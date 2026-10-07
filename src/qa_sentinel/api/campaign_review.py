"""Explicit trusted-operator commands; read-only derived preparation assessment."""
from uuid import UUID
from fastapi import APIRouter
from qa_sentinel.application import ApprovalCommand, ReviewState, CampaignTraceability, Readiness
from .dependencies import Application, CollectionLimit
from .errors import ERROR_RESPONSES

router = APIRouter(prefix="/projects/{project_id}/campaigns/{campaign_id}", tags=["Campaign Review"], responses=ERROR_RESPONSES)


@router.post("/requirements/{requirement_id}/review", response_model=ReviewState)
def approve_requirement(project_id: UUID, campaign_id: UUID, requirement_id: UUID, body: ApprovalCommand, application: Application):
    return application.review_campaign_requirement(project_id, campaign_id, requirement_id, **body.model_dump())


@router.get("/requirements/{requirement_id}/review", response_model=ReviewState)
def requirement_review(project_id: UUID, campaign_id: UUID, requirement_id: UUID, application: Application):
    return application.get_campaign_requirement_review(project_id, campaign_id, requirement_id)


@router.post("/test-specifications/{test_spec_id}/review", response_model=ReviewState)
def approve_test(project_id: UUID, campaign_id: UUID, test_spec_id: UUID, body: ApprovalCommand, application: Application):
    return application.review_campaign_test_specification(project_id, campaign_id, test_spec_id, **body.model_dump())


@router.get("/test-specifications/{test_spec_id}/review", response_model=ReviewState)
def test_review(project_id: UUID, campaign_id: UUID, test_spec_id: UUID, application: Application):
    return application.get_campaign_test_specification_review(project_id, campaign_id, test_spec_id)


@router.get("/traceability", response_model=CampaignTraceability)
def traceability(project_id: UUID, campaign_id: UUID, application: Application, limit: CollectionLimit = 50):
    return application.get_campaign_traceability(project_id, campaign_id, limit=limit)


@router.get("/readiness", response_model=Readiness)
def readiness(project_id: UUID, campaign_id: UUID, application: Application):
    return application.get_campaign_readiness(project_id, campaign_id)
