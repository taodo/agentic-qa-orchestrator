from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
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
    task = Task(title="Persistence test", requirement="Store evidence", created_at=now,
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
        uow.tasks.add(bundle["task"])
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
