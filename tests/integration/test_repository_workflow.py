from qa_sentinel.application import QASentinelApplication, ProjectExecutionResolver
"""Mocked real turns, durable read evidence, and unchanged gates/mutation boundary."""
from qa_sentinel.projects import ProjectWorkspaceBinding, ProjectRuntimeRegistry
from qa_sentinel.domain.project import Project
from dataclasses import dataclass
from pathlib import Path
from hashlib import sha256
from uuid import uuid4
import json
import pytest
from qa_sentinel.agents.real import RealAgentRuntime
from qa_sentinel.agents.composite import CompositeAgentRuntime
from qa_sentinel.agents.fake import FakeAgentRuntime
from qa_sentinel.agents.scenarios import division_scenario, DIVISION_REQUIREMENT
from qa_sentinel.models.config import RoleModelConfig
from qa_sentinel.models.base import ModelSettings
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from qa_sentinel.schemas.repository import ResearchTurn, PlannerTurn, RepositoryToolRequest
from qa_sentinel.schemas.mutation import ImplementationProposal
from qa_sentinel.repository.config import RepositoryReadConfig
from qa_sentinel.repository.service import RepositoryReadService
from qa_sentinel.mutation.contracts import MutationConfig
from qa_sentinel.mutation.service import MutationService
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.enums import AgentName as A, TaskState as S, ArtifactType as AT
from qa_sentinel.orchestration.runner import WorkflowRunner, RunnerStoppedError
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.database import create_engine, create_session_factory
from qa_sentinel.persistence.repositories import HistoryRepository, ArtifactRepository
from qa_sentinel.execution.fake import FakeTestResultProvider
from qa_sentinel.execution.command_policy import ExecutionConfig, CommandRequest
from qa_sentinel.execution.command_runner import CommandRunner
from qa_sentinel.execution.pytest_runner import PytestRunner
from qa_sentinel.execution.service import TestExecutionService as ExecutionService, PytestTestResultProvider

INITIAL = "def add(a, b):\n    return a + b\n"
GUARDED = INITIAL + "\ndef divide(a, b):\n    if b == 0:\n        raise ValueError('zero divisor')\n    return a / b\n"


def values():
    scenario, _ = division_scenario()
    return {role: responses[0].output for role, responses in scenario.responses.items()}


def tool_turn(tool="READ_FILE", path="calculator.py", role=A.RESEARCHER, **options):
    args = dict(tool=tool, path=path, **options)
    if tool == "LIST_FILES":
        args.setdefault("depth", 1)
        args.setdefault("limit", 20)
    elif tool == "SEARCH_TEXT":
        args.setdefault("query", "add")
        args.setdefault("limit", 20)
    cls = ResearchTurn if role == A.RESEARCHER else PlannerTurn
    return cls(kind="TOOL_REQUEST", tool_request=RepositoryToolRequest(request_id=uuid4(), arguments=args), final_output=None)


def final(output, role=A.RESEARCHER):
    cls = ResearchTurn if role == A.RESEARCHER else PlannerTurn
    return cls(kind="FINAL_OUTPUT", tool_request=None, final_output=output)


def cited_research(call):
    data = json.loads(call["input"][0]["content"])
    evidence = data["repository_results"]
    assert evidence[-1]["result"]["data"]["content"] == INITIAL
    output = values()[A.RESEARCHER].model_dump(mode="json")
    output["findings"][0]["evidence"] = [e["evidence_ref"] for e in evidence]
    output["findings"][0]["summary"] = "FACT: calculator.py implements add; division is absent."
    return final(output)


@dataclass
class Harness:
    task: object
    factory: object
    root: Path
    reader: object
    runtime: object
    provider: object
    runner: object
    mock: object
    mutation: object = None


