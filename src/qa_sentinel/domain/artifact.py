from datetime import datetime, timezone
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from .enums import AgentName, ArtifactType
from .types import NonBlank

class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    invocation_id: UUID | None = None
    artifact_type: ArtifactType
    schema_version: NonBlank
    producer_agent: AgentName | None = None
    producer_model: NonBlank | None = None
    content: JsonValue
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    supersedes_artifact_id: UUID | None = None
