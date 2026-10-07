"""Frozen detached contracts for future CLI/API hosts."""
from datetime import datetime
from types import MappingProxyType
from typing import Generic, TypeVar
from uuid import UUID
from pydantic import BaseModel, ConfigDict, JsonValue, field_validator, field_serializer
from qa_sentinel.domain.enums import (
    TaskState, AgentName, AgentInvocationStatus, ArtifactType, TestExecutionStatus,
    TestOutcome, ErrorType, ErrorSeverity, ErrorOwner, DecisionType, GateResult,
)
from qa_sentinel.domain.references import ActorRef, CorrelationRef, ErrorSource
from qa_sentinel.domain.gate import GateCheck
from qa_sentinel.domain.execution_job import ExecutionJobStatus, ExecutionJobError
from qa_sentinel.domain.campaign import CampaignPreparationStatus


class View(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExecutionJobView(View):
    id: UUID
    task_id: UUID
    project_id: UUID
    status: ExecutionJobStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    safe_error_code: ExecutionJobError | None


T = TypeVar("T")


class CollectionPage(View, Generic[T]):
    items: tuple[T, ...]
    total_returned: int
    truncated: bool


class ProjectView(View):
    id: UUID
    key: str
    name: str
    description: str
    created_at: datetime
    updated_at: datetime


class QACampaignView(View):
    id: UUID
    project_id: UUID
    name: str
    objective: str | None
    status: CampaignPreparationStatus
    created_at: datetime
    updated_at: datetime


class TaskSummary(View):
    id: UUID
    project_id: UUID
    title: str
    state: TaskState
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class TaskDetail(TaskSummary):
    requirement: str
    resume_state: TaskState | None
    current_invocation_id: UUID | None
    implementation_attempt: int
    defect_cycle: int
    review_cycle: int
    terminal_reason: str | None


class InvocationView(View):
    id: UUID
    task_id: UUID
    agent: AgentName
    model: str
    reasoning_effort: str
    attempt: int
    status: AgentInvocationStatus
    started_at: datetime
    finished_at: datetime | None
    error_id: UUID | None


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


def thaw(value):
    if isinstance(value, MappingProxyType):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


class PayloadView(View):
    @field_validator("content", "details", mode="after", check_fields=False)
    @classmethod
    def detached_payload(cls, value):
        return freeze(value)

    @field_serializer("content", "details", check_fields=False)
    def serialize_payload(self, value):
        return thaw(value)


class ArtifactView(PayloadView):
    id: UUID
    task_id: UUID
    invocation_id: UUID | None
    artifact_type: ArtifactType
    schema_version: str
    producer_agent: AgentName | None
    producer_model: str | None
    content: JsonValue
    created_at: datetime
    supersedes_artifact_id: UUID | None


class TestRunView(View):
    id: UUID
    task_id: UUID
    implementation_artifact_id: UUID
    execution_status: TestExecutionStatus
    outcome: TestOutcome
    environment: str
    started_at: datetime
    finished_at: datetime
    passed_count: int
    failed_count: int
    skipped_count: int
    report_artifact_id: UUID | None


class ErrorView(View):
    id: UUID
    task_id: UUID
    error_type: ErrorType
    code: str
    severity: ErrorSeverity
    owner: ErrorOwner
    retryable: bool
    blocking: bool
    source: ErrorSource
    message: str
    evidence_refs: tuple[str, ...]
    created_at: datetime


class DecisionView(View):
    id: UUID
    task_id: UUID
    decision_type: DecisionType
    decision_source: str
    reason_code: str
    reason_details: str
    evidence_refs: tuple[str, ...]
    created_at: datetime


class GateEvaluationView(View):
    id: UUID
    task_id: UUID
    gate_name: str
    result: GateResult
    checks: tuple[GateCheck, ...]
    blocking_reasons: tuple[str, ...]
    evaluated_at: datetime


class TimelineEntry(PayloadView):
    index: int
    insertion_order: int
    timestamp: datetime
    timestamp_tied: bool
    event_id: UUID
    task_id: UUID
    category: str
    event_type: str
    actor: ActorRef
    correlation: CorrelationRef
    summary: str
    details: JsonValue
