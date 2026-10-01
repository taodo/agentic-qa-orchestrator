"""Small typed records for specified entities without existing domain contracts."""
from datetime import datetime
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field
from qa_sentinel.domain.types import NonBlank, Count


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    text: NonBlank


class AcceptanceCriterionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: NonBlank
    requirement_id: UUID
    text: NonBlank
    verification_method: NonBlank


class FailureFingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    test_run_id: UUID
    fingerprint: NonBlank
    test_name: NonBlank
    error_class: NonBlank
    component: NonBlank
    normalized_signature: NonBlank
    occurrence_count: Count
    first_seen_at: datetime
    last_seen_at: datetime
