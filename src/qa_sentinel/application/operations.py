"""Frozen operational projections. No operational label authorizes execution."""
from datetime import datetime
from enum import StrEnum
from uuid import UUID
from pydantic import Field
from qa_sentinel.domain.enums import TaskState
from qa_sentinel.domain.execution_job import ExecutionJobStatus, ExecutionJobError
from .models import View


class OperationalAttention(StrEnum):
    NORMAL = "NORMAL"
    ACTIVE = "ACTIVE"
    ATTENTION = "ATTENTION"
    BLOCKED = "BLOCKED"


class OperationalErrorCode(StrEnum):
    ERROR_RECORDED = "ERROR_RECORDED"
    OUTPUT_SCHEMA_INVALID = "OUTPUT_SCHEMA_INVALID"
    MUTATION_RECONCILIATION_REQUIRED = "MUTATION_RECONCILIATION_REQUIRED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTION_INTERRUPTED = "EXECUTION_INTERRUPTED"
    RUNTIME_STOPPED = "RUNTIME_STOPPED"


class OperationalSummaryView(View):
    project_count: int = Field(ge=0)
    task_count: int = Field(ge=0)
    running_jobs: int = Field(ge=0)
    queued_jobs: int = Field(ge=0)
    blocked_tasks: int = Field(ge=0)
    terminal_tasks: int = Field(ge=0)
    reconciliation_attention_tasks: int = Field(ge=0)
    recent_failed_jobs: int = Field(ge=0)
    recent_stopped_jobs: int = Field(ge=0)
    recent_jobs_window: int = 50
    generated_at: datetime


class ProjectOperationalSummaryView(View):
    project_id: UUID
    project_key: str = Field(max_length=64)
    task_count: int = Field(ge=0)
    active_jobs: int = Field(ge=0)
    blocked_tasks: int = Field(ge=0)
    reconciliation_attention_tasks: int = Field(ge=0)
    latest_activity_at: datetime


class TaskOperationalSummaryView(View):
    task_id: UUID
    project_id: UUID
    project_key: str = Field(max_length=64)
    title: str = Field(max_length=240)
    task_state: TaskState
    active_execution_status: ExecutionJobStatus | None
    latest_execution_status: ExecutionJobStatus | None
    latest_execution_error_code: ExecutionJobError | None
    reconciliation_attention: bool
    attention: OperationalAttention
    latest_error_code: OperationalErrorCode | None
    updated_at: datetime


class OperationalActivityKind(StrEnum):
    TASK_STATE_CHANGED = "TASK_STATE_CHANGED"
    EXECUTION_QUEUED = "EXECUTION_QUEUED"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    EXECUTION_SUCCEEDED = "EXECUTION_SUCCEEDED"
    EXECUTION_STOPPED = "EXECUTION_STOPPED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    BLOCKING_ERROR_RECORDED = "BLOCKING_ERROR_RECORDED"
    TEST_PASS = "TEST_PASS"
    TEST_FAIL = "TEST_FAIL"
    TEST_UNKNOWN = "TEST_UNKNOWN"


class OperationalActivityView(View):
    record_id: UUID
    task_id: UUID
    project_id: UUID
    kind: OperationalActivityKind
    timestamp: datetime
    task_state: TaskState | None = None
