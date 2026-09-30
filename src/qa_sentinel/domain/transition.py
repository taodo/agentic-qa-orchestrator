from datetime import datetime, timezone
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field
from .enums import TaskState
from .types import NonBlank

class Transition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    from_state: TaskState
    to_state: TaskState
    trigger: NonBlank
    gate_evaluation_id: UUID | None = None
    decision_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
