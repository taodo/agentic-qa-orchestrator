"""Mock Responses reasoning, deterministic source mutation, and actual target pytest."""
from qa_sentinel.projects import ProjectWorkspaceBinding
from qa_sentinel.domain.project import Project
from uuid import uuid4
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from contextlib import nullcontext
import json
import pytest
from qa_sentinel.agents.real import RealAgentRuntime
from qa_sentinel.agents.scenarios import division_scenario, DIVISION_REQUIREMENT
from qa_sentinel.domain.enums import AgentName as A, TaskState as S, ArtifactType as AT
from qa_sentinel.domain.task import Task
from qa_sentinel.models.config import RoleModelConfig
from qa_sentinel.models.base import ModelSettings
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from qa_sentinel.mutation.contracts import MutationConfig, MutationReconciliationRequired
from qa_sentinel.mutation.service import MutationService
from qa_sentinel.schemas.mutation import ImplementationProposal
from qa_sentinel.execution.command_policy import ExecutionConfig, CommandRequest
from qa_sentinel.execution.command_runner import CommandRunner
from qa_sentinel.execution.pytest_runner import PytestRunner
from qa_sentinel.execution.service import TestExecutionService as ExecutionService, PytestTestResultProvider
from qa_sentinel.orchestration.runner import WorkflowRunner, RunnerStoppedError
from qa_sentinel.orchestration.reliability_policy import ReliabilityConfig, FailureIdentity
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.database import create_engine, create_session_factory
from qa_sentinel.persistence.repositories import ArtifactRepository, HistoryRepository

INITIAL = "def add(a, b):\n    return a + b\n"
UNGUARDED = INITIAL + "\ndef divide(a, b):\n    return a / b\n"
GUARDED = INITIAL + "\ndef divide(a, b):\n    if b == 0:\n        raise ValueError('zero divisor')\n    return a / b\n"
TESTS = ("import pytest\nfrom calculator import add, divide\n"
    "def test_add():\n    assert add(2, 3) == 5\n"
    "def test_divide():\n    assert divide(5, 2) == 2.5\n"
    "def test_divide_by_zero():\n    with pytest.raises(ValueError):\n        divide(1, 0)\n")


def outputs():
    scenario, _ = division_scenario(repair=True)
    return {role: sequence[0].output for role, sequence in scenario.responses.items()}


def response(content=GUARDED, *, create=False, extra=(), edit=None, status="COMPLETED", deviations=()):
    def make(call):
        data = json.loads(call["input"][0]["content"])
        if edit:
            edit()
        mutations = [dict(path="calculator.py", operation="CREATE" if create else "MODIFY",
            expected_sha256=None if create else data["source_files"][0]["sha256"],
            content=content, reason="Add planned division support")]
        return ImplementationProposal(implementation_status=status, implementation_summary="Division support",
            plan_steps=[dict(step_id="step-1", status="COMPLETED")], mutations=mutations + list(extra),
            tests_added_or_modified=["unrelated_test.py"], assumptions=[], known_issues=[], deviations=deviations)
    return make


@dataclass
class Harness:
    task: object
    factory: object
    root: Path
    mutation: object
    runtime: object
    provider: object
    runner: object
    mock: object


