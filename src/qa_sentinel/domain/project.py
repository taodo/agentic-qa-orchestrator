"""Logical project identity; workspace paths and secrets belong outside this model."""
from datetime import datetime, timezone
from uuid import UUID, uuid4
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field
from .types import NonBlank

ProjectKey = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    id: UUID = Field(default_factory=uuid4, frozen=True)
    key: ProjectKey = Field(frozen=True)
    name: NonBlank
    description: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), frozen=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
