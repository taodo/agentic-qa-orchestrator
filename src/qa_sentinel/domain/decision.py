from datetime import datetime, timezone
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field
from .enums import DecisionType
from .types import NonBlank

class DecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    decision_type: DecisionType
    decision_source: NonBlank
    reason_code: NonBlank
    reason_details: NonBlank
    evidence_refs: tuple[NonBlank, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
