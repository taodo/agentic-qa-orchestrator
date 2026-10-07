"""Small command input contracts; workflow inputs remain core contracts."""
from uuid import UUID
from pydantic import BaseModel, ConfigDict, model_validator
from qa_sentinel.domain.types import NonBlank
from qa_sentinel.domain.campaign import CampaignName, CampaignObjective, CampaignPreparationStatus


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


class UpdateCampaign(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: CampaignName | None = None
    objective: CampaignObjective | None = None

    @model_validator(mode="after")
    def non_null_name(self):
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Campaign name cannot be null")
        return self


class TransitionCampaign(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: CampaignPreparationStatus
