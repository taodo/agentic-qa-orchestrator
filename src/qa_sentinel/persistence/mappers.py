"""Explicit domain/storage mappings with detached JSON values."""
from copy import deepcopy
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.project import Project
from qa_sentinel.domain.campaign import QACampaign
from qa_sentinel.domain.invocation import AgentInvocation
from qa_sentinel.domain.artifact import Artifact
from qa_sentinel.domain.transition import Transition
from qa_sentinel.domain.gate import GateEvaluation
from qa_sentinel.domain.decision import DecisionRecord
from qa_sentinel.domain.error import ErrorRecord
from qa_sentinel.domain.event import Event
from qa_sentinel.domain.audit import AuditRecord
from qa_sentinel.domain.test_run import TestRun
from qa_sentinel.persistence.records import FailureFingerprint
from qa_sentinel.persistence.records import Requirement
from qa_sentinel.persistence.records import AcceptanceCriterionRecord
from .models import (
    ProjectRow, QACampaignRow,
    TaskRow,
    InvocationRow,
    ArtifactRow,
    TransitionRow,
    GateEvaluationRow,
    DecisionRow,
    ErrorRow,
    EventRow,
    AuditRow,
    TestRunRow,
    FailureFingerprintRow,
    RequirementRow,
    AcceptanceCriterionRow,
)


def project_to_orm(record: Project) -> ProjectRow:
    record = Project.model_validate(record.model_dump())
    return ProjectRow(id=str(record.id), key=record.key, name=record.name,
        description=record.description, created_at=record.created_at, updated_at=record.updated_at)


def project_from_orm(row: ProjectRow) -> Project:
    return Project(id=row.id, key=row.key, name=row.name, description=row.description,
        created_at=row.created_at, updated_at=row.updated_at)


def campaign_to_orm(record: QACampaign) -> QACampaignRow:
    record = QACampaign.model_validate(record.model_dump())
    return QACampaignRow(id=str(record.id), project_id=str(record.project_id), name=record.name,
        objective=record.objective, status=record.status.value,
        created_at=record.created_at, updated_at=record.updated_at)


def campaign_from_orm(row: QACampaignRow) -> QACampaign:
    return QACampaign(id=row.id, project_id=row.project_id, name=row.name, objective=row.objective,
        status=row.status, created_at=row.created_at, updated_at=row.updated_at)


def task_to_orm(record: Task) -> TaskRow:
    record = Task.model_validate(record.model_dump())
    data = record.model_dump(mode="json")
    return TaskRow(
        id=data["id"],
        project_id=data["project_id"],
        title=data["title"],
        requirement=data["requirement"],
        state=data["state"],
        resume_state=data["resume_state"],
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
        current_invocation_id=data["current_invocation_id"],
        implementation_attempt=data["implementation_attempt"],
        defect_cycle=data["defect_cycle"],
        review_cycle=data["review_cycle"],
        terminal_reason=data["terminal_reason"],
    )


def task_from_orm(row: TaskRow) -> Task:
    return Task.model_validate({
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "requirement": row.requirement,
        "state": row.state,
        "resume_state": row.resume_state,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "completed_at": row.completed_at,
        "current_invocation_id": row.current_invocation_id,
        "implementation_attempt": row.implementation_attempt,
        "defect_cycle": row.defect_cycle,
        "review_cycle": row.review_cycle,
        "terminal_reason": row.terminal_reason,
    })


def invocation_to_orm(record: AgentInvocation) -> InvocationRow:
    record = AgentInvocation.model_validate(record.model_dump())
    data = record.model_dump(mode="json")
    return InvocationRow(
        id=data["id"],
        task_id=data["task_id"],
        agent=data["agent"],
        model=data["model"],
        reasoning_effort=data["reasoning_effort"],
        attempt=data["attempt"],
        status=data["status"],
        started_at=record.started_at,
        finished_at=record.finished_at,
        input_context_refs=deepcopy(data["input_context_refs"]),
        error_id=data["error_id"],
    )


def invocation_from_orm(row: InvocationRow) -> AgentInvocation:
    return AgentInvocation.model_validate({
        "id": row.id,
        "task_id": row.task_id,
        "agent": row.agent,
        "model": row.model,
        "reasoning_effort": row.reasoning_effort,
        "attempt": row.attempt,
        "status": row.status,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "input_context_refs": deepcopy(row.input_context_refs),
        "error_id": row.error_id,
    })


def artifact_to_orm(record: Artifact) -> ArtifactRow:
    record = Artifact.model_validate(record.model_dump())
    data = record.model_dump(mode="json")
    return ArtifactRow(
        id=data["id"],
        task_id=data["task_id"],
        invocation_id=data["invocation_id"],
        artifact_type=data["artifact_type"],
        schema_version=data["schema_version"],
        producer_agent=data["producer_agent"],
        producer_model=data["producer_model"],
        content=deepcopy(data["content"]),
        created_at=record.created_at,
        supersedes_artifact_id=data["supersedes_artifact_id"],
    )


