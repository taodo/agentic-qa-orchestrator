"""Transport input and error schemas; no persistence or workflow behavior."""
from pydantic import BaseModel, ConfigDict, StrictStr, model_validator


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
