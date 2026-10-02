"""Small command input contracts; workflow inputs remain core contracts."""
from uuid import UUID
from pydantic import BaseModel, ConfigDict, model_validator
from qa_sentinel.domain.types import NonBlank


class UpdateProject(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: NonBlank | None = None
    description: str | None = None

    @model_validator(mode="after")
    def present_values(self):
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Supplied updates must not be null")
        return self


class CreateTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: UUID
    title: NonBlank
    requirement: NonBlank
