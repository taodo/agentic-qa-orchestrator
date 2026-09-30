from datetime import datetime
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field
from .enums import TestExecutionStatus, TestOutcome
from .types import NonBlank, Count

class TestRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    implementation_artifact_id: UUID
    execution_status: TestExecutionStatus
    outcome: TestOutcome
    environment: NonBlank
    started_at: datetime
    finished_at: datetime
    passed_count: Count
    failed_count: Count
    skipped_count: Count
    report_artifact_id: UUID | None = None
