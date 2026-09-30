from datetime import datetime, timezone
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from .types import NonBlank

class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    event_type: NonBlank
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: NonBlank
    correlation: UUID
    payload: dict[str, JsonValue]
