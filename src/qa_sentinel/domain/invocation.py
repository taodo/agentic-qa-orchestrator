from datetime import datetime
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field
from .enums import AgentName, AgentInvocationStatus
from .types import NonBlank, Attempt

class AgentInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    agent: AgentName
    model: NonBlank
    reasoning_effort: NonBlank
    attempt: Attempt
    status: AgentInvocationStatus
    started_at: datetime
    finished_at: datetime
    input_context_refs: tuple[NonBlank, ...] = ()
    error_id: UUID | None = None
