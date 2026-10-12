"""Bounded read-only product projections. These never execute models or tests."""
from datetime import datetime
from uuid import UUID
from pydantic import Field
from qa_sentinel.domain.campaign_content import Frozen
from qa_sentinel.domain.test_specification import CampaignTestSpecification

class ExecutionCandidate(Frozen):
    test: CampaignTestSpecification
    content_hash: str
    eligible: bool
    reason: str | None


class TestEditEvidence(Frozen):
    id: UUID
    test_id: UUID
    previous_id: UUID
    source_id: UUID
    version: int = Field(ge=2,le=10)
    reviewer_label: str = Field(max_length=64)
    note: str = Field(max_length=1000)
    previous_hash: str
    created_at: datetime
