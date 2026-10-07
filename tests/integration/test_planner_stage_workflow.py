"""Real workflow services with mock Responses and pytest on a temporary backend."""
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import socket
import subprocess
import pytest
from qa_sentinel.agents.real import RealAgentRuntime
from qa_sentinel.application import QASentinelApplication, ProjectExecutionResolver, ProjectExecutionBundle
from qa_sentinel.domain.enums import AgentName as A, TaskState as S, ArtifactType as AT
from qa_sentinel.domain.project import Project
from qa_sentinel.execution.command_policy import ExecutionConfig, CommandRequest
from qa_sentinel.execution.command_runner import CommandRunner
from qa_sentinel.execution.pytest_runner import PytestRunner
from qa_sentinel.execution.service import TestExecutionService as ExecutionService, PytestTestResultProvider
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from qa_sentinel.mutation.contracts import MutationConfig
from qa_sentinel.mutation.service import MutationService
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.projects import ProjectRuntimeRegistry, ProjectWorkspaceBinding
from qa_sentinel.repository.config import RepositoryReadConfig
from qa_sentinel.repository.service import RepositoryReadService
from qa_sentinel.schemas.plan import PlannerOutput
from qa_sentinel.schemas.research import ResearchOutput
from qa_sentinel.schemas.review import ReviewOutput
from qa_sentinel.schemas.mutation import ImplementationProposal
from qa_sentinel.schemas.test_result import TestAnalysisOutput as Analysis
from qa_sentinel.schemas.investigation import InvestigationOutput
from test_repository_workflow import tool_turn, final

REQUIREMENT = ("Booking must never confirm when inventory is exhausted. A second request for the last room "
    "must return room_unavailable, and concurrent requests for the final room must not overbook. "
    "Diagnose from repository evidence and preserve the existing contract and tests.")
BROKEN = """from threading import Lock

class Inventory:
    def __init__(self, available):
        self.available = available
        self.confirmed = 0
        self.lock = Lock()

    def book(self):
        with self.lock:
            if self.available < 0:
                return 'room_unavailable'
            self.available -= 1
            self.confirmed += 1
            return 'confirmed'
"""
FIXED = BROKEN.replace('self.available < 0', 'self.available <= 0')
PRESERVATION = 'guardrail_policy = "preserve_existing_behavior"\n'
TESTS = """from concurrent.futures import ThreadPoolExecutor
from inventory import Inventory

def test_available_room():
    inventory = Inventory(1)
    assert inventory.book() == 'confirmed'

def test_exhausted_room():
    inventory = Inventory(1)
    assert inventory.book() == 'confirmed'
    assert inventory.book() == 'room_unavailable'
    assert inventory.confirmed == 1

def test_concurrent_final_room():
    inventory = Inventory(1)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: inventory.book(), range(16)))
    assert results.count('confirmed') == 1
    assert inventory.confirmed == 1
"""


def repair_plan():
    return PlannerOutput(decision="READY_FOR_IMPLEMENTATION", summary="Repair exhausted inventory guard",
        assumptions=[], implementation_steps=[
            dict(id="repair", kind="CODE_CHANGE", description="Reject non-positive availability",
                 files=["backend/inventory.py"], depends_on=[]),
            dict(id="preserve", kind="STATIC_REVIEW", description="Compare source to preserve the lock and other behavior",
                 files=["backend/inventory.py", "backend/preservation.py"], depends_on=["repair"])],
        files_to_create=[], files_to_modify=["backend/inventory.py"],
        acceptance_criteria=[dict(id=f"AC-{i}", description=description, verification="Existing deterministic pytest evidence")
            for i, description in enumerate(("Available room confirms", "Exhausted room rejects", "Concurrent last room does not overbook"), 1)],
        test_strategy=[dict(description="Run existing available, exhausted and concurrent-final-room tests in TESTING",
            acceptance_criteria_refs=["AC-1", "AC-2", "AC-3"])], risks=[], rollback_considerations=[], open_questions=[])