def setup(factory, tmp_path, mock, *, create=False, config=None):
    task = Task(project_id=uuid4(), title="Task 9 guarded division", requirement=DIVISION_REQUIREMENT)
    root = tmp_path / "target-project"
    (root / "tests").mkdir(parents=True)
    if not create:
        (root / "calculator.py").write_bytes(INITIAL.encode())
    (root / "tests/test_calculator.py").write_bytes(TESTS.encode())
    (root / "unrelated.txt").write_bytes(b"preserve unrelated source")
    models = RoleModelConfig(**{field: ModelSettings(model="real-" + field, reasoning_effort="high")
        for field in ("researcher", "planner", "implementer", "test_analyzer", "investigator", "investigator_escalated", "reviewer")})
    runtime = RealAgentRuntime(OpenAIModelAdapter(client=mock.client), models)
    mutation = MutationService(MutationConfig(root))
    service = ExecutionService(factory, PytestRunner(CommandRunner(ExecutionConfig(root,
        python_path=(Path(pytest.__file__).resolve().parents[1],)))), workspace_binding=ProjectWorkspaceBinding(project_id=task.project_id, workspace_root=root))
    provider = PytestTestResultProvider(service, CommandRequest(cwd=str(root), args=("-m", "pytest", "tests", "-q")))
    with UnitOfWork(factory) as uow:
        uow.projects.add(Project(id=task.project_id,key="test-"+task.project_id.hex,name="Test owner")); uow.tasks.add(task)
        uow.commit()
    runner = WorkflowRunner(factory, runtime, provider, mutation_service=mutation, reliability_config=config, workspace_binding=provider.workspace_binding)
    return Harness(task, factory, root, mutation, runtime, provider, runner, mock)


def advance(h, stage):
    for _ in range(20):
        task = h.runner._task(h.task.id)
        if task.state == stage:
            return task
        assert task.state not in {S.DONE, S.BLOCKED, S.FAILED}
        h.runner._step(task)
    raise AssertionError("Stage not reached")


def restart(h, factory=None):
    return WorkflowRunner(factory or h.factory, h.runtime, h.provider, mutation_service=h.mutation, workspace_binding=h.provider.workspace_binding)


@pytest.mark.parametrize("create", [False, True])
def test_happy_real_implementer_actual_mutation_test_done(migrated_factory, tmp_path, mock_openai, create):
    factory, _, _ = migrated_factory
    values = outputs()
    plan = values[A.PLANNER]
    if create:
        plan = plan.model_copy(update={"files_to_create": ("calculator.py",), "files_to_modify": ()})
    mock = mock_openai([values[A.RESEARCHER], plan, response(create=create), values[A.REVIEWER]])
    h = setup(factory, tmp_path, mock, create=create)
    assert h.runner.run(h.task.id).state == S.DONE
    assert (h.root / "calculator.py").read_bytes() == GUARDED.encode()
    assert (h.root / "unrelated.txt").read_bytes() == b"preserve unrelated source"
    with UnitOfWork(factory) as uow:
        artifacts = uow.artifacts.list_by_task(h.task.id)
        canonical, = [a for a in artifacts if a.artifact_type == AT.IMPLEMENTATION]
        proposed, = [a for a in artifacts if a.artifact_type == AT.IMPLEMENTATION_PROPOSAL]
        assert proposed.invocation_id == canonical.invocation_id
        assert canonical.content["changed_files"][0]["change_type"] == ("CREATED" if create else "MODIFIED")
        assert canonical.content["commands_executed"] == [] and canonical.content["tests_added_or_modified"] == []
        run, = uow.history.list_test_runs(h.task.id)
        assert run.implementation_artifact_id == canonical.id and run.passed_count == 3
        assert run.environment == "local-pytest" and run.outcome.value == "PASS"
        events = uow.history.list_events(h.task.id)
        assert sum(e.event_type == "MUTATION_RESERVED" for e in events) == 1
        assert sum(e.event_type == "MUTATION_APPLIED" for e in events) == 1
    for call in mock.calls:
        assert call["tools"] == [] and call["tool_choice"] == "none" and call["store"] is False
        assert "previous_response_id" not in call and "conversation" not in call
    assert mock.calls[2]["text"]["format"]["name"] == "ImplementationProposal"
    assert mock.calls[2]["text"]["format"]["strict"] is True
    data = json.loads(mock.calls[2]["input"][0]["content"])
    assert "unrelated.txt" not in str(data) and str(h.root) not in str(data)
    assert data["source_files"] == ([] if create else [dict(path="calculator.py", content=INITIAL,
        sha256=sha256(INITIAL.encode()).hexdigest(), size_bytes=len(INITIAL))])


