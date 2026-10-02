"""Session-scoped persistence APIs; repositories never commit or choose workflow."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import models, mappers
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.project import Project
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


class ProjectRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, record: Project) -> None:
        self.session.add(mappers.project_to_orm(record))
        self.session.flush()

    def get(self, record_id: UUID) -> Project | None:
        row = self.session.get(models.ProjectRow, str(record_id))
        return None if row is None else mappers.project_from_orm(row)

    def get_by_key(self, key: str) -> Project | None:
        row = self.session.scalar(select(models.ProjectRow).where(models.ProjectRow.key == key))
        return None if row is None else mappers.project_from_orm(row)

    def list(self) -> list[Project]:
        return [mappers.project_from_orm(row) for row in self.session.scalars(
            select(models.ProjectRow).order_by(models.ProjectRow.key, models.ProjectRow.id))]

    def save(self, record: Project) -> None:
        row = self.session.get(models.ProjectRow, str(record.id))
        if row is None:
            raise KeyError(record.id)
        values = mappers.project_to_orm(record)
        if (row.key, row.created_at) != (values.key, values.created_at):
            raise ValueError("Project identity is immutable")
        row.name, row.description, row.updated_at = values.name, values.description, values.updated_at
        self.session.flush()


class TaskRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, record: Task) -> None:
        self.session.add(mappers.task_to_orm(record))
        self.session.flush()

    def get(self, record_id: UUID) -> Task | None:
        row = self.session.get(models.TaskRow, str(record_id))
        return None if row is None else mappers.task_from_orm(row)

    def save(self, record: Task) -> None:
        row = self.session.get(models.TaskRow, str(record.id))
        if row is None:
            raise KeyError(record.id)
        values = mappers.task_to_orm(record)
        if row.project_id != values.project_id:
            raise ValueError("Task ownership is immutable")
        row.title = values.title
        row.requirement = values.requirement
        row.state = values.state
        row.resume_state = values.resume_state
        row.created_at = values.created_at
        row.updated_at = values.updated_at
        row.completed_at = values.completed_at
        row.current_invocation_id = values.current_invocation_id
        row.implementation_attempt = values.implementation_attempt
        row.defect_cycle = values.defect_cycle
        row.review_cycle = values.review_cycle
        row.terminal_reason = values.terminal_reason
        self.session.flush()


class ArtifactRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, record: Artifact) -> None:
        self.session.add(mappers.artifact_to_orm(record))
        self.session.flush()

    def get(self, record_id: UUID) -> Artifact | None:
        row = self.session.get(models.ArtifactRow, str(record_id))
        return None if row is None else mappers.artifact_from_orm(row)

    def list_by_task(self, task_id: UUID) -> list[Artifact]:
        rows = self.session.scalars(select(models.ArtifactRow).where(
            models.ArtifactRow.task_id == str(task_id)
        ).order_by(models.ArtifactRow.id))
        return [mappers.artifact_from_orm(row) for row in rows]


class InvocationRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, record: AgentInvocation) -> None:
        self.session.add(mappers.invocation_to_orm(record))
        self.session.flush()

    def get(self, record_id: UUID) -> AgentInvocation | None:
        row = self.session.get(models.InvocationRow, str(record_id))
        return None if row is None else mappers.invocation_from_orm(row)

    def list_by_task(self, task_id: UUID) -> list[AgentInvocation]:
        rows = self.session.scalars(select(models.InvocationRow).where(
            models.InvocationRow.task_id == str(task_id)
        ).order_by(models.InvocationRow.id))
        return [mappers.invocation_from_orm(row) for row in rows]

    def save(self, record: AgentInvocation) -> None:
        row = self.session.get(models.InvocationRow, str(record.id))
        if row is None:
            raise KeyError(record.id)
        values = mappers.invocation_to_orm(record)
        row.task_id = values.task_id
        row.agent = values.agent
        row.model = values.model
        row.reasoning_effort = values.reasoning_effort
        row.attempt = values.attempt
        row.status = values.status
        row.started_at = values.started_at
        row.finished_at = values.finished_at
        row.input_context_refs = values.input_context_refs
        row.error_id = values.error_id
        self.session.flush()


class RequirementRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, record: Requirement) -> None:
        self.session.add(mappers.requirement_to_orm(record))
        self.session.flush()

    def get(self, record_id: UUID) -> Requirement | None:
        row = self.session.get(models.RequirementRow, str(record_id))
        return None if row is None else mappers.requirement_from_orm(row)

    def list_by_task(self, task_id: UUID) -> list[Requirement]:
        rows = self.session.scalars(select(models.RequirementRow).where(
            models.RequirementRow.task_id == str(task_id)
        ).order_by(models.RequirementRow.id))
        return [mappers.requirement_from_orm(row) for row in rows]


class AcceptanceCriterionRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, record: AcceptanceCriterionRecord) -> None:
        self.session.add(mappers.acceptance_criterion_to_orm(record))
        self.session.flush()

    def get(self, persistence_id: UUID) -> AcceptanceCriterionRecord | None:
        row = self.session.get(models.AcceptanceCriterionRow, str(persistence_id))
        return None if row is None else mappers.acceptance_criterion_from_orm(row)

    def get_by_logical_id(self, requirement_id: UUID, criterion_id: str) -> AcceptanceCriterionRecord | None:
        row = self.session.scalar(select(models.AcceptanceCriterionRow).where(
            models.AcceptanceCriterionRow.requirement_id == str(requirement_id),
            models.AcceptanceCriterionRow.id == criterion_id,
        ))
        return None if row is None else mappers.acceptance_criterion_from_orm(row)

    def list_by_requirement(self, requirement_id: UUID) -> list[AcceptanceCriterionRecord]:
        rows = self.session.scalars(select(models.AcceptanceCriterionRow).where(
            models.AcceptanceCriterionRow.requirement_id == str(requirement_id)
        ).order_by(models.AcceptanceCriterionRow.id))
        return [mappers.acceptance_criterion_from_orm(row) for row in rows]


class FailureFingerprintRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, record: FailureFingerprint) -> None:
        self.session.add(mappers.failure_fingerprint_to_orm(record))
        self.session.flush()

    def get(self, record_id: UUID) -> FailureFingerprint | None:
        row = self.session.get(models.FailureFingerprintRow, str(record_id))
        return None if row is None else mappers.failure_fingerprint_from_orm(row)

    def list_by_task(self, task_id: UUID) -> list[FailureFingerprint]:
        rows = self.session.scalars(select(models.FailureFingerprintRow).where(
            models.FailureFingerprintRow.task_id == str(task_id)
        ).order_by(models.FailureFingerprintRow.id))
        return [mappers.failure_fingerprint_from_orm(row) for row in rows]

    def update_occurrence(self, record_id: UUID, occurrence_count: int,
                          last_seen_at: datetime) -> None:
        row = self.session.get(models.FailureFingerprintRow, str(record_id))
        if row is None:
            raise KeyError(record_id)
        original = mappers.failure_fingerprint_from_orm(row)
        validated = FailureFingerprint.model_validate({
            **original.model_dump(), "occurrence_count": occurrence_count,
            "last_seen_at": last_seen_at,
        })
        row.occurrence_count = validated.occurrence_count
        row.last_seen_at = validated.last_seen_at
        self.session.flush()


class HistoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def append_transition(self, record: Transition) -> None:
        self.session.add(mappers.transition_to_orm(record))
        self.session.flush()

    def get_transition(self, record_id: UUID) -> Transition | None:
        row = self.session.get(models.TransitionRow, str(record_id))
        return None if row is None else mappers.transition_from_orm(row)

    def list_transitions(self, task_id: UUID) -> list[Transition]:
        rows = self.session.scalars(select(models.TransitionRow).where(
            models.TransitionRow.task_id == str(task_id)
        ).order_by(models.TransitionRow.id))
        return [mappers.transition_from_orm(row) for row in rows]

    def append_gate_evaluation(self, record: GateEvaluation) -> None:
        self.session.add(mappers.gate_evaluation_to_orm(record))
        self.session.flush()

    def get_gate_evaluation(self, record_id: UUID) -> GateEvaluation | None:
        row = self.session.get(models.GateEvaluationRow, str(record_id))
        return None if row is None else mappers.gate_evaluation_from_orm(row)

    def list_gate_evaluations(self, task_id: UUID) -> list[GateEvaluation]:
        rows = self.session.scalars(select(models.GateEvaluationRow).where(
            models.GateEvaluationRow.task_id == str(task_id)
        ).order_by(models.GateEvaluationRow.id))
        return [mappers.gate_evaluation_from_orm(row) for row in rows]

    def append_decision(self, record: DecisionRecord) -> None:
        self.session.add(mappers.decision_to_orm(record))
        self.session.flush()

    def get_decision(self, record_id: UUID) -> DecisionRecord | None:
        row = self.session.get(models.DecisionRow, str(record_id))
        return None if row is None else mappers.decision_from_orm(row)

    def list_decisions(self, task_id: UUID) -> list[DecisionRecord]:
        rows = self.session.scalars(select(models.DecisionRow).where(
            models.DecisionRow.task_id == str(task_id)
        ).order_by(models.DecisionRow.id))
        return [mappers.decision_from_orm(row) for row in rows]

    def append_error(self, record: ErrorRecord) -> None:
        self.session.add(mappers.error_to_orm(record))
        self.session.flush()

    def get_error(self, record_id: UUID) -> ErrorRecord | None:
        row = self.session.get(models.ErrorRow, str(record_id))
        return None if row is None else mappers.error_from_orm(row)

    def list_errors(self, task_id: UUID) -> list[ErrorRecord]:
        rows = self.session.scalars(select(models.ErrorRow).where(
            models.ErrorRow.task_id == str(task_id)
        ).order_by(models.ErrorRow.id))
        return [mappers.error_from_orm(row) for row in rows]

    def append_event(self, record: Event) -> None:
        self.session.add(mappers.event_to_orm(record))
        self.session.flush()

    def get_event(self, record_id: UUID) -> Event | None:
        row = self.session.get(models.EventRow, str(record_id))
        return None if row is None else mappers.event_from_orm(row)

    def list_events(self, task_id: UUID) -> list[Event]:
        rows = self.session.scalars(select(models.EventRow).where(
            models.EventRow.task_id == str(task_id)
        ).order_by(models.EventRow.id))
        return [mappers.event_from_orm(row) for row in rows]

    def append_audit(self, record: AuditRecord) -> None:
        self.session.add(mappers.audit_to_orm(record))
        self.session.flush()

    def get_audit(self, record_id: UUID) -> AuditRecord | None:
        row = self.session.get(models.AuditRow, str(record_id))
        return None if row is None else mappers.audit_from_orm(row)

    def list_audits(self, task_id: UUID) -> list[AuditRecord]:
        rows = self.session.scalars(select(models.AuditRow).where(
            models.AuditRow.task_id == str(task_id)
        ).order_by(models.AuditRow.id))
        return [mappers.audit_from_orm(row) for row in rows]

    def append_test_run(self, record: TestRun) -> None:
        self.session.add(mappers.test_run_to_orm(record))
        self.session.flush()

    def get_test_run(self, record_id: UUID) -> TestRun | None:
        row = self.session.get(models.TestRunRow, str(record_id))
        return None if row is None else mappers.test_run_from_orm(row)

    def list_test_runs(self, task_id: UUID) -> list[TestRun]:
        rows = self.session.scalars(select(models.TestRunRow).where(
            models.TestRunRow.task_id == str(task_id)
        ).order_by(models.TestRunRow.id))
        return [mappers.test_run_from_orm(row) for row in rows]
