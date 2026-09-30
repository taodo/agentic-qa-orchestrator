from pydantic import BaseModel, ConfigDict
from qa_sentinel.domain.enums import GateResult, FailureClassification
from qa_sentinel.domain.types import NonBlank, Confidence


class FailureGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tests: tuple[NonBlank, ...]
    classification: FailureClassification
    summary: NonBlank
    evidence: tuple[NonBlank, ...]
    confidence: Confidence
    requires_investigation: bool

class TestAnalysisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    overall_result: GateResult
    failure_groups: tuple[FailureGroup, ...]