def test_actual_failure_repair_fresh_hash_and_reopened_provenance(migrated_factory, tmp_path, mock_openai):
    factory, engine, _ = migrated_factory
    v = outputs()
    mock = mock_openai([v[A.RESEARCHER], v[A.PLANNER], response(UNGUARDED),
        v[A.TEST_ANALYZER], v[A.INVESTIGATOR], response(GUARDED), v[A.REVIEWER]])
    h = setup(factory, tmp_path, mock)
    assert h.runner.run(h.task.id).state == S.DONE
    assert (h.root / "calculator.py").read_bytes() == GUARDED.encode()
    first = json.loads(mock.calls[2]["input"][0]["content"])
    repair = json.loads(mock.calls[5]["input"][0]["content"])
    assert first["source_files"][0]["sha256"] == sha256(INITIAL.encode()).hexdigest()
    assert repair["source_files"][0]["sha256"] == sha256(UNGUARDED.encode()).hexdigest()
    assert repair["investigation"]["recommended_action"]["type"] == "CODE_FIX"
    assert repair["previous_implementation_ref"] and repair["evidence_refs"]
    fresh = create_engine(str(engine.url))
    try:
        with UnitOfWork(create_session_factory(fresh)) as uow:
            runs = sorted(uow.history.list_test_runs(h.task.id), key=lambda r: r.started_at)
            assert [r.outcome.value for r in runs] == ["FAIL", "PASS"]
            assert [r.failed_count for r in runs] == [1, 0]
            assert runs[0].implementation_artifact_id != runs[1].implementation_artifact_id
            invocations = uow.invocations.list_by_task(h.task.id)
            assert len(invocations) == 7 and all(i.status.value == "COMPLETED" for i in invocations)
            implementers = sorted([i for i in invocations if i.agent == A.IMPLEMENTER], key=lambda i: i.attempt)
            assert [i.model for i in implementers] == ["real-implementer", "real-implementer"]
            assert [i.attempt for i in implementers] == [1, 2]
            assert uow.tasks.get(h.task.id).defect_cycle == 1
            events = uow.history.list_events(h.task.id)
            assert sum(e.event_type == "MUTATION_APPLIED" for e in events) == 2
            for inv in implementers:
                artifacts = [a for a in uow.artifacts.list_by_task(h.task.id) if a.invocation_id == inv.id]
                assert {a.artifact_type for a in artifacts} == {AT.IMPLEMENTATION, AT.IMPLEMENTATION_PROPOSAL}
                assert all(a.producer_model == inv.model and a.producer_agent == inv.agent for a in artifacts)
                assert any(e.event_type == "AGENT_COMPLETED" and e.correlation.invocation_id == inv.id
                    and e.payload["model_metadata"]["total_tokens"] == 30 for e in events)
            proposals = sorted([a for a in uow.artifacts.list_by_task(h.task.id)
                if a.artifact_type == AT.IMPLEMENTATION_PROPOSAL],
                key=lambda a: next(i.attempt for i in implementers if i.id == a.invocation_id))
            assert [a.content["mutations"][0]["content"] for a in proposals] == [UNGUARDED, GUARDED]
            edges = {(t.from_state.value, t.to_state.value) for t in uow.history.list_transitions(h.task.id)}
            assert {("TESTING", "ANALYZING"), ("ANALYZING", "INVESTIGATING"),
                    ("INVESTIGATING", "IMPLEMENTING"), ("REVIEWING", "DONE")} <= edges
            persisted = str(events) + str(uow.artifacts.list_by_task(h.task.id))
            assert "synthetic-test-credential" not in persisted and "authorization" not in persisted
    finally:
        fresh.dispose()
    assert len(mock.calls) == 7


