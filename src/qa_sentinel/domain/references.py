"""Structured record references; these contracts perform no lookups."""
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from .enums import ActorType
from .types import NonBlank


class ActorRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: ActorType
    id: NonBlank


class CorrelationRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    invocation_id: UUID | None = None
    artifact_id: UUID | None = None
    test_run_id: UUID | None = None
    decision_id: UUID | None = None


class ErrorSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    actor: ActorRef | None = None
    invocation_id: UUID | None = None
    tool: NonBlank | None = None
