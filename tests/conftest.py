from qa_sentinel.domain.project import Project
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
import json
from types import SimpleNamespace
from collections import deque
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.artifact import Artifact
from qa_sentinel.domain.invocation import AgentInvocation
from qa_sentinel.domain.decision import DecisionRecord
from qa_sentinel.domain.error import ErrorRecord
from qa_sentinel.domain.gate import GateEvaluation
from qa_sentinel.domain.transition import Transition
from qa_sentinel.domain.event import Event
from qa_sentinel.domain.audit import AuditRecord
from qa_sentinel.domain.test_run import TestRun as RunRecord
from qa_sentinel.persistence.records import Requirement, AcceptanceCriterionRecord, FailureFingerprint
from qa_sentinel.persistence.database import create_engine, create_session_factory
from qa_sentinel.persistence.models import Base


@pytest.fixture(autouse=True)
def offline_provider_guard(monkeypatch):
    """Normal pytest never has provider credentials or a live HTTP transport."""
    import httpx
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("Live provider HTTP transport is forbidden in automated tests")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)


@pytest.fixture
def mock_openai():
    """Real SDK with deterministic mock HTTP responses; captures requests only in test memory."""
    import httpx
    from openai import OpenAI
    clients = []
    def make(outputs):
        queue = deque(outputs)
        calls = []
        def respond(request):
            calls.append(json.loads(request.content))
            assert queue, "Unexpected extra provider request (hidden retry)"
            item = queue.popleft()
            if callable(item):
                item = item(calls[-1])
            if item == "timeout":
                raise httpx.ReadTimeout("synthetic-sensitive-provider-error", request=request)
            if item == "connection":
                raise httpx.ConnectError("synthetic-sensitive-provider-error", request=request)
            if isinstance(item, int):
                return httpx.Response(item, json={"error": {"message": "synthetic-sensitive-provider-error",
                    "type": "synthetic", "code": "synthetic"}})
            refusal = item == "refusal"
            content = ({"type": "refusal", "refusal": "synthetic-sensitive-refusal"} if refusal else
                {"type": "output_text", "text": json.dumps(item.model_dump(mode="json")
                    if hasattr(item, "model_dump") else item), "annotations": []})
            return httpx.Response(200, json={"id": "resp_mock_1", "object": "response", "created_at": 1,
                "status": "completed", "model": json.loads(request.content)["model"],
                "output": [{"id": "msg_mock_1", "type": "message", "role": "assistant",
                            "status": "completed", "content": [content]}],
                "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}})
        client = OpenAI(api_key="synthetic-test-credential", max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(respond)))
        clients.append(client)
        return SimpleNamespace(client=client, calls=calls, queue=queue)
    yield make
    for client in clients:
        client.close()


@pytest.fixture
def factory():
    # Fast isolated unit setup. Integration tests use real Alembic upgrades.
    engine = create_engine()
    Base.metadata.create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


@pytest.fixture
def bundle():
    now = datetime(2026, 10, 1, 12, 34, 56, 123456, tzinfo=timezone(timedelta(hours=7)))
    task = Task(project_id=uuid4(), title="Persistence test", requirement="Store evidence", created_at=now,
                updated_at=now, implementation_attempt=2, defect_cycle=3, review_cycle=4)
    error = ErrorRecord(task_id=task.id, error_type="TEST_FAILURE", code="ASSERT", severity="ERROR",
                        owner="TEST_TARGET", retryable=False, blocking=True, message="Mismatch",
                        source=dict(actor=dict(type="TOOL",id="pytest"),tool="pytest"),
                        evidence_refs=["report:1"], created_at=now)
    invocation = AgentInvocation(task_id=task.id, agent="IMPLEMENTER", model="model-id",
                                reasoning_effort="low", attempt=1, status="STARTED", started_at=now,
                                input_context_refs=["plan:1"], error_id=error.id)
    task.current_invocation_id = invocation.id
    artifact = Artifact(task_id=task.id, invocation_id=invocation.id, artifact_type="IMPLEMENTATION",
                        schema_version="0.1", producer_agent="IMPLEMENTER",producer_model="model-id",
                        content={"nested":{"list":[True,False,None,3,2.5,"text"]}}, created_at=now)
    gate = GateEvaluation(task_id=task.id,gate_name="evidence",result="FAIL",
                          checks=[dict(check="tests",result="FAIL",reason="Mismatch")],
                          blocking_reasons=["Mismatch"],evaluated_at=now)
    decision = DecisionRecord(task_id=task.id,decision_type="TRANSITION",decision_source="orchestrator",
                              reason_code="EVIDENCE",reason_details="Recorded only",
                              evidence_refs=[str(artifact.id)],created_at=now)
    transition = Transition(task_id=task.id,from_state="CREATED",to_state="RESEARCHING",trigger="record",
                            gate_evaluation_id=gate.id,decision_id=decision.id,created_at=now)
    run = RunRecord(task_id=task.id,implementation_artifact_id=artifact.id,execution_status="COMPLETED",
                    outcome="PASS",environment="local",started_at=now,finished_at=now,
                    passed_count=2,failed_count=0,skipped_count=1,report_artifact_id=artifact.id)
    event = Event(task_id=task.id,event_type="evidence",timestamp=now,actor=dict(type="SYSTEM",id="qa"),
                  correlation=dict(invocation_id=invocation.id,artifact_id=artifact.id,
                                   test_run_id=run.id,decision_id=decision.id),
                  payload={"nested":{"list":[True,False,None,3,2.5,"text"]}})
    audit = AuditRecord(task_id=task.id,actor=dict(type="HUMAN",id="reviewer"),action="read",
                        resource="artifact",decision="allow",policy="least_privilege",
                        metadata={"nested":{"list":[True,False,None,3,2.5,"text"]}},created_at=now)
    requirement = Requirement(task_id=task.id,text="Store evidence")
    criterion = AcceptanceCriterionRecord(id="AC-1",requirement_id=requirement.id,
                                          text="Round-trip",verification_method="Reload and compare")
    fingerprint = FailureFingerprint(task_id=task.id,test_run_id=run.id,fingerprint="known-signature",
                                     test_name="test_example",error_class="AssertionError",component="product",
                                     normalized_signature="expected != actual",occurrence_count=1,
                                     first_seen_at=now,last_seen_at=now)
    return dict(task=task,invocation=invocation,artifact=artifact,gate_evaluation=gate,decision=decision,
                error=error,transition=transition,test_run=run,event=event,audit=audit,
                requirement=requirement,acceptance_criterion=criterion,failure_fingerprint=fingerprint)


@pytest.fixture
def store_bundle():
    def store(uow, bundle):
        uow.projects.add(Project(id=bundle["task"].project_id,key="test-"+bundle["task"].project_id.hex,name="Test owner")); uow.tasks.add(bundle["task"])
        uow.history.append_error(bundle["error"])
        uow.invocations.add(bundle["invocation"])
        uow.artifacts.add(bundle["artifact"])
        uow.history.append_gate_evaluation(bundle["gate_evaluation"])
        uow.history.append_decision(bundle["decision"])
        uow.history.append_transition(bundle["transition"])
        uow.history.append_test_run(bundle["test_run"])
        uow.history.append_event(bundle["event"])
        uow.history.append_audit(bundle["audit"])
        uow.requirements.add(bundle["requirement"])
        uow.acceptance_criteria.add(bundle["acceptance_criterion"])
        uow.failure_fingerprints.add(bundle["failure_fingerprint"])
    return store


@pytest.fixture
def migrated_factory(tmp_path):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    db=tmp_path/"migrated.sqlite"
    # Start with an empty database file, not a create_all database.
    db.touch()
    config=Config(str(Path(__file__).resolve().parents[1]/"alembic.ini"))
    config.set_main_option("sqlalchemy.url","sqlite+pysqlite:///"+db.as_posix())
    command.upgrade(config,"head")
    engine=create_engine("sqlite+pysqlite:///"+db.as_posix())
    yield create_session_factory(engine),engine,config
    engine.dispose()


@pytest.fixture
def workflow_outputs():
    from qa_sentinel.schemas.research import ResearchOutput
    from qa_sentinel.schemas.plan import PlannerOutput
    from qa_sentinel.schemas.implementation import ImplementationOutput
    from qa_sentinel.schemas.review import ReviewOutput
    from qa_sentinel.schemas.test_result import TestAnalysisOutput
    from qa_sentinel.schemas.investigation import InvestigationOutput
    plan=PlannerOutput(decision="READY_FOR_IMPLEMENTATION",summary="Plan",assumptions=[],
                       implementation_steps=[dict(id="step-1",description="Implement",files=["app.py"],depends_on=[])],
                       files_to_create=[],files_to_modify=["app.py"],
                       acceptance_criteria=[dict(id="AC-1",description="Expected behavior",verification="Assert result")],
                       test_strategy=[dict(description="Assert behavior",acceptance_criteria_refs=["AC-1"])],
                       risks=[],rollback_considerations=[],open_questions=[])
    research=ResearchOutput(summary="Research",findings=[],dependencies=[],constraints=[],risks=[],
                            unknowns=[],recommendations=[],research_complete=True)
    implementation=ImplementationOutput(implementation_status="COMPLETED",
        plan_steps=[dict(step_id="step-1",status="COMPLETED")],
        changed_files=[dict(path="app.py",change_type="MODIFIED",reason="Implement")],
        tests_added_or_modified=[],commands_executed=[],deviations=[],assumptions=[],known_issues=[])
    review=ReviewOutput(decision="APPROVE",requirement_coverage=[dict(acceptance_criterion_id="AC-1",
                        status="COVERED",summary="Verified",evidence_refs=["report:1"])],
                        issues=[],test_gaps=[],implementation_risks=[],unverified_assumptions=[])
    analysis=TestAnalysisOutput(overall_result="FAIL",failure_groups=[dict(tests=["test_example"],
        classification="LIKELY_PRODUCT_DEFECT",summary="Mismatch",evidence=["report:1"],
        confidence=0.8,requires_investigation=True)])
    investigation=InvestigationOutput(status="ROOT_CAUSE_IDENTIFIED",root_cause="Condition mismatch",
        evidence=["report:1"],confidence=0.8,recommended_action=dict(type="CODE_FIX",description="Fix condition"),
        alternative_hypotheses=[],additional_evidence_needed=[])
    return dict(plan=plan,research=research,implementation=implementation,review=review,
                analysis=analysis,investigation=investigation)


@pytest.fixture
def calculator_workspace(tmp_path):
    """Prepared real test code; no agent modifies these files."""
    def prepare(*, failing=False, extra=""):
        root = tmp_path / "calculator-project"
        (root / "tests").mkdir(parents=True, exist_ok=True)
        root.joinpath("calculator.py").write_text(
            "def add(a, b):\n    return a + b\n\n"
            "def divide(a, b):\n    if b == 0:\n        raise ValueError('zero divisor')\n"
            + ("    return a // b\n" if failing else "    return a / b\n"), encoding="utf-8")
        root.joinpath("tests", "test_calculator.py").write_text(
            "import pytest\nfrom calculator import add, divide\n"
            "def test_add():\n    assert add(2, 3) == 5\n"
            "def test_divide():\n    assert divide(5, 2) == 2.5\n"
            "def test_divide_by_zero():\n    with pytest.raises(ValueError):\n        divide(1, 0)\n" + extra,
            encoding="utf-8")
        return root
    return prepare