def setup(factory, tmp_path, mock, *, config=None, real_implementation=False, project=None):
    project = project or Project(key="test-"+uuid4().hex, name="Repository fixture owner")
    task = Task(project_id=project.id, title="Task 10 repository evidence", requirement=DIVISION_REQUIREMENT)
    root = tmp_path / "target-repository"
    (root / "tests").mkdir(parents=True)
    (root / "calculator.py").write_bytes(INITIAL.encode())
    (root / "README.md").write_bytes(b"Small arithmetic package\n")
    (root / "tests/test_calculator.py").write_bytes(b"from calculator import add\ndef test_add():\n    assert add(2,3) == 5\n")
    reader = RepositoryReadService(RepositoryReadConfig(root, **(config or {})))
    models = RoleModelConfig(**{name: ModelSettings(model="real-" + name, reasoning_effort="high")
                               for name in ("researcher", "planner", "implementer", "reviewer")})
    real = RealAgentRuntime(OpenAIModelAdapter(client=mock.client), models, repository_tools=True)
    scenario, runs = division_scenario()
    fake = FakeAgentRuntime(scenario)
    routes = {r: real if r in {A.RESEARCHER, A.PLANNER} else fake for r in A}
    mutation = None
    if real_implementation:
        routes.update({A.IMPLEMENTER: real, A.REVIEWER: real})
        mutation = MutationService(MutationConfig(root))
        (root / "tests/test_calculator.py").write_bytes(
            b"import pytest\nfrom calculator import add, divide\n"
            b"def test_add():\n    assert add(2,3) == 5\n"
            b"def test_divide():\n    assert divide(5,2) == 2.5\n"
            b"def test_zero():\n    with pytest.raises(ValueError):\n        divide(1,0)\n")
        execution = ExecutionService(factory, PytestRunner(CommandRunner(ExecutionConfig(root,
            python_path=(Path(pytest.__file__).resolve().parents[1],)))), workspace_binding=ProjectWorkspaceBinding(project_id=task.project_id, workspace_root=root))
        provider = PytestTestResultProvider(execution, CommandRequest(cwd=str(root), args=("-m", "pytest", "tests", "-q")))
    else:
        provider = FakeTestResultProvider(runs)
    runtime = CompositeAgentRuntime(routes)
    with UnitOfWork(factory) as uow:
        uow.projects.add(project)
        uow.tasks.add(task)
        uow.commit()
    runner = WorkflowRunner(factory, runtime, provider, repository_service=reader, mutation_service=mutation, workspace_binding=ProjectWorkspaceBinding(project_id=task.project_id, workspace_root=root))
    return Harness(task, factory, root, reader, runtime, provider, runner, mock, mutation)


def recreated(h, factory=None, reader=None):
    return WorkflowRunner(factory or h.factory, h.runtime, h.provider,
        repository_service=reader or h.reader, mutation_service=h.mutation, workspace_binding=ProjectWorkspaceBinding(project_id=h.task.project_id, workspace_root=h.root))


