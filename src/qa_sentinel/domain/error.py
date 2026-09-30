from datetime import datetime, timezone
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field
from .enums import ErrorType, ErrorSeverity, ErrorOwner
from .references import ErrorSource
from .types import NonBlank

class ErrorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    error_type: ErrorType
    code: NonBlank
    severity: ErrorSeverity
    owner: ErrorOwner
    retryable: bool
    blocking: bool
    source: ErrorSource
    message: NonBlank
    evidence_refs: tuple[NonBlank, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
