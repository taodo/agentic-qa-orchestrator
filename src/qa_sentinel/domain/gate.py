from datetime import datetime, timezone
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field
from .enums import GateResult
from .types import NonBlank

class GateCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    check: NonBlank
    result: GateResult
    reason: NonBlank | None = None


class GateEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    gate_name: NonBlank
    result: GateResult
    checks: tuple[GateCheck, ...]
    blocking_reasons: tuple[NonBlank, ...] = ()
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
