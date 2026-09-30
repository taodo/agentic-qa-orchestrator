from pydantic import BaseModel, ConfigDict
from qa_sentinel.domain.types import NonBlank, Confidence


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    summary: NonBlank
    evidence: tuple[NonBlank, ...]
    confidence: Confidence

class Unknown(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    description: NonBlank
    blocking: bool

class ResearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    summary: NonBlank
    findings: tuple[Finding, ...]
    dependencies: tuple[NonBlank, ...]
    constraints: tuple[NonBlank, ...]
    risks: tuple[NonBlank, ...]
    unknowns: tuple[Unknown, ...]
    recommendations: tuple[NonBlank, ...]
    research_complete: bool