def artifact_from_orm(row: ArtifactRow) -> Artifact:
    return Artifact.model_validate({
        "id": row.id,
        "task_id": row.task_id,
        "invocation_id": row.invocation_id,
        "artifact_type": row.artifact_type,
        "schema_version": row.schema_version,
        "producer_agent": row.producer_agent,
        "producer_model": row.producer_model,
        "content": deepcopy(row.content),
        "created_at": row.created_at,
        "supersedes_artifact_id": row.supersedes_artifact_id,
    })


def transition_to_orm(record: Transition) -> TransitionRow:
    record = Transition.model_validate(record.model_dump())
    data = record.model_dump(mode="json")
    return TransitionRow(
        id=data["id"],
        task_id=data["task_id"],
        from_state=data["from_state"],
        to_state=data["to_state"],
        trigger=data["trigger"],
        gate_evaluation_id=data["gate_evaluation_id"],
        decision_id=data["decision_id"],
        created_at=record.created_at,
    )


def transition_from_orm(row: TransitionRow) -> Transition:
    return Transition.model_validate({
        "id": row.id,
        "task_id": row.task_id,
        "from_state": row.from_state,
        "to_state": row.to_state,
        "trigger": row.trigger,
        "gate_evaluation_id": row.gate_evaluation_id,
        "decision_id": row.decision_id,
        "created_at": row.created_at,
    })


def gate_evaluation_to_orm(record: GateEvaluation) -> GateEvaluationRow:
    record = GateEvaluation.model_validate(record.model_dump())
    data = record.model_dump(mode="json")
    return GateEvaluationRow(
        id=data["id"],
        task_id=data["task_id"],
        gate_name=data["gate_name"],
        result=data["result"],
        checks=deepcopy(data["checks"]),
        blocking_reasons=deepcopy(data["blocking_reasons"]),
        evaluated_at=record.evaluated_at,
    )


def gate_evaluation_from_orm(row: GateEvaluationRow) -> GateEvaluation:
    return GateEvaluation.model_validate({
        "id": row.id,
        "task_id": row.task_id,
        "gate_name": row.gate_name,
        "result": row.result,
        "checks": deepcopy(row.checks),
        "blocking_reasons": deepcopy(row.blocking_reasons),
        "evaluated_at": row.evaluated_at,
    })


def decision_to_orm(record: DecisionRecord) -> DecisionRow:
    record = DecisionRecord.model_validate(record.model_dump())
    data = record.model_dump(mode="json")
    return DecisionRow(
        id=data["id"],
        task_id=data["task_id"],
        decision_type=data["decision_type"],
        decision_source=data["decision_source"],
        reason_code=data["reason_code"],
        reason_details=data["reason_details"],
        evidence_refs=deepcopy(data["evidence_refs"]),
        created_at=record.created_at,
    )


def decision_from_orm(row: DecisionRow) -> DecisionRecord:
    return DecisionRecord.model_validate({
        "id": row.id,
        "task_id": row.task_id,
        "decision_type": row.decision_type,
        "decision_source": row.decision_source,
        "reason_code": row.reason_code,
        "reason_details": row.reason_details,
        "evidence_refs": deepcopy(row.evidence_refs),
        "created_at": row.created_at,
    })


def error_to_orm(record: ErrorRecord) -> ErrorRow:
    record = ErrorRecord.model_validate(record.model_dump())
    data = record.model_dump(mode="json")
    return ErrorRow(
        id=data["id"],
        task_id=data["task_id"],
        error_type=data["error_type"],
        code=data["code"],
        severity=data["severity"],
        owner=data["owner"],
        retryable=data["retryable"],
        blocking=data["blocking"],
        source=deepcopy(data["source"]),
        message=data["message"],
        evidence_refs=deepcopy(data["evidence_refs"]),
        created_at=record.created_at,
    )


def error_from_orm(row: ErrorRow) -> ErrorRecord:
    return ErrorRecord.model_validate({
        "id": row.id,
        "task_id": row.task_id,
        "error_type": row.error_type,
        "code": row.code,
        "severity": row.severity,
        "owner": row.owner,
        "retryable": row.retryable,
        "blocking": row.blocking,
        "source": deepcopy(row.source),
        "message": row.message,
        "evidence_refs": deepcopy(row.evidence_refs),
        "created_at": row.created_at,
    })


def event_to_orm(record: Event) -> EventRow:
    record = Event.model_validate(record.model_dump())
    data = record.model_dump(mode="json")
    return EventRow(
        id=data["id"],
        task_id=data["task_id"],
        event_type=data["event_type"],
        timestamp=record.timestamp,
        actor=deepcopy(data["actor"]),
        correlation=deepcopy(data["correlation"]),
        payload=deepcopy(data["payload"]),
    )


