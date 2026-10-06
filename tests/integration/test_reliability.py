from qa_sentinel.domain.project import Project
from uuid import uuid4
from datetime import datetime, timezone
import pytest
from qa_sentinel.domain.artifact import Artifact
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.test_run import TestRun as RunRecord
from qa_sentinel.domain.enums import TaskState as S, DecisionType
from qa_sentinel.domain.references import CorrelationRef
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.repositories import HistoryRepository
from qa_sentinel.orchestration.reliability import ReliabilityService
from qa_sentinel.orchestration.reliability_policy import (
    FailureIdentity, FailureDisposition as D, RetryDomain as R, RecoveryAction as A,
    InvestigatorContext, BlockerReason,
)


def seed(factory, state=S.IMPLEMENTING):
    task = Task(project_id=uuid4(), title="Reliability", requirement="Bounded recovery", state=state)
    artifact = Artifact(task_id=task.id, artifact_type="IMPLEMENTATION", schema_version="0.1", content={})
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    run = RunRecord(task_id=task.id, implementation_artifact_id=artifact.id, execution_status="COMPLETED",
        outcome="FAIL", environment="test", started_at=now, finished_at=now,
        passed_count=0, failed_count=1, skipped_count=0)
    with UnitOfWork(factory) as uow:
        uow.projects.add(Project(id=task.project_id,key="test-"+task.project_id.hex,name="Test owner")); uow.tasks.add(task)
        uow.artifacts.add(artifact)
        uow.history.append_test_run(run)
        uow.commit()
    return task, CorrelationRef(test_run_id=run.id, artifact_id=artifact.id)


def identity(signature="expected != actual"):
    return FailureIdentity(test_name="test_x", error_class="AssertionError",
                           component="product", normalized_signature=signature)


def test_transient_retry_and_durable_independent_budgets(migrated_factory):
    factory, _, _ = migrated_factory
    task, correlation = seed(factory)
    service = ReliabilityService(factory)
    for domain in (R.IMPLEMENTATION, R.IMPLEMENTATION, R.SCHEMA_VALIDATION):
        result = service.retry(task_id=task.id, domain=domain, disposition=D.TRANSIENT,
                               evidence_refs=("report:1",), correlation=correlation)
        assert result.action == A.RETRY
    # A fresh service uses persisted counts, not a caller-resettable attempt counter.
    result = ReliabilityService(factory).retry(task_id=task.id, domain=R.IMPLEMENTATION, disposition=D.TRANSIENT)
    assert not result.allowed and result.current_attempt == 2
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(task.id) == task
        assert uow.history.list_transitions(task.id) == []
        decisions = uow.history.list_decisions(task.id)
        events = uow.history.list_events(task.id)
        assert len(decisions) == len(events) == 4
        assert sum(d.decision_type == DecisionType.RETRY for d in decisions) == 3
        assert sum(e.event_type == "RETRY_EXHAUSTED" for e in events) == 1
        assert {e.correlation.decision_id for e in events} == {d.id for d in decisions}
        scheduled = [e for e in events if e.event_type == "RETRY_SCHEDULED"]
        assert all(e.actor.type.value == "ORCHESTRATOR" and e.actor.id == "qa-sentinel" for e in events)
        assert all(e.correlation.test_run_id == correlation.test_run_id for e in scheduled)
        assert all(d.task_id == task.id and d.reason_code and d.reason_details for d in decisions)
        assert any("report:1" in d.evidence_refs for d in decisions)


def test_circuit_breaker_stops_retry_and_preserves_first_seen(migrated_factory):
    factory, _, _ = migrated_factory
    task, correlation = seed(factory)
    # Separate domains ensure circuit, rather than the retry budget, stops the third retry.
    first_seen = None
    for index, domain in enumerate((R.RESEARCH, R.PLANNING, R.IMPLEMENTATION), 1):
        result = ReliabilityService(factory).retry(task_id=task.id, domain=domain,
            disposition=D.CORRECTABLE, changed_input=True, identity=identity(), correlation=correlation)
        assert result.allowed == (index < 3)
        with UnitOfWork(factory) as uow:
            fingerprint, = uow.failure_fingerprints.list_by_task(task.id)
            assert fingerprint.occurrence_count == index
            if index == 1:
                first_seen = fingerprint.first_seen_at
            assert fingerprint.first_seen_at == first_seen
            assert fingerprint.last_seen_at >= first_seen
    assert result.reason_code == "CIRCUIT_BREAKER_TRIPPED" and result.action == A.BLOCK
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(task.id) == task
        assert len(uow.failure_fingerprints.list_by_task(task.id)) == 1
        event, = [e for e in uow.history.list_events(task.id) if e.event_type == "CIRCUIT_BREAKER_TRIPPED"]
        assert event.payload["occurrence_count"] == 3
        assert uow.history.get_decision(event.correlation.decision_id).decision_type == DecisionType.BLOCK


