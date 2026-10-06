from datetime import datetime, timezone
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from .references import ActorRef
from .types import NonBlank

class AuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    actor: ActorRef
    action: NonBlank
    resource: NonBlank
    decision: NonBlank
    policy: NonBlank
    metadata: dict[str, JsonValue]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