def event_from_orm(row: EventRow) -> Event:
    return Event.model_validate({
        "id": row.id,
        "task_id": row.task_id,
        "event_type": row.event_type,
        "timestamp": row.timestamp,
        "actor": deepcopy(row.actor),
        "correlation": deepcopy(row.correlation),
        "payload": deepcopy(row.payload),
    })


def audit_to_orm(record: AuditRecord) -> AuditRow:
    record = AuditRecord.model_validate(record.model_dump())
    data = record.model_dump(mode="json")
    return AuditRow(
        id=data["id"],
        task_id=data["task_id"],
        actor=deepcopy(data["actor"]),
        action=data["action"],
        resource=data["resource"],
        decision=data["decision"],
        policy=data["policy"],
        metadata_json=deepcopy(data["metadata"]),
        created_at=record.created_at,
    )


def audit_from_orm(row: AuditRow) -> AuditRecord:
    return AuditRecord.model_validate({
        "id": row.id,
        "task_id": row.task_id,
        "actor": deepcopy(row.actor),
        "action": row.action,
        "resource": row.resource,
        "decision": row.decision,
        "policy": row.policy,
        "metadata": deepcopy(row.metadata_json),
        "created_at": row.created_at,
    })


def test_run_to_orm(record: TestRun) -> TestRunRow:
    record = TestRun.model_validate(record.model_dump())
    data = record.model_dump(mode="json")
    return TestRunRow(
        id=data["id"],
        task_id=data["task_id"],
        implementation_artifact_id=data["implementation_artifact_id"],
        execution_status=data["execution_status"],
        outcome=data["outcome"],
        environment=data["environment"],
        started_at=record.started_at,
        finished_at=record.finished_at,
        passed_count=data["passed_count"],
        failed_count=data["failed_count"],
        skipped_count=data["skipped_count"],
        report_artifact_id=data["report_artifact_id"],
    )


def test_run_from_orm(row: TestRunRow) -> TestRun:
    return TestRun.model_validate({
        "id": row.id,
        "task_id": row.task_id,
        "implementation_artifact_id": row.implementation_artifact_id,
        "execution_status": row.execution_status,
        "outcome": row.outcome,
        "environment": row.environment,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "passed_count": row.passed_count,
        "failed_count": row.failed_count,
        "skipped_count": row.skipped_count,
        "report_artifact_id": row.report_artifact_id,
    })


def failure_fingerprint_to_orm(record: FailureFingerprint) -> FailureFingerprintRow:
    record = FailureFingerprint.model_validate(record.model_dump())
    data = record.model_dump(mode="json")
    return FailureFingerprintRow(
        id=data["id"],
        task_id=data["task_id"],
        test_run_id=data["test_run_id"],
        fingerprint=data["fingerprint"],
        test_name=data["test_name"],
        error_class=data["error_class"],
        component=data["component"],
        normalized_signature=data["normalized_signature"],
        occurrence_count=data["occurrence_count"],
        first_seen_at=record.first_seen_at,
        last_seen_at=record.last_seen_at,
    )


def failure_fingerprint_from_orm(row: FailureFingerprintRow) -> FailureFingerprint:
    return FailureFingerprint.model_validate({
        "id": row.id,
        "task_id": row.task_id,
        "test_run_id": row.test_run_id,
        "fingerprint": row.fingerprint,
        "test_name": row.test_name,
        "error_class": row.error_class,
        "component": row.component,
        "normalized_signature": row.normalized_signature,
        "occurrence_count": row.occurrence_count,
        "first_seen_at": row.first_seen_at,
        "last_seen_at": row.last_seen_at,
    })


def requirement_to_orm(record: Requirement) -> RequirementRow:
    record = Requirement.model_validate(record.model_dump())
    data = record.model_dump(mode="json")
    return RequirementRow(
        id=data["id"],
        task_id=data["task_id"],
        text=data["text"],
    )


def requirement_from_orm(row: RequirementRow) -> Requirement:
    return Requirement.model_validate({
        "id": row.id,
        "task_id": row.task_id,
        "text": row.text,
    })


def acceptance_criterion_to_orm(record: AcceptanceCriterionRecord) -> AcceptanceCriterionRow:
    record = AcceptanceCriterionRecord.model_validate(record.model_dump())
    data = record.model_dump(mode="json")
    return AcceptanceCriterionRow(
        persistence_id=data["persistence_id"],
        id=data["id"],
        requirement_id=data["requirement_id"],
        text=data["text"],
        verification_method=data["verification_method"],
    )


def acceptance_criterion_from_orm(row: AcceptanceCriterionRow) -> AcceptanceCriterionRecord:
    return AcceptanceCriterionRecord.model_validate({
        "persistence_id": row.persistence_id,
        "id": row.id,
        "requirement_id": row.requirement_id,
        "text": row.text,
        "verification_method": row.verification_method,
    })