def research_response(call):
    evidence = json.loads(call["input"][0]["content"])["repository_results"]
    assert evidence[-1]["result"]["data"]["content"] == BROKEN
    output = ResearchOutput(summary="Inventory accepts zero availability",
        findings=[dict(summary="The guard admits zero inventory while preserving the existing lock",
            evidence=[item["evidence_ref"] for item in evidence], confidence=1)],
        dependencies=[], constraints=["Preserve tests and lock"], risks=[], unknowns=[],
        recommendations=["Reject exhausted inventory"], research_complete=True)
    return final(output)


def plan_response(value):
    def respond(call):
        evidence = json.loads(call["input"][0]["content"])["repository_results"]
        assert evidence[-1]["result"]["data"]["content"] == TESTS
        return final(value, A.PLANNER)
    return respond


def implementation_response(content=FIXED, *, weaken_tests=False, change_review_only=False):
    def respond(call):
        data = json.loads(call["input"][0]["content"])
        sources = {s["path"]: s for s in data["source_files"]}
        assert set(sources) == {"backend/inventory.py", "backend/preservation.py"}
        assert sources["backend/preservation.py"]["content"] == PRESERVATION
        assert data["authorized_modify_paths"] == ["backend/inventory.py"]
        assert data["authorized_create_paths"] == []
        source = sources["backend/inventory.py"]
        assert source["path"] == "backend/inventory.py" and source["content"] == BROKEN
        assert source["sha256"] == sha256(BROKEN.encode()).hexdigest()
        assert [s["kind"] for s in data["accepted_plan"]["implementation_steps"]] == ["CODE_CHANGE", "STATIC_REVIEW"]
        mutations = [dict(path=source["path"], operation="MODIFY", expected_sha256=source["sha256"],
            content=content, reason="Repair the authorized guard and preserve lock source")]
        if weaken_tests:
            mutations.append(dict(path="backend/tests/test_inventory.py", operation="MODIFY",
                expected_sha256=sha256(TESTS.encode()).hexdigest(), content="def test_fake(): pass\n", reason="Unauthorized weakening attempt"))
        if change_review_only:
            review = sources["backend/preservation.py"]
            mutations.append(dict(path=review["path"], operation="MODIFY", expected_sha256=review["sha256"],
                content="guardrail_policy = \"weakened\"\n", reason="Attempted review-only mutation"))
        return ImplementationProposal(implementation_status="COMPLETED", implementation_summary="Proposed guard repair",
            plan_steps=[dict(step_id=s["id"], status="COMPLETED") for s in data["accepted_plan"]["implementation_steps"]],
            mutations=mutations, tests_added_or_modified=[], assumptions=[], known_issues=[], deviations=[])
    return respond


def review_response(call):
    data = json.loads(call["input"][0]["content"])
    assert data["test_evidence"]["outcome"] == "PASS" and data["test_evidence"]["passed_count"] == 3
    assert data["implementation"]["tests_added_or_modified"] == []
    return ReviewOutput(decision="APPROVE", requirement_coverage=[
        dict(acceptance_criterion_id=f"AC-{i}", status="COVERED", summary="Existing deterministic test evidence",
            evidence_refs=[data["test_evidence"]["test_run_ref"]]) for i in (1, 2, 3)],
        issues=[], test_gaps=[], implementation_risks=[], unverified_assumptions=[])


@dataclass
class Harness:
    app: object
    task: object
    root: Path
    mutation: object
    mock: object
    factory: object