def test_fingerprint_match_scoped_to_task_and_signature(migrated_factory):
    factory, _, _ = migrated_factory
    task, correlation = seed(factory)
    other, other_correlation = seed(factory)
    service = ReliabilityService(factory)
    first, _ = service.record_failure(task_id=task.id, identity=identity(), correlation=correlation)
    # Supply a past first_seen_at to prove last_seen changes without a timing/sleep dependency.
    with UnitOfWork(factory) as uow:
        uow.failure_fingerprints.update_occurrence(first.id, 1, datetime(2026, 1, 1, tzinfo=timezone.utc))
        uow.commit()
    second, _ = service.record_failure(task_id=task.id, identity=identity(), correlation=correlation)
    assert second.id == first.id and second.first_seen_at == first.first_seen_at
    assert second.last_seen_at > datetime(2026, 1, 1, tzinfo=timezone.utc)
    changed, _ = service.record_failure(task_id=task.id, identity=identity("changed"), correlation=correlation)
    separate, _ = service.record_failure(task_id=other.id, identity=identity(), correlation=other_correlation)
    assert changed.id != first.id and separate.id != first.id
    assert changed.occurrence_count == separate.occurrence_count == 1


def test_investigator_escalation_is_durable_and_state_preserving(migrated_factory):
    factory, _, _ = migrated_factory
    task, correlation = seed(factory, S.INVESTIGATING)
    context = InvestigatorContext(confidence=0.55, attempt=1, evidence_refs=("investigation:1",))
    result = ReliabilityService(factory).investigator_escalation(task_id=task.id, context=context, correlation=correlation)
    assert result.escalate and result.source_model == "Luna Max" and result.target_model == "Sol High"
    denied = ReliabilityService(factory).investigator_escalation(task_id=task.id, context=context)
    assert not denied.escalate and denied.escalation_count == 1
    assert "ESCALATION_BUDGET_EXHAUSTED" in denied.reason_codes
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(task.id) == task
        assert not uow.history.list_transitions(task.id)
        assert len(uow.history.list_decisions(task.id)) == 2
        event, = uow.history.list_events(task.id)
        assert event.event_type == "MODEL_ESCALATED" and event.task_id == task.id
        decision = uow.history.get_decision(event.correlation.decision_id)
        assert decision.decision_type == DecisionType.ESCALATE_MODEL
        assert "investigation:1" in decision.evidence_refs


def test_other_roles_cannot_escalate(migrated_factory):
    factory, _, _ = migrated_factory
    task, correlation = seed(factory)
    with pytest.raises(ValueError, match="INVESTIGATING"):
        ReliabilityService(factory).investigator_escalation(task_id=task.id,
            context=InvestigatorContext(confidence=0.1, attempt=1))
    for _ in range(3):
        _, circuit = ReliabilityService(factory).record_failure(task_id=task.id, identity=identity(),
            correlation=correlation, escalation_available=True)
    assert circuit.tripped and circuit.recommended_action == A.BLOCK


def test_circuit_can_recommend_investigator_escalation(migrated_factory):
    factory, _, _ = migrated_factory
    task, correlation = seed(factory, S.INVESTIGATING)
    service = ReliabilityService(factory)
    for _ in range(3):
        _, circuit = service.record_failure(task_id=task.id, identity=identity(),
            correlation=correlation, escalation_available=True)
    assert circuit.recommended_action == A.ESCALATE
    service.investigator_escalation(task_id=task.id, context=InvestigatorContext(confidence=0.1, attempt=1))
    _, circuit = service.record_failure(task_id=task.id, identity=identity(),
        correlation=correlation, escalation_available=True)
    assert circuit.recommended_action == A.BLOCK


def test_block_recommendation_uses_workflow_engine_for_actual_transition(migrated_factory):
    from qa_sentinel.orchestration.workflow_engine import WorkflowEngine
    factory, _, _ = migrated_factory
    task, _ = seed(factory, S.RESEARCHING)
    result = ReliabilityService(factory).block(task_id=task.id, reason=BlockerReason.MISSING_CREDENTIAL,
        resume_state=S.RESEARCHING, evidence_refs=("credential-request:1",))
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(task.id).state == S.RESEARCHING
        decision, = uow.history.list_decisions(task.id)
        event, = uow.history.list_events(task.id)
        assert decision.decision_type == DecisionType.BLOCK
        assert event.event_type == "TASK_BLOCKED" and event.payload["recommendation_only"]
    engine = WorkflowEngine(factory)
    engine.transition(task_id=task.id, to_state=result.recommended_state, resume_state=result.resume_state,
                      reason_code=result.reason_code, reason_details=result.reason)
    engine.transition(task_id=task.id, to_state=S.RESEARCHING, reason_code="RESOLVED", reason_details="Credential supplied")
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(task.id).resume_state is None


