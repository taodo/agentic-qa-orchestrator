"""Bounded proposal-only contracts. No prose, secrets, tools or workflow handles."""
from datetime import date, datetime, timezone
from enum import StrEnum
from decimal import Decimal
from typing import Annotated, Literal, Protocol
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field, model_validator
from qa_sentinel.domain.enums import AgentName, TaskState
from qa_sentinel.agents.base import STATE_AGENTS

Probability = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
ModelId = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
Count = Annotated[int, Field(strict=True, ge=0, le=10000000)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Risk(StrEnum):
    LOW = "LOW"
    ARCHITECTURE = "ARCHITECTURE"
    SECURITY = "SECURITY"
    STATE_MACHINE = "STATE_MACHINE"


class Reason(StrEnum):
    CLASSIFICATION = "CLASSIFICATION"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    POLICY_LOCK = "POLICY_LOCK"
    DISALLOWED_ROUTE = "DISALLOWED_ROUTE"
    DISALLOWED_ESCALATION = "DISALLOWED_ESCALATION"
    STALE = "STALE"
    CORRELATION_MISMATCH = "CORRELATION_MISMATCH"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"
    AUTHENTICATION = "AUTHENTICATION"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"


class DecisionRequest(Record):
    version: Literal["decision-v1"] = "decision-v1"
    correlation_id: UUID = Field(default_factory=uuid4)
    baseline_route: AgentName
    allowed_routes: tuple[AgentName, ...] = Field(min_length=1, max_length=6)
    workflow_state: TaskState | None = None
    risk: Risk = Risk.LOW
    complexity: Literal["BOUNDED", "COMPLEX"] = "BOUNDED"
    evidence_refs: tuple[UUID, ...] = Field(default=(), max_length=16)
    evidence_complete: bool = Field(default=True, strict=True)
    evidence_conflict: bool = Field(default=False, strict=True)
    untrusted_input: bool = Field(default=False, strict=True)
    permission_required: bool = Field(default=False, strict=True)
    policy_denied: bool = Field(default=False, strict=True)
    escalation_allowed: bool = Field(default=False, strict=True)
    baseline_escalation: bool = Field(default=False, strict=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime

    @model_validator(mode="after")
    def coherent(self):
        if len(set(self.allowed_routes)) != len(self.allowed_routes) or self.baseline_route not in self.allowed_routes:
            raise ValueError("Baseline must be in a unique route allowlist")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("Evidence references must be unique")
        if self.created_at.utcoffset() is None or self.expires_at.utcoffset() is None:
            raise ValueError("Timezone required")
        if not 0 < (self.expires_at-self.created_at).total_seconds() <= 30:
            raise ValueError("Decision lifetime must be at most 30 seconds")
        if self.workflow_state is not None and STATE_AGENTS.get(self.workflow_state) != self.baseline_route:
            raise ValueError("Baseline must preserve canonical stage role")
        if self.baseline_escalation and not self.escalation_allowed:
            raise ValueError("Baseline escalation must already be permitted")
        return self


class DecisionProposal(Record):
    version: Literal["decision-v1"] = "decision-v1"
    correlation_id: UUID
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    route: AgentName
    confidence: Probability
    escalate: bool = Field(strict=True)
    reason_codes: tuple[Literal["CLASSIFICATION", "UNCERTAIN"], ...] = Field(min_length=1, max_length=2)
    provider: Literal["typesafe", "offline"]
    configured_model: ModelId
    reported_model: ModelId
    reported_model_release_date: date | None = None
    provider_version: Literal["openapi-0.2.0", "fixture-v1"]
    latency_ms: float = Field(strict=True, ge=0, le=30000, allow_inf_nan=False)
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    # Provider response has no currency field. Unknown remains unknown.
    provider_cost_usd: None = None
    estimated_cost_usd: Decimal | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    pricing_source: Literal["operator-configured"] | None = None


    @model_validator(mode="after")
    def metadata_consistent(self):
        if (self.estimated_cost_usd is None) != (self.pricing_source is None):
            raise ValueError("An estimate requires its pricing provenance")
        if (self.provider == "typesafe") != (self.provider_version == "openapi-0.2.0"):
            raise ValueError("Provider/schema identity mismatch")
        return self


class DecisionReceipt(Record):
    request: DecisionRequest
    version: Literal["decision-v1"] = "decision-v1"
    correlation_id: UUID
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    route: AgentName
    escalate: bool
    accepted: bool
    reason: Reason
    proposal: DecisionProposal | None = None


class DecisionFailure(Exception):
    def __init__(self, reason: Reason):
        self.reason = Reason(reason)
        super().__init__(self.reason.value)


class DecisionProvider(Protocol):
    def propose(self, request: DecisionRequest) -> DecisionProposal: ...