def setup(factory, tmp_path, mock, *, target_python=None):
    root = tmp_path / "external inventory repository"
    tests = root / "backend" / "tests"
    tests.mkdir(parents=True)
    (root / "frontend").mkdir()
    (root / "backend/inventory.py").write_text(BROKEN, encoding="utf-8", newline="\n")
    (tests / "test_inventory.py").write_text(TESTS, encoding="utf-8", newline="\n")
    (root / "backend/preservation.py").write_text(PRESERVATION, encoding="utf-8", newline="\n")
    project = Project(key="temporary-inventory", name="Prepared offline inventory fixture")
    with UnitOfWork(factory) as uow:
        uow.projects.add(project)
        uow.commit()
    binding = ProjectWorkspaceBinding(project_id=project.id, workspace_root=root)
    mutation = MutationService(MutationConfig(root))
    execution = ExecutionConfig(root, pytest_target_root=root / "backend",
        **({"python_executable": target_python} if target_python is not None else {}),
        python_path=(Path(pytest.__file__).resolve().parents[1],))
    service = ExecutionService(factory, PytestRunner(CommandRunner(execution)), workspace_binding=binding)
    provider = PytestTestResultProvider(service, CommandRequest(cwd=str(root / "backend"), args=("-m", "pytest", "tests")))
    runtime = RealAgentRuntime(OpenAIModelAdapter(client=mock.client), repository_tools=True)
    bundle = ProjectExecutionBundle(binding=binding, runtime=runtime, test_provider=provider,
        mutation_service=mutation, repository_service=RepositoryReadService(RepositoryReadConfig(root)))
    app = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([binding]), [bundle]))
    task = app.create_task(project_id=project.id, title="Repair exhausted inventory", requirement=REQUIREMENT)
    return Harness(app, task, root, mutation, mock, factory)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs): pytest.fail("No live network is allowed in Task 26 regressions")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def initial_outputs(value):
    return [tool_turn(path="backend/inventory.py"), research_response,
        tool_turn(path="backend/tests/test_inventory.py", role=A.PLANNER), plan_response(value)]


@pytest.mark.parametrize("repaired", [True, False])
def test_controlled_repair_advances_to_testing_only_existing_runner_executes(migrated_factory, tmp_path, mock_openai, monkeypatch, repaired):
    factory, _, _ = migrated_factory
    value = repair_plan()
    responses = initial_outputs(value) + [implementation_response(FIXED if repaired else BROKEN + "\n# Incomplete synthetic repair\n")]
    if repaired:
        responses.append(review_response)
    else:
        responses += [Analysis(overall_result="FAIL", failure_groups=[dict(tests=["test_exhausted_room", "test_concurrent_final_room"],
            classification="LIKELY_PRODUCT_DEFECT", summary="Existing exhaustion tests fail", evidence=["synthetic:test-result"],
            confidence=1, requires_investigation=True)]),
            InvestigationOutput(status="ROOT_CAUSE_IDENTIFIED", root_cause="Guard remains faulty", evidence=["synthetic:test-result"],
                confidence=1, recommended_action=dict(type="HUMAN_ACTION", description="Resolve incomplete repair"),
                alternative_hypotheses=[], additional_evidence_needed=[])]
    mock = mock_openai(responses)
    h = setup(factory, tmp_path, mock)
    subprocess_calls, mutations = [], []
    original_popen, original_apply = subprocess.Popen, h.mutation.apply
    def apply(plan, sources, proposal):
        with UnitOfWork(factory) as uow: assert uow.tasks.get(h.task.id).state == S.IMPLEMENTING
        assert len(proposal.mutations) == 1 and not subprocess_calls
        assert {s.path for s in sources} == {"backend/inventory.py", "backend/preservation.py"}
        mutations.append(proposal)
        return original_apply(plan, sources, proposal)
    def popen(argv, **kwargs):
        with UnitOfWork(factory) as uow:
            assert uow.tasks.get(h.task.id).state == S.TESTING
            assert any(g.gate_name == "IMPLEMENTATION_GATE" and g.result.value == "PASS" for g in uow.history.list_gate_evaluations(h.task.id))
            assert any(e.event_type == "MUTATION_APPLIED" for e in uow.history.list_events(h.task.id))
            assert any(e.event_type == "TEST_EXECUTION_STARTED" for e in uow.history.list_events(h.task.id))
        assert argv[1:5] == ["-P", "-s", "-m", "pytest"] and kwargs["shell"] is False
        assert kwargs["cwd"] == str(h.root / "backend") and argv[argv.index("--rootdir") + 1] == str(h.root)
        subprocess_calls.append(argv)
        return original_popen(argv, **kwargs)
    monkeypatch.setattr(h.mutation, "apply", apply)
    monkeypatch.setattr(subprocess, "Popen", popen)
    result = h.app.run_task(h.task.id)
    assert result.state == (S.DONE if repaired else S.BLOCKED)
    assert len(mutations) == len(subprocess_calls) == 1
    assert (h.root / "backend/tests/test_inventory.py").read_text() == TESTS
    assert (h.root / "backend/preservation.py").read_text() == PRESERVATION
    assert (h.root / "backend/inventory.py").read_text() == (FIXED if repaired else BROKEN + "\n# Incomplete synthetic repair\n")
    with UnitOfWork(factory) as uow:
        artifacts = uow.artifacts.list_by_task(h.task.id)
        canonical, = [a for a in artifacts if a.artifact_type == AT.IMPLEMENTATION]
        assert canonical.content["commands_executed"] == [] and len(canonical.content["plan_steps"]) == 2
        assert {s["status"] for s in canonical.content["plan_steps"]} == {"COMPLETED"}
        run, = uow.history.list_test_runs(h.task.id)
        assert run.outcome.value == ("PASS" if repaired else "FAIL") and run.environment == "local-pytest"
        assert (run.passed_count, run.failed_count) == ((3, 0) if repaired else (1, 2))
        report = uow.artifacts.get(run.report_artifact_id)
        assert report.content["counts"]["reliable"] is True
        if not repaired:
            assert not any(t.to_state == S.DONE for t in uow.history.list_transitions(h.task.id))
        assert len([a for a in artifacts if a.artifact_type == AT.REPOSITORY_EVIDENCE]) == 2
        roles = {inv.agent for inv in uow.invocations.list_by_task(h.task.id)}
        assert (A.TEST_ANALYZER in roles and A.INVESTIGATOR in roles) == (not repaired)
    for call in mock.calls: assert call["tools"] == [] and call["tool_choice"] == "none" and call["store"] is False
    assert len(mock.calls) == (6 if repaired else 7) and not mock.queue
    assert not list(h.root.glob("qa-pytest-*"))


