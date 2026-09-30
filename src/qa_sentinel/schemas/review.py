from pydantic import BaseModel, ConfigDict
from qa_sentinel.domain.enums import ReviewDecision, ReviewIssueSeverity, CoverageStatus
from qa_sentinel.domain.types import NonBlank


class RequirementCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    acceptance_criterion_id: NonBlank
    status: CoverageStatus
    summary: NonBlank
    evidence_refs: tuple[NonBlank, ...]

class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    severity: ReviewIssueSeverity
    description: NonBlank
    evidence_refs: tuple[NonBlank, ...]

class ReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: ReviewDecision
    requirement_coverage: tuple[RequirementCoverage, ...]
    issues: tuple[ReviewIssue, ...]
    test_gaps: tuple[NonBlank, ...]
    implementation_risks: tuple[NonBlank, ...]
    unverified_assumptions: tuple[NonBlank, ...]
