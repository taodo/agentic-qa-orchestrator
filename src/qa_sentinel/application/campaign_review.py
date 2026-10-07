"""Detached review/read models shared by in-process and HTTP clients."""
from uuid import UUID
from qa_sentinel.domain.campaign_review import (ApprovalCommand, ApprovalEvidence, ReviewState,
    RequirementTrace, TraceLink, Readiness, Frozen)
from .models import CollectionPage


class CampaignTraceability(Frozen):
    project_id: UUID
    campaign_id: UUID
    requirements: CollectionPage[RequirementTrace]
    links: CollectionPage[TraceLink]
