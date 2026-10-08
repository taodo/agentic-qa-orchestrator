"""Separate bounded content ingestion and explicit requirement extraction routes."""
from uuid import UUID
from fastapi import APIRouter
from qa_sentinel.application import (CampaignSourceView, CampaignSourceDetail, CampaignRequirementView,
    ExtractionView, CampaignModelUsage, CollectionPage, ClarificationView, RequirementHistoryEntry)
from .models import IngestSourceRequest, ExtractRequirementsRequest, ClarificationRequest
from .dependencies import Application, CollectionLimit
from .errors import ERROR_RESPONSES

router = APIRouter(prefix="/projects/{project_id}/campaigns/{campaign_id}", tags=["Campaign Content"], responses=ERROR_RESPONSES)


@router.post("/sources", response_model=CampaignSourceView, status_code=201)
def ingest_source(project_id: UUID, campaign_id: UUID, body: IngestSourceRequest, application: Application):
    return application.ingest_campaign_source(project_id, campaign_id, **body.model_dump())


@router.get("/sources", response_model=CollectionPage[CampaignSourceView])
def list_sources(project_id: UUID, campaign_id: UUID, application: Application, limit: CollectionLimit = 50):
    return application.list_campaign_sources(project_id, campaign_id, limit=limit)


@router.get("/sources/{source_id}", response_model=CampaignSourceDetail)
def get_source(project_id: UUID, campaign_id: UUID, source_id: UUID, application: Application):
    return application.get_campaign_source(project_id, campaign_id, source_id)


@router.post("/sources/{source_id}/extract-requirements", response_model=ExtractionView)
def extract_requirements(project_id: UUID, campaign_id: UUID, source_id: UUID, application: Application,
                         body: ExtractRequirementsRequest | None = None):
    return application.extract_campaign_requirements(project_id, campaign_id, source_id)


@router.get("/requirements", response_model=CollectionPage[CampaignRequirementView])
def list_requirements(project_id: UUID, campaign_id: UUID, application: Application, limit: CollectionLimit = 50):
    return application.list_campaign_requirements(project_id, campaign_id, limit=limit)


@router.get("/requirements/{requirement_id}", response_model=CampaignRequirementView)
def get_requirement(project_id: UUID, campaign_id: UUID, requirement_id: UUID, application: Application):
    return application.get_campaign_requirement(project_id, campaign_id, requirement_id)


@router.get("/model-usage", response_model=CampaignModelUsage)
def model_usage(project_id: UUID, campaign_id: UUID, application: Application, limit: CollectionLimit = 200):
    return application.get_campaign_model_usage(project_id, campaign_id, limit=limit)


@router.get("/sources/{source_id}/extractions", response_model=CollectionPage[ExtractionView])
def extraction_history(project_id:UUID,campaign_id:UUID,source_id:UUID,application:Application,limit:CollectionLimit=50):
    return application.list_campaign_extraction_attempts(project_id,campaign_id,source_id,limit=limit)


@router.post("/extractions/{attempt_id}/retry", response_model=ExtractionView)
def retry_extraction(project_id:UUID,campaign_id:UUID,attempt_id:UUID,application:Application,body:ExtractRequirementsRequest | None=None):
    return application.retry_campaign_extraction(project_id,campaign_id,attempt_id)


@router.post("/requirements/{requirement_id}/clarifications", response_model=ClarificationView,status_code=201)
def clarify_requirement(project_id:UUID,campaign_id:UUID,requirement_id:UUID,body:ClarificationRequest,application:Application):
    return application.add_requirement_clarification(project_id,campaign_id,requirement_id,**body.model_dump())


@router.get("/requirements/{requirement_id}/history", response_model=CollectionPage[RequirementHistoryEntry])
def requirement_history(project_id:UUID,campaign_id:UUID,requirement_id:UUID,application:Application):
    return application.get_requirement_history(project_id,campaign_id,requirement_id)
