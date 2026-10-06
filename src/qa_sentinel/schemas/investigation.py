from pydantic import BaseModel, ConfigDict
from qa_sentinel.domain.enums import InvestigationStatus, InvestigationActionType
from qa_sentinel.domain.types import NonBlank, Confidence


class InvestigationAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: InvestigationActionType
    description: NonBlank


class InvestigationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: InvestigationStatus
    root_cause: NonBlank | None
    evidence: tuple[NonBlank, ...]
    confidence: Confidence
    recommended_action: InvestigationAction
    alternative_hypotheses: tuple[NonBlank, ...]
    additional_evidence_needed: tuple[NonBlank, ...]