@pytest.mark.parametrize("kind", ["stale", "unauthorized", "protected", "replan"])
def test_rejected_proposal_no_canonical_no_partial_write(migrated_factory, tmp_path, mock_openai, kind):
    factory, _, _ = migrated_factory
    v = outputs()
    extra = ()
    if kind in {"unauthorized", "protected"}:
        extra = (dict(path="outside.py" if kind == "unauthorized" else ".env", operation="CREATE",
            expected_sha256=None, content="synthetic-rejected-content", reason="attempt"),)
    mock = mock_openai([v[A.RESEARCHER], v[A.PLANNER]])
    h = setup(factory, tmp_path, mock)
    edit = lambda: (h.root / "calculator.py").write_bytes(b"newer\n")
    mock.queue.append(response(extra=extra, edit=edit if kind == "stale" else None,
        deviations=(dict(description="Change plan", requires_replan=True),) if kind == "replan" else ()))
    with pytest.raises(RunnerStoppedError) if kind in {"stale", "replan"} else nullcontext():
        result = h.runner.run(h.task.id)
        assert result.state == S.FAILED
    assert (h.root / "calculator.py").read_bytes() == (b"newer\n" if kind == "stale" else INITIAL.encode())
    assert not (h.root / "outside.py").exists() and not (h.root / ".env").exists()
    with UnitOfWork(factory) as uow:
        assert not any(a.artifact_type == AT.IMPLEMENTATION for a in uow.artifacts.list_by_task(h.task.id))
        denied, = [a for a in uow.artifacts.list_by_task(h.task.id) if a.artifact_type == AT.IMPLEMENTATION_PROPOSAL]
        assert "mutations" not in denied.content and "synthetic-rejected-content" not in str(denied)
        assert not uow.history.list_test_runs(h.task.id)
    assert len(mock.calls) == 3


@pytest.mark.parametrize("phase", ["reservation", "completion"])
def test_persistence_failure_requires_reconciliation_without_reapply(migrated_factory, tmp_path, mock_openai, monkeypatch, phase):
    factory, _, _ = migrated_factory
    v = outputs()
    mock = mock_openai([v[A.RESEARCHER], v[A.PLANNER], response()])
    h = setup(factory, tmp_path, mock)
    task = advance(h, S.IMPLEMENTING)
    original = ArtifactRepository.add
    def fail(self, artifact):
        original(self, artifact)
        if artifact.artifact_type == (AT.IMPLEMENTATION_PROPOSAL if phase == "reservation" else AT.IMPLEMENTATION):
            raise RuntimeError("injected persistence failure")
    monkeypatch.setattr(ArtifactRepository, "add", fail)
    with pytest.raises(MutationReconciliationRequired if phase == "completion" else RuntimeError):
        h.runner._step(task)
    assert (h.root / "calculator.py").read_bytes() == (GUARDED.encode() if phase == "completion" else INITIAL.encode())
    monkeypatch.setattr(ArtifactRepository, "add", original)
    with pytest.raises(RunnerStoppedError, match="unfinished"):
        restart(h).run(task.id)
    with UnitOfWork(factory) as uow:
        inv, = [i for i in uow.invocations.list_by_task(task.id) if i.agent == A.IMPLEMENTER]
        assert inv.status.value == "STARTED"
        assert not any(a.artifact_type == AT.IMPLEMENTATION for a in uow.artifacts.list_by_task(task.id))
        assert sum(e.event_type == "MUTATION_RESERVED" for e in uow.history.list_events(task.id)) == (phase == "completion")
    assert len(mock.calls) == 3


def test_completion_reused_after_transition_failure_without_model_or_reapply(migrated_factory, tmp_path, mock_openai, monkeypatch):
    factory, _, _ = migrated_factory
    v = outputs()
    mock = mock_openai([v[A.RESEARCHER], v[A.PLANNER], response(), v[A.REVIEWER]])
    h = setup(factory, tmp_path, mock)
    task = advance(h, S.IMPLEMENTING)
    original = HistoryRepository.append_event
    def fail(self, event):
        original(self, event)
        if event.event_type == "STATE_TRANSITIONED":
            raise RuntimeError("injected transition failure")
    monkeypatch.setattr(HistoryRepository, "append_event", fail)
    with pytest.raises(RuntimeError):
        h.runner._step(task)
    monkeypatch.setattr(HistoryRepository, "append_event", original)
    monkeypatch.setattr(h.mutation, "apply", lambda *args: (_ for _ in ()).throw(AssertionError("Duplicate apply")))
    assert restart(h).run(task.id).state == S.DONE
    assert len(mock.calls) == 4


