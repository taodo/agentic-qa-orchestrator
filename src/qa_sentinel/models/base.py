"""Small provider-neutral contracts; no SDK, persistence, or tool handles."""
from enum import StrEnum
from typing import Protocol, Annotated
from pydantic import BaseModel, ConfigDict, Field
from qa_sentinel.domain.enums import AgentName, ErrorType
from qa_sentinel.domain.types import Count
from qa_sentinel.orchestration.reliability_policy import FailureDisposition, BlockerReason


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:/-]+$")]


class ModelSettings(FrozenModel):
    model: Identifier
    reasoning_effort: str | None = Field(default=None, pattern=r"^(none|minimal|low|medium|high|xhigh|max)$")
    timeout_seconds: float = Field(default=120, gt=0, le=600, allow_inf_nan=False)
    max_output_tokens: int = Field(default=8192, ge=256, le=32768, strict=True)


class ModelRequest(ModelSettings):
    agent_name: AgentName
    system_instructions: str = Field(min_length=1, max_length=8192)
    user_input: str = Field(min_length=1, max_length=60000)


class ModelMetadata(FrozenModel):
    provider: Identifier = "openai"
    model: Identifier
    provider_response_id: Identifier | None = None
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    total_tokens: Count | None = None
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    status: str = Field(default="completed", pattern=r"^completed$")


class ModelResponse(FrozenModel):
    parsed_output: BaseModel
    metadata: ModelMetadata


class ModelAdapter(Protocol):
    def generate(self, request: ModelRequest, output_type: type[BaseModel]) -> ModelResponse: ...


class ProviderErrorCategory(StrEnum):
    CONFIGURATION = "CONFIGURATION"
    AUTHENTICATION = "AUTHENTICATION"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    CONNECTION = "CONNECTION"
    SERVER_ERROR = "SERVER_ERROR"
    INVALID_REQUEST = "INVALID_REQUEST"
    CONTENT_REFUSAL = "CONTENT_REFUSAL"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    INCOMPLETE_RESPONSE = "INCOMPLETE_RESPONSE"
    CONTEXT_LIMIT = "CONTEXT_LIMIT"
    UNSUPPORTED_ROLE = "UNSUPPORTED_ROLE"
    UNKNOWN_PROVIDER_ERROR = "UNKNOWN_PROVIDER_ERROR"


class ModelError(Exception):
    """Fixed reason codes only: never stores provider exception/request/payload."""
    def __init__(self, category: ProviderErrorCategory, *, changed_input: bool = False):
        self.category = ProviderErrorCategory(category)
        self.code = "MODEL_" + self.category.value
        super().__init__(self.code)
        self.changed_input = changed_input
        self.error_type = ErrorType.AGENT_ERROR
        self.disposition = FailureDisposition.STRUCTURAL
        self.blocker_reason = None
        if self.category in {ProviderErrorCategory.CONFIGURATION, ProviderErrorCategory.AUTHENTICATION}:
            self.error_type = ErrorType.EXTERNAL_BLOCKER
            self.blocker_reason = BlockerReason.MISSING_CREDENTIAL
        elif self.category in {ProviderErrorCategory.RATE_LIMIT, ProviderErrorCategory.TIMEOUT,
                              ProviderErrorCategory.CONNECTION, ProviderErrorCategory.SERVER_ERROR}:
            self.disposition = FailureDisposition.TRANSIENT
        elif self.category == ProviderErrorCategory.MALFORMED_RESPONSE:
            self.error_type = ErrorType.SCHEMA_ERROR
            self.disposition = FailureDisposition.CORRECTABLE
        elif self.category == ProviderErrorCategory.CONTENT_REFUSAL:
            self.blocker_reason = BlockerReason.SECURITY_DECISION