def test_test_execution_step_stops_at_plan_gate_before_implementer_or_mutation(migrated_factory, tmp_path, mock_openai, monkeypatch):
    factory, _, _ = migrated_factory
    data = repair_plan().model_dump(mode="json")
    data["implementation_steps"].append(dict(id="run-tests", kind="TEST_EXECUTION",
        description="Run existing exhaustion and concurrency tests", files=[], depends_on=["repair", "preserve"]))
    mock = mock_openai(initial_outputs(PlannerOutput.model_validate(data)))
    h = setup(factory, tmp_path, mock)
    def forbidden(*args, **kwargs): pytest.fail("Rejected plan reached mutation or pytest")
    monkeypatch.setattr(h.mutation, "apply", forbidden)
    monkeypatch.setattr(h.mutation, "build_snapshots", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = h.app.run_task(h.task.id)
    assert result.state == S.BLOCKED and result.resume_state == S.PLANNING
    assert (h.root / "backend/inventory.py").read_text() == BROKEN
    with UnitOfWork(factory) as uow:
        assert not uow.history.list_test_runs(h.task.id)
        assert {inv.agent for inv in uow.invocations.list_by_task(h.task.id)} == {A.RESEARCHER, A.PLANNER}
        assert any(d.reason_code == "PLAN_STAGE_CAPABILITY_MISMATCH" for d in uow.history.list_decisions(h.task.id))
        gate, = [g for g in uow.history.list_gate_evaluations(h.task.id) if g.gate_name == "PLAN_GATE"]
        assert gate.result.value == "FAIL" and any(c.check == "IMPLEMENTING_STEP_KINDS" and c.result.value == "FAIL" for c in gate.checks)
        plan, = [a for a in uow.artifacts.list_by_task(h.task.id) if a.artifact_type == AT.PLAN]
        assert len(plan.content["implementation_steps"]) == 3  # Immutable evidence is preserved.
        assert not any(t.to_state == S.IMPLEMENTING for t in uow.history.list_transitions(h.task.id))
    assert len(mock.calls) == 4 and not mock.queue


def test_test_strategy_does_not_authorize_test_weakening(migrated_factory, tmp_path, mock_openai, monkeypatch):
    factory, _, _ = migrated_factory
    mock = mock_openai(initial_outputs(repair_plan()) + [implementation_response(weaken_tests=True)])
    h = setup(factory, tmp_path, mock)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("Rejected mutation reached pytest"))
    assert h.app.run_task(h.task.id).state == S.FAILED
    assert (h.root / "backend/inventory.py").read_text() == BROKEN
    assert (h.root / "backend/tests/test_inventory.py").read_text() == TESTS
    with UnitOfWork(factory) as uow:
        assert not uow.history.list_test_runs(h.task.id)
        assert any(error.code == "PATH_NOT_AUTHORIZED" for error in uow.history.list_errors(h.task.id))
        assert not any(a.artifact_type == AT.IMPLEMENTATION for a in uow.artifacts.list_by_task(h.task.id))
    assert len(mock.calls) == 5