def test_post_completion_drift_stops_before_testing(migrated_factory, tmp_path, mock_openai):
    factory, _, _ = migrated_factory
    v = outputs()
    mock = mock_openai([v[A.RESEARCHER], v[A.PLANNER], response()])
    h = setup(factory, tmp_path, mock)
    advance(h, S.TESTING)
    (h.root / "calculator.py").write_bytes(b"newer edit\n")
    with pytest.raises(RunnerStoppedError, match="RECONCILIATION"):
        restart(h).run(h.task.id)
    with UnitOfWork(factory) as uow:
        assert not uow.history.list_test_runs(h.task.id)
    assert len(mock.calls) == 3


@pytest.mark.parametrize("failure", [{}, "timeout", 429])
def test_implementer_retry_uses_existing_policy_and_fresh_snapshots(migrated_factory, tmp_path, mock_openai, failure):
    factory, _, _ = migrated_factory
    v = outputs()
    mock = mock_openai([v[A.RESEARCHER], v[A.PLANNER], failure, response(), v[A.REVIEWER]])
    h = setup(factory, tmp_path, mock)
    assert h.runner.run(h.task.id).state == S.DONE
    with UnitOfWork(factory) as uow:
        invs = sorted([i for i in uow.invocations.list_by_task(h.task.id) if i.agent == A.IMPLEMENTER], key=lambda i: i.attempt)
        assert [i.status.value for i in invs] == ["FAILED", "COMPLETED"]
        assert sum(e.event_type == "RETRY_SCHEDULED" for e in uow.history.list_events(h.task.id)) == 1
        assert sum(e.event_type == "MUTATION_APPLIED" for e in uow.history.list_events(h.task.id)) == 1
    assert len(mock.calls) == 5


@pytest.mark.parametrize("failures", [["refusal"], [{}, {}], ["timeout", "timeout", "timeout"]])
def test_refusal_or_exhausted_provider_schema_failures_never_mutate(migrated_factory, tmp_path, mock_openai, failures):
    factory, _, _ = migrated_factory
    v = outputs()
    mock = mock_openai([v[A.RESEARCHER], v[A.PLANNER]] + failures)
    h = setup(factory, tmp_path, mock)
    with pytest.raises(RunnerStoppedError):
        h.runner.run(h.task.id)
    assert (h.root / "calculator.py").read_bytes() == INITIAL.encode()
    with UnitOfWork(factory) as uow:
        assert not any(a.producer_agent == A.IMPLEMENTER for a in uow.artifacts.list_by_task(h.task.id))
        assert "synthetic-sensitive-refusal" not in str(uow.history.list_errors(h.task.id))
    assert len(mock.calls) == 2 + len(failures)


def test_real_repair_respects_existing_defect_budget(migrated_factory, tmp_path, mock_openai):
    factory, _, _ = migrated_factory
    v = outputs()
    mock = mock_openai([v[A.RESEARCHER], v[A.PLANNER], response(UNGUARDED), v[A.TEST_ANALYZER], v[A.INVESTIGATOR]])
    h = setup(factory, tmp_path, mock, config=ReliabilityConfig(max_defect_cycles=0))
    assert h.runner.run(h.task.id).state == S.BLOCKED
    assert (h.root / "calculator.py").read_bytes() == UNGUARDED.encode()
    with UnitOfWork(factory) as uow:
        assert sum(i.agent == A.IMPLEMENTER for i in uow.invocations.list_by_task(h.task.id)) == 1
        assert uow.tasks.get(h.task.id).defect_cycle == 0
    assert len(mock.calls) == 5