def snapshot(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("discovery", ["LIST_FILES", "SEARCH_TEXT"])
def test_discover_read_cite_plan_gate_and_reopen_zero_mutation(migrated_factory, tmp_path, mock_openai, discovery):
    factory, engine, _ = migrated_factory
    def selected_read(call):
        data = json.loads(call["input"][0]["content"])
        result = data["repository_results"][0]["result"]["data"]
        paths = [e["path"] for e in result["entries" if discovery == "LIST_FILES" else "matches"]]
        assert "calculator.py" in paths
        return tool_turn(path="calculator.py")
    mock = mock_openai([tool_turn(discovery, "."), selected_read, cited_research,
        tool_turn(path="README.md", role=A.PLANNER), final(values()[A.PLANNER], A.PLANNER)])
    h = setup(factory, tmp_path, mock)
    before = snapshot(h.root)
    assert h.runner.run(h.task.id).state == S.DONE
    assert snapshot(h.root) == before
    initial = json.loads(mock.calls[0]["input"][0]["content"])
    assert initial["repository_results"] == [] and initial["repository_evidence"] == []
    assert INITIAL not in str(initial)
    assert len(mock.calls) == 5
    for call in mock.calls:
        assert call["tools"] == [] and call["tool_choice"] == "none" and call["store"] is False
        assert "previous_response_id" not in call and "conversation" not in call
    fresh = create_engine(str(engine.url))
    try:
        with UnitOfWork(create_session_factory(fresh)) as uow:
            invs = uow.invocations.list_by_task(h.task.id)
            research, = [i for i in invs if i.agent == A.RESEARCHER]
            planner, = [i for i in invs if i.agent == A.PLANNER]
            assert research.status.value == planner.status.value == "COMPLETED"
            evidence = [a for a in uow.artifacts.list_by_task(h.task.id) if a.artifact_type == AT.REPOSITORY_EVIDENCE]
            assert len(evidence) == 3
            reads = sorted([a for a in evidence if a.invocation_id == research.id], key=lambda a: a.content["call_index"])
            assert [a.content["call_index"] for a in reads] == [1, 2]
            canonical, = [a for a in uow.artifacts.list_by_task(h.task.id) if a.artifact_type == AT.RESEARCH]
            assert canonical.content["findings"][0]["evidence"] == ["artifact:" + str(a.id) for a in reads]
            events = uow.history.list_events(h.task.id)
            turns = [e for e in events if e.event_type == "MODEL_TURN_COMPLETED"]
            assert len(turns) == 5 and all(e.payload["model_metadata"]["total_tokens"] == 30 for e in turns)
            assert any(e.event_type == "AGENT_COMPLETED" and e.correlation.invocation_id == research.id
                and e.payload["repository_evidence_refs"] == canonical.content["findings"][0]["evidence"] for e in events)
            assert any(t.from_state == S.PLANNING and t.to_state == S.IMPLEMENTING for t in uow.history.list_transitions(h.task.id))
            assert all(a.producer_agent is None and a.producer_model is None for a in evidence)
    finally:
        fresh.dispose()


def test_tool_budget_stops_without_extra_service_call(migrated_factory, tmp_path, mock_openai, monkeypatch):
    factory, _, _ = migrated_factory
    mock = mock_openai([tool_turn() for _ in range(4)])
    h = setup(factory, tmp_path, mock, config={"max_tool_calls_per_agent_invocation": 2})
    calls = []
    original = h.reader.execute
    def execute(*a, **k):
        calls.append(1)
        return original(*a, **k)
    monkeypatch.setattr(h.reader, "execute", execute)
    result = h.runner.run(h.task.id)
    assert result.state == S.BLOCKED and result.resume_state == S.RESEARCHING
    assert len(calls) == 2 and len(mock.calls) == 3
    with UnitOfWork(factory) as uow:
        assert not any(a.artifact_type == AT.RESEARCH for a in uow.artifacts.list_by_task(h.task.id))
        assert any(e.code == "TOOL_CALL_BUDGET_EXHAUSTED" for e in uow.history.list_errors(h.task.id))
        evidence = sorted([a for a in uow.artifacts.list_by_task(h.task.id) if a.artifact_type == AT.REPOSITORY_EVIDENCE],
                          key=lambda a: a.content["call_index"])
        assert evidence[-1].content["result"]["error_code"] == "TOOL_CALL_BUDGET_EXHAUSTED"


@pytest.mark.parametrize("path,code", [("../../outside.txt", "WORKSPACE_ESCAPE"), (".git/config", "PROTECTED_PATH"),
                                     (".env", "PROTECTED_PATH")])
def test_denial_stops_without_hidden_retry_or_authority(migrated_factory, tmp_path, mock_openai, path, code):
    factory, _, _ = migrated_factory
    mock = mock_openai([tool_turn(path=path)])
    h = setup(factory, tmp_path, mock)
    (h.root / ".env").write_bytes(b"synthetic-private-content")
    before = snapshot(h.root)
    assert h.runner.run(h.task.id).state == S.BLOCKED
    assert snapshot(h.root) == before
    assert "synthetic-private-content" not in json.dumps(mock.calls)
    with UnitOfWork(factory) as uow:
        assert not any(t.to_state == S.PLANNING for t in uow.history.list_transitions(h.task.id))
        assert not any(e.event_type == "RETRY_SCHEDULED" for e in uow.history.list_events(h.task.id))
        evidence, = [a for a in uow.artifacts.list_by_task(h.task.id) if a.artifact_type == AT.REPOSITORY_EVIDENCE]
        assert evidence.content["result"]["error_code"] == code and evidence.content["result"]["data"] is None
    assert len(mock.calls) == 1


@pytest.mark.parametrize("boundary", ["after-result", "after-turn-final"])
def test_safe_resume_reuses_results_or_final_without_read_replay(migrated_factory, tmp_path, mock_openai, monkeypatch, boundary):
    factory, engine, _ = migrated_factory
    mock = mock_openai([tool_turn(), cited_research, final(values()[A.PLANNER], A.PLANNER)])
    h = setup(factory, tmp_path, mock)
    original = HistoryRepository.append_event
    def fail(self, event):
        if boundary == "after-result" and event.event_type == "MODEL_TURN_STARTED" and event.payload["turn_index"] == 2:
            raise RuntimeError("injected before next turn reservation")
        if boundary == "after-turn-final" and event.event_type == "AGENT_COMPLETED":
            raise RuntimeError("injected canonical commit failure")
        original(self, event)
    monkeypatch.setattr(HistoryRepository, "append_event", fail)
    with pytest.raises(RuntimeError):
        h.runner.run(h.task.id)
    assert len(mock.calls) == (1 if boundary == "after-result" else 2)
    monkeypatch.setattr(HistoryRepository, "append_event", original)
    monkeypatch.setattr(h.reader, "execute", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Duplicate read")))
    fresh = create_engine(str(engine.url))
    try:
        assert recreated(h, create_session_factory(fresh)).run(h.task.id).state == S.DONE
    finally:
        fresh.dispose()
    assert len(mock.calls) == 3
    with UnitOfWork(factory) as uow:
        assert len([i for i in uow.invocations.list_by_task(h.task.id) if i.agent == A.RESEARCHER]) == 1


def test_unresolved_model_turn_stops_restart_no_reissue(migrated_factory, tmp_path, mock_openai, monkeypatch):
    factory, _, _ = migrated_factory
    mock = mock_openai([tool_turn(), cited_research])
    h = setup(factory, tmp_path, mock)
    original = HistoryRepository.append_event
    def fail(self, event):
        original(self, event)
        if event.event_type == "MODEL_TURN_COMPLETED" and event.payload["turn_index"] == 2:
            raise RuntimeError("injected model turn completion failure")
    monkeypatch.setattr(HistoryRepository, "append_event", fail)
    with pytest.raises(RuntimeError):
        h.runner.run(h.task.id)
    monkeypatch.setattr(HistoryRepository, "append_event", original)
    with pytest.raises(RunnerStoppedError, match="UNRESOLVED_MODEL_TURN"):
        recreated(h).run(h.task.id)
    assert len(mock.calls) == 2
    with UnitOfWork(factory) as uow:
        inv, = uow.invocations.list_by_task(h.task.id)
        assert inv.status.value == "STARTED"
        assert not any(a.artifact_type == AT.RESEARCH for a in uow.artifacts.list_by_task(h.task.id))


@pytest.mark.parametrize("failure", [{}, "timeout", 429])
def test_existing_schema_and_provider_retry_ownership(migrated_factory, tmp_path, mock_openai, failure):
    factory, _, _ = migrated_factory
    mock = mock_openai([failure, tool_turn(), cited_research, final(values()[A.PLANNER], A.PLANNER)])
    h = setup(factory, tmp_path, mock)
    assert h.runner.run(h.task.id).state == S.DONE
    with UnitOfWork(factory) as uow:
        researchers = sorted([i for i in uow.invocations.list_by_task(h.task.id) if i.agent == A.RESEARCHER], key=lambda i: i.attempt)
        assert [i.status.value for i in researchers] == ["FAILED", "COMPLETED"]
        assert sum(e.event_type == "RETRY_SCHEDULED" for e in uow.history.list_events(h.task.id)) == 1
        assert any(e.event_type == "MODEL_TURN_FAILED" for e in uow.history.list_events(h.task.id))
    assert len(mock.calls) == 4


def test_repeated_malformed_turn_never_executes_a_tool(migrated_factory, tmp_path, mock_openai, monkeypatch):
    factory, _, _ = migrated_factory
    mock = mock_openai([{}, {}])
    h = setup(factory, tmp_path, mock)
    monkeypatch.setattr(h.reader, "execute", lambda *a, **k: (_ for _ in ()).throw(AssertionError("No tool")))
    assert h.runner.run(h.task.id).state == S.BLOCKED
    assert len(mock.calls) == 2 and "OUTPUT_SCHEMA_INVALID" in mock.calls[1]["instructions"]
    with UnitOfWork(factory) as uow:
        assert not uow.artifacts.list_by_task(h.task.id)


def test_context_limit_does_not_supply_partial_file_or_extra_provider_call(migrated_factory, tmp_path, mock_openai):
    factory, _, _ = migrated_factory
    mock = mock_openai([tool_turn()])
    h = setup(factory, tmp_path, mock)
    content = "x" * 65000
    (h.root / "calculator.py").write_bytes(content.encode())
    assert h.runner.run(h.task.id).state == S.BLOCKED
    assert len(mock.calls) == 1
    with UnitOfWork(factory) as uow:
        evidence, = [a for a in uow.artifacts.list_by_task(h.task.id) if a.artifact_type == AT.REPOSITORY_EVIDENCE]
        assert evidence.content["result"]["data"]["content"] == content
        assert any(e.code == "MODEL_CONTEXT_LIMIT" for e in uow.history.list_errors(h.task.id))


def test_root_configuration_drift_stops_resume(migrated_factory, tmp_path, mock_openai, monkeypatch):
    factory, _, _ = migrated_factory
    mock = mock_openai([tool_turn()])
    h = setup(factory, tmp_path, mock)
    original = HistoryRepository.append_event
    def fail(self, event):
        if event.event_type == "MODEL_TURN_STARTED" and event.payload["turn_index"] == 2:
            raise RuntimeError("pause")
        original(self, event)
    monkeypatch.setattr(HistoryRepository, "append_event", fail)
    with pytest.raises(RuntimeError):
        h.runner.run(h.task.id)
    monkeypatch.setattr(HistoryRepository, "append_event", original)
    reader = RepositoryReadService(RepositoryReadConfig(h.root, max_tool_calls_per_agent_invocation=1))
    with pytest.raises(RunnerStoppedError, match="CONTEXT_REQUIRES_RECONCILIATION"):
        recreated(h, reader=reader).run(h.task.id)
    assert len(mock.calls) == 1


def test_repository_assisted_plan_keeps_real_implementer_snapshots_and_reviewer_plain(migrated_factory, tmp_path, mock_openai):
    factory, _, _ = migrated_factory
    def implementation(call):
        data = json.loads(call["input"][0]["content"])
        assert "repository_results" not in data
        source, = data["source_files"]
        assert source["content"] == INITIAL and source["sha256"] == sha256(INITIAL.encode()).hexdigest()
        return ImplementationProposal(implementation_status="COMPLETED", implementation_summary="Add division",
            plan_steps=[dict(step_id="step-1", status="COMPLETED")], mutations=[dict(path="calculator.py",
                operation="MODIFY", expected_sha256=source["sha256"], content=GUARDED, reason="Plan-authorized change")],
            tests_added_or_modified=[], assumptions=[], known_issues=[], deviations=[])
    mock = mock_openai([tool_turn("LIST_FILES", "."), tool_turn(), cited_research,
        final(values()[A.PLANNER], A.PLANNER), implementation, values()[A.REVIEWER]])
    h = setup(factory, tmp_path, mock, real_implementation=True)
    assert h.runner.run(h.task.id).state == S.DONE
    assert h.root.joinpath("calculator.py").read_bytes() == GUARDED.encode()
    assert not h.runtime.repository_turns(A.IMPLEMENTER) and not h.runtime.repository_turns(A.REVIEWER)
    assert mock.calls[4]["text"]["format"]["name"] == "ImplementationProposal"
    assert mock.calls[5]["text"]["format"]["name"] == "ReviewOutput"
    assert "repository_results" not in json.loads(mock.calls[5]["input"][0]["content"])
    with UnitOfWork(factory) as uow:
        run, = uow.history.list_test_runs(h.task.id)
        assert run.passed_count == 3 and run.outcome.value == "PASS"
        assert any(e.event_type == "MUTATION_APPLIED" for e in uow.history.list_events(h.task.id))
        assert all(a.invocation_id != uow.tasks.get(h.task.id).current_invocation_id
            for a in uow.artifacts.list_by_task(h.task.id) if a.artifact_type == AT.REPOSITORY_EVIDENCE)


def test_planner_read_cannot_bypass_needs_research(migrated_factory, tmp_path, mock_openai):
    factory, _, _ = migrated_factory
    plan = values()[A.PLANNER].model_dump(mode="json")
    plan["decision"] = "NEEDS_RESEARCH"
    mock = mock_openai([final(values()[A.RESEARCHER]), tool_turn(path="README.md", role=A.PLANNER), final(plan, A.PLANNER)])
    h = setup(factory, tmp_path, mock)
    for _ in range(3):
        h.runner._step(h.runner._task(h.task.id))
    assert h.runner._task(h.task.id).state == S.RESEARCHING
    with UnitOfWork(factory) as uow:
        assert any(g.gate_name == "PLAN_GATE" and g.result.value == "FAIL" for g in uow.history.list_gate_evaluations(h.task.id))
        assert not any(t.to_state == S.IMPLEMENTING for t in uow.history.list_transitions(h.task.id))
    assert len(mock.calls) == 3


def test_refusal_has_no_read_and_no_raw_refusal_persistence(migrated_factory, tmp_path, mock_openai, monkeypatch):
    factory, _, _ = migrated_factory
    mock = mock_openai(["refusal"])
    h = setup(factory, tmp_path, mock)
    monkeypatch.setattr(h.reader, "execute", lambda *a, **k: (_ for _ in ()).throw(AssertionError("No read")))
    assert h.runner.run(h.task.id).state == S.BLOCKED
    with UnitOfWork(factory) as uow:
        assert not uow.artifacts.list_by_task(h.task.id)
        persisted = str(uow.history.list_events(h.task.id)) + str(uow.history.list_errors(h.task.id))
        assert "synthetic-sensitive-refusal" not in persisted and "synthetic-test-credential" not in persisted
    assert len(mock.calls) == 1
    application = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]), []))
    usage = application.get_task_model_usage(h.task.id)
    assert usage.usage.records == 1 and usage.usage.total_tokens.total == 30
    assert usage.invocations[0].configured_model == "real-researcher"



