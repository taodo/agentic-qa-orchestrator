"""One execution request lifecycle. Never a QA workflow state or outcome."""
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ExecutionJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class ExecutionJobError(StrEnum):
    RUNTIME_STOPPED = "RUNTIME_STOPPED"
    EXECUTION_INTERRUPTED = "EXECUTION_INTERRUPTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"


class ExecutionJob(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    project_id: UUID
    status: ExecutionJobStatus = ExecutionJobStatus.QUEUED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    safe_error_code: ExecutionJobError | None = None

    @field_validator("created_at", "started_at", "finished_at")
    @classmethod
    def utc(cls, value):
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Execution timestamps must have a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def lifecycle(self):
        if self.status == ExecutionJobStatus.QUEUED:
            valid = self.started_at is None and self.finished_at is None and self.safe_error_code is None
        elif self.status == ExecutionJobStatus.RUNNING:
            valid = self.started_at is not None and self.finished_at is None and self.safe_error_code is None
        else:
            valid = self.started_at is not None and self.finished_at is not None
            if self.status == ExecutionJobStatus.SUCCEEDED:
                valid = valid and self.safe_error_code is None
            elif self.status == ExecutionJobStatus.STOPPED:
                valid = valid and self.safe_error_code in {ExecutionJobError.RUNTIME_STOPPED, ExecutionJobError.EXECUTION_INTERRUPTED}
            else:
                valid = valid and self.safe_error_code == ExecutionJobError.EXECUTION_FAILED
        if not valid or (self.started_at is not None and self.started_at < self.created_at) or (
                self.finished_at is not None and self.finished_at < self.started_at):
            raise ValueError("Invalid execution request lifecycle")
        return self