@pytest.mark.parametrize("rollback_fails", [False, True])
def test_partial_apply_failure_rolls_back_without_success_evidence(migrated_factory, tmp_path, mock_openai, monkeypatch, rollback_fails):
    factory, _, _ = migrated_factory
    v = outputs()
    plan = v[A.PLANNER].model_copy(update={"files_to_create": ("first.py", "last.py")})
    extra = [dict(path=p, operation="CREATE", expected_sha256=None, content="new\n", reason="planned")
             for p in ("first.py", "last.py")]
    mock = mock_openai([v[A.RESEARCHER], plan, response(extra=extra)])
    h = setup(factory, tmp_path, mock)
    original = h.mutation._apply_file
    def fail(item, staged):
        if item.mutation.path == "last.py":
            raise OSError("Injected partial filesystem failure")
        original(item, staged)
    monkeypatch.setattr(h.mutation, "_apply_file", fail)
    if rollback_fails:
        monkeypatch.setattr(h.mutation, "_rollback_file", lambda *a: (_ for _ in ()).throw(OSError("Failed restore")))
    with pytest.raises(RunnerStoppedError):
        h.runner.run(h.task.id)
    if not rollback_fails:
        assert (h.root / "calculator.py").read_bytes() == INITIAL.encode()
        assert not (h.root / "first.py").exists()
    with UnitOfWork(factory) as uow:
        assert not any(a.artifact_type == AT.IMPLEMENTATION for a in uow.artifacts.list_by_task(h.task.id))
        assert not uow.history.list_test_runs(h.task.id)
        assert uow.tasks.get(h.task.id).state == S.IMPLEMENTING
        inv, = [i for i in uow.invocations.list_by_task(h.task.id) if i.agent == A.IMPLEMENTER]
        assert inv.status.value == ("STARTED" if rollback_fails else "FAILED")
        if not rollback_fails:
            failure, = [e for e in uow.history.list_events(h.task.id) if e.event_type == "MUTATION_FAILED"]
            assert failure.payload["result"]["rollback"] == "SUCCEEDED"
        else:
            pending, = [e for e in uow.history.list_events(h.task.id) if e.event_type == "MUTATION_RECONCILIATION_REQUIRED"]
            assert pending.payload["result"]["rollback"] == "FAILED"
    with pytest.raises(RunnerStoppedError):
        restart(h).run(h.task.id)
    assert len(mock.calls) == 3


def test_create_conflict_after_model_context_preserves_new_file(migrated_factory, tmp_path, mock_openai):
    factory, _, _ = migrated_factory
    v = outputs()
    plan = v[A.PLANNER].model_copy(update={"files_to_create": ("calculator.py",), "files_to_modify": ()})
    mock = mock_openai([v[A.RESEARCHER], plan])
    h = setup(factory, tmp_path, mock, create=True)
    mock.queue.append(response(create=True, edit=lambda: (h.root / "calculator.py").write_bytes(b"existing\n")))
    with pytest.raises(RunnerStoppedError):
        h.runner.run(h.task.id)
    assert (h.root / "calculator.py").read_bytes() == b"existing\n"
    with UnitOfWork(factory) as uow:
        assert any(e.code == "CREATE_TARGET_EXISTS" for e in uow.history.list_errors(h.task.id))
        assert not uow.history.list_test_runs(h.task.id)
    assert len(mock.calls) == 3