def test_review_only_mutation_rejected_before_any_apply_or_testing(migrated_factory, tmp_path, mock_openai, monkeypatch):
    factory, _, _ = migrated_factory
    mock = mock_openai(initial_outputs(repair_plan()) + [implementation_response(change_review_only=True)])
    h = setup(factory, tmp_path, mock)
    def forbidden(*args, **kwargs): pytest.fail("Unauthorized review-only mutation reached application or pytest")
    monkeypatch.setattr(h.mutation, "apply", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    assert h.app.run_task(h.task.id).state == S.FAILED
    assert (h.root / "backend/inventory.py").read_text() == BROKEN
    assert (h.root / "backend/preservation.py").read_text() == PRESERVATION
    assert (h.root / "backend/tests/test_inventory.py").read_text() == TESTS
    with UnitOfWork(factory) as uow:
        assert not uow.history.list_test_runs(h.task.id)
        assert any(error.code == "PATH_NOT_AUTHORIZED" for error in uow.history.list_errors(h.task.id))
        events = uow.history.list_events(h.task.id)
        captured, = [e for e in events if e.event_type == "IMPLEMENTATION_SOURCE_CAPTURED"]
        assert {s["path"] for s in captured.payload["sources"]} == {"backend/inventory.py", "backend/preservation.py"}
        assert not any(e.event_type in {"MUTATION_RESERVED", "MUTATION_APPLIED", "TEST_EXECUTION_STARTED"} for e in events)
        assert not any(a.artifact_type == AT.IMPLEMENTATION for a in uow.artifacts.list_by_task(h.task.id))
    assert len(mock.calls) == 5 and not mock.queue


def test_separate_target_interpreter_uses_single_existing_workflow_subprocess(migrated_factory, tmp_path, mock_openai, monkeypatch, native_target_python):
    import io
    from types import SimpleNamespace
    from qa_sentinel.execution import command_runner
    factory, _, _ = migrated_factory
    mock = mock_openai(initial_outputs(repair_plan()) + [implementation_response(), review_response])
    h = setup(factory, tmp_path, mock, target_python=native_target_python)
    calls = []
    def popen(argv, **kwargs):
        with UnitOfWork(factory) as uow:
            assert uow.tasks.get(h.task.id).state == S.TESTING
            assert any(e.event_type == "MUTATION_APPLIED" for e in uow.history.list_events(h.task.id))
            assert any(e.event_type == "TEST_EXECUTION_STARTED" for e in uow.history.list_events(h.task.id))
        calls.append((argv, kwargs))
        Path(argv[argv.index("--junitxml") + 1]).write_text('<testsuite><testcase/><testcase/><testcase/></testsuite>')
        return SimpleNamespace(returncode=0, stdout=io.BytesIO(), stderr=io.BytesIO(),
            wait=lambda **kw: 0, poll=lambda: 0)
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(command_runner, "ProcessTree", lambda p: SimpleNamespace(close=lambda: None))
    assert h.app.run_task(h.task.id).state == S.DONE
    argv, kwargs = calls[0]
    assert len(calls) == 1 and argv[:5] == [str(native_target_python), "-P", "-s", "-m", "pytest"]
    assert kwargs["cwd"] == str(h.root / "backend") and kwargs["shell"] is False
    assert argv[argv.index("--rootdir") + 1] == str(h.root)
    with UnitOfWork(factory) as uow:
        run, = uow.history.list_test_runs(h.task.id)
        assert run.outcome.value == "PASS" and run.passed_count == 3
        assert str(native_target_python) not in str(uow.artifacts.get(run.report_artifact_id).content)
    assert (h.root / "backend/inventory.py").read_text() == FIXED
