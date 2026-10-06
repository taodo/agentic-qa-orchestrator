from datetime import datetime, timezone
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field
from .enums import TaskState
from .types import NonBlank, Count

class Task(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID = Field(frozen=True)
    title: NonBlank
    requirement: NonBlank
    state: TaskState = TaskState.CREATED
    resume_state: TaskState | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    current_invocation_id: UUID | None = None
    implementation_attempt: Count = 0
    defect_cycle: Count = 0
    review_cycle: Count = 0
    terminal_reason: NonBlank | None = None