def test_explicit_reads_record_drift_without_snapshot_isolation(migrated_factory, tmp_path, mock_openai):
    factory, _, _ = migrated_factory
    mock = mock_openai([tool_turn()])
    h = setup(factory, tmp_path, mock)
    def second(call):
        data = json.loads(call["input"][0]["content"])
        assert data["repository_results"][0]["result"]["data"]["content"] == INITIAL
        (h.root / "calculator.py").write_bytes(b"changed by external trusted writer\n")
        return tool_turn()
    def finished(call):
        evidence = json.loads(call["input"][0]["content"])["repository_results"]
        assert evidence[0]["result"]["data"]["sha256"] != evidence[1]["result"]["data"]["sha256"]
        return final(values()[A.RESEARCHER])
    mock.queue.extend([second, finished, final(values()[A.PLANNER], A.PLANNER)])
    assert h.runner.run(h.task.id).state == S.DONE
    with UnitOfWork(factory) as uow:
        artifacts = sorted([a for a in uow.artifacts.list_by_task(h.task.id) if a.artifact_type == AT.REPOSITORY_EVIDENCE],
                           key=lambda a: a.content["call_index"])
        assert [a.content["result"]["data"]["content"] for a in artifacts] == [INITIAL, "changed by external trusted writer\n"]


def test_result_commit_failure_reuses_model_request_but_repeats_only_unrecorded_read(migrated_factory, tmp_path, mock_openai, monkeypatch):
    factory, _, _ = migrated_factory
    mock = mock_openai([tool_turn(), cited_research, final(values()[A.PLANNER], A.PLANNER)])
    h = setup(factory, tmp_path, mock)
    original = ArtifactRepository.add
    def fail(self, artifact):
        original(self, artifact)
        if artifact.artifact_type == AT.REPOSITORY_EVIDENCE:
            raise RuntimeError("injected read evidence commit failure")
    monkeypatch.setattr(ArtifactRepository, "add", fail)
    with pytest.raises(RuntimeError):
        h.runner.run(h.task.id)
    assert len(mock.calls) == 1
    with UnitOfWork(factory) as uow:
        assert not uow.artifacts.list_by_task(h.task.id)
    monkeypatch.setattr(ArtifactRepository, "add", original)
    assert recreated(h).run(h.task.id).state == S.DONE
    assert len(mock.calls) == 3