def test_real_implementation_circuit_breaker_stops_repair(migrated_factory, tmp_path, mock_openai, monkeypatch):
    factory, _, _ = migrated_factory
    v = outputs()
    mock = mock_openai([v[A.RESEARCHER], v[A.PLANNER], response(UNGUARDED), v[A.TEST_ANALYZER]])
    h = setup(factory, tmp_path, mock, config=ReliabilityConfig(identical_failure_threshold=1))
    # Task 6 intentionally does not infer fingerprints from logs. Supply explicit
    # trusted identity through the existing provider capability, without code edits.
    monkeypatch.setattr(h.provider, "failure_identity", lambda context: FailureIdentity(
        test_name="test_divide_by_zero", error_class="ZeroDivisionError", component="calculator",
        normalized_signature="missing zero-divisor guard"))
    assert h.runner.run(h.task.id).state == S.BLOCKED
    with UnitOfWork(factory) as uow:
        assert sum(i.agent == A.IMPLEMENTER for i in uow.invocations.list_by_task(h.task.id)) == 1
        assert any(e.event_type == "CIRCUIT_BREAKER_TRIPPED" for e in uow.history.list_events(h.task.id))
        assert not any(i.agent == A.INVESTIGATOR for i in uow.invocations.list_by_task(h.task.id))
    assert len(mock.calls) == 4


@pytest.mark.parametrize("status", ["BLOCKED", "FAILED"])
def test_nonwriting_implementer_status_uses_existing_gates(migrated_factory, tmp_path, mock_openai, status):
    factory, _, _ = migrated_factory
    v = outputs()
    output = ImplementationProposal(implementation_status=status, implementation_summary="Cannot safely implement",
        plan_steps=[dict(step_id="step-1", status="BLOCKED")], mutations=[], tests_added_or_modified=[],
        assumptions=[], known_issues=["Requires resolution"], deviations=[])
    mock = mock_openai([v[A.RESEARCHER], v[A.PLANNER], output])
    h = setup(factory, tmp_path, mock)
    with pytest.raises(RunnerStoppedError):
        h.runner.run(h.task.id)
    assert h.runner._task(h.task.id).state == S.IMPLEMENTING
    assert (h.root / "calculator.py").read_bytes() == INITIAL.encode()
    with UnitOfWork(factory) as uow:
        artifact, = [a for a in uow.artifacts.list_by_task(h.task.id) if a.artifact_type == AT.IMPLEMENTATION]
        assert artifact.content["implementation_status"] == status and artifact.content["changed_files"] == []
        assert not uow.history.list_test_runs(h.task.id)


def test_reviewgate_still_rejects_unverified_approval_after_actual_write(migrated_factory, tmp_path, mock_openai):
    factory, _, _ = migrated_factory
    v = outputs()
    review = v[A.REVIEWER].model_dump(mode="json")
    review["requirement_coverage"][0]["status"] = "UNVERIFIED"
    mock = mock_openai([v[A.RESEARCHER], v[A.PLANNER], response(), review])
    h = setup(factory, tmp_path, mock)
    result = h.runner.run(h.task.id)
    assert result.state == S.BLOCKED and result.resume_state == S.REVIEWING
    with UnitOfWork(factory) as uow:
        assert any(g.gate_name == "REVIEW_GATE" and g.result.value == "FAIL" for g in uow.history.list_gate_evaluations(h.task.id))
        assert not any(t.to_state == S.DONE for t in uow.history.list_transitions(h.task.id))
    assert (h.root / "calculator.py").read_bytes() == GUARDED.encode()


def test_reopen_after_completion_reuses_artifact_and_verifies_actual_hash(migrated_factory, tmp_path, mock_openai, monkeypatch):
    factory, engine, _ = migrated_factory
    v = outputs()
    mock = mock_openai([v[A.RESEARCHER], v[A.PLANNER], response(), v[A.REVIEWER]])
    h = setup(factory, tmp_path, mock)
    task = advance(h, S.IMPLEMENTING)
    # Complete application but leave routing for a runner using a reopened DB.
    h.runner.executor.execute(A.IMPLEMENTER, h.runner.build_context(task, A.IMPLEMENTER))
    monkeypatch.setattr(h.mutation, "apply", lambda *a: (_ for _ in ()).throw(AssertionError("Duplicate apply")))
    fresh = create_engine(str(engine.url))
    try:
        assert restart(h, create_session_factory(fresh)).run(task.id).state == S.DONE
    finally:
        fresh.dispose()
    assert len(mock.calls) == 4
