"""Transport input and error schemas; no persistence or workflow behavior."""
from pydantic import BaseModel, ConfigDict, StrictStr, model_validator, Field
from qa_sentinel.application import CampaignPreparationStatus, SourceType


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CreateProjectRequest(RequestModel):
    key: StrictStr
    name: StrictStr
    description: StrictStr = ""


class UpdateProjectRequest(RequestModel):
    name: StrictStr | None = None
    description: StrictStr | None = None

    @model_validator(mode="after")
    def reject_explicit_null(self):
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Supplied fields cannot be null")
        return self


class CreateTaskRequest(RequestModel):
    title: StrictStr
    requirement: StrictStr


class ErrorDetail(RequestModel):
    code: str
    message: str


class ErrorEnvelope(RequestModel):
    error: ErrorDetail


class HealthView(RequestModel):
    status: str = "ok"


class CreateCampaignRequest(RequestModel):
    name: StrictStr
    objective: StrictStr | None = None


class UpdateCampaignRequest(RequestModel):
    name: StrictStr | None = None
    objective: StrictStr | None = None

    @model_validator(mode="after")
    def non_null_name(self):
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Campaign name cannot be null")
        return self


class TransitionCampaignRequest(RequestModel):
    status: CampaignPreparationStatus


class IngestSourceRequest(RequestModel):
    name: StrictStr
    source_type: SourceType
    content: StrictStr = Field(max_length=65536)


class ExtractRequirementsRequest(RequestModel):
    pass