@pytest.mark.parametrize("failure_point", ["event", "commit"])
def test_retry_audit_and_budget_roll_back(migrated_factory, monkeypatch, failure_point):
    factory, _, _ = migrated_factory
    task, _ = seed(factory)
    original_event = HistoryRepository.append_event
    def fail_event(self, event):
        original_event(self, event)
        raise RuntimeError("Injected after event insert")
    def fail_commit(self):
        raise RuntimeError("Injected before commit")
    with monkeypatch.context() as patch:
        if failure_point == "event":
            patch.setattr(HistoryRepository, "append_event", fail_event)
        else:
            patch.setattr(UnitOfWork, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="Injected"):
            ReliabilityService(factory).retry(task_id=task.id, domain=R.IMPLEMENTATION, disposition=D.TRANSIENT)
    with UnitOfWork(factory) as uow:
        assert not uow.history.list_events(task.id) and not uow.history.list_decisions(task.id)
        assert uow.tasks.get(task.id) == task
    result = ReliabilityService(factory).retry(task_id=task.id, domain=R.IMPLEMENTATION, disposition=D.TRANSIENT)
    assert result.allowed and result.current_attempt == 0


@pytest.mark.parametrize("existing", [0, 2])
def test_fingerprint_and_circuit_audit_rollback(migrated_factory, monkeypatch, existing):
    factory, _, _ = migrated_factory
    task, correlation = seed(factory)
    service = ReliabilityService(factory)
    for _ in range(existing):
        service.record_failure(task_id=task.id, identity=identity(), correlation=correlation)
    with UnitOfWork(factory) as uow:
        before = uow.failure_fingerprints.list_by_task(task.id)
    def fail_commit(self):
        raise RuntimeError("Injected commit failure")
    with monkeypatch.context() as patch:
        patch.setattr(UnitOfWork, "commit", fail_commit)
        with pytest.raises(RuntimeError):
            service.retry(task_id=task.id, domain=R.IMPLEMENTATION, disposition=D.TRANSIENT,
                          correlation=correlation, identity=identity())
    with UnitOfWork(factory) as uow:
        assert uow.failure_fingerprints.list_by_task(task.id) == before
        assert not uow.history.list_events(task.id) and not uow.history.list_decisions(task.id)
    fingerprint, circuit = service.record_failure(task_id=task.id, identity=identity(), correlation=correlation)
    assert fingerprint.occurrence_count == existing + 1 and circuit.tripped == (existing == 2)


def test_cross_task_correlation_rejected_without_writes(migrated_factory):
    factory, _, _ = migrated_factory
    task, _ = seed(factory)
    _, other_correlation = seed(factory)
    with pytest.raises(ValueError, match="another task"):
        ReliabilityService(factory).retry(task_id=task.id, domain=R.RESEARCH, disposition=D.TRANSIENT,
                                          correlation=other_correlation, identity=identity())
    with UnitOfWork(factory) as uow:
        assert not uow.history.list_decisions(task.id)
        assert not uow.failure_fingerprints.list_by_task(task.id)


def test_fingerprint_requires_test_run_and_terminal_recovery_rejected(migrated_factory):
    factory, _, _ = migrated_factory
    task, _ = seed(factory)
    with pytest.raises(ValueError, match="test-run"):
        ReliabilityService(factory).retry(task_id=task.id, domain=R.RESEARCH, disposition=D.TRANSIENT,
                                          identity=identity())
    terminal, _ = seed(factory, S.DONE)
    with pytest.raises(ValueError, match="Terminal"):
        ReliabilityService(factory).retry(task_id=terminal.id, domain=R.RESEARCH, disposition=D.TRANSIENT)


def test_denied_retry_does_not_consume_domain_budget(migrated_factory):
    factory, _, _ = migrated_factory
    task, _ = seed(factory)
    service = ReliabilityService(factory)
    denied = service.retry(task_id=task.id, domain=R.IMPLEMENTATION, disposition=D.CORRECTABLE)
    assert not denied.allowed
    allowed = service.retry(task_id=task.id, domain=R.IMPLEMENTATION, disposition=D.CORRECTABLE, changed_input=True)
    assert allowed.allowed and allowed.current_attempt == 0


def test_blocked_task_requires_explicit_resume(migrated_factory):
    factory, _, _ = migrated_factory
    task, _ = seed(factory, S.BLOCKED)
    with pytest.raises(ValueError, match="Resume through WorkflowEngine"):
        ReliabilityService(factory).retry(task_id=task.id, domain=R.RESEARCH, disposition=D.TRANSIENT)
    with UnitOfWork(factory) as uow:
        assert not uow.history.list_decisions(task.id) and not uow.history.list_events(task.id)


def test_escalation_failure_does_not_consume_budget(migrated_factory, monkeypatch):
    factory, _, _ = migrated_factory
    task, _ = seed(factory, S.INVESTIGATING)
    context = InvestigatorContext(confidence=0.55, attempt=1)
    original = HistoryRepository.append_event
    def fail(self, event):
        original(self, event)
        raise RuntimeError("Injected after escalation event")
    with monkeypatch.context() as patch:
        patch.setattr(HistoryRepository, "append_event", fail)
        with pytest.raises(RuntimeError):
            ReliabilityService(factory).investigator_escalation(task_id=task.id, context=context)
    with UnitOfWork(factory) as uow:
        assert not uow.history.list_events(task.id) and not uow.history.list_decisions(task.id)
    result = ReliabilityService(factory).investigator_escalation(task_id=task.id, context=context)
    assert result.escalate and result.escalation_count == 0
