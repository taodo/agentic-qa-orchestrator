"""Project-scoped campaign HTTP transport; each route delegates one use case."""
from uuid import UUID
from fastapi import APIRouter
from qa_sentinel.application import QACampaignView, CollectionPage
from .dependencies import Application, CollectionLimit
from .models import CreateCampaignRequest, UpdateCampaignRequest, TransitionCampaignRequest
from .errors import ERROR_RESPONSES

router = APIRouter(prefix="/projects/{project_id}/campaigns", tags=["QA Campaigns"], responses=ERROR_RESPONSES)


@router.post("", response_model=QACampaignView, status_code=201)
def create_campaign(project_id: UUID, body: CreateCampaignRequest, application: Application):
    return application.create_campaign(project_id, **body.model_dump())


@router.get("", response_model=CollectionPage[QACampaignView])
def list_campaigns(project_id: UUID, application: Application, limit: CollectionLimit = 50):
    return application.list_project_campaigns(project_id, limit=limit)


@router.get("/{campaign_id}", response_model=QACampaignView)
def get_campaign(project_id: UUID, campaign_id: UUID, application: Application):
    return application.get_campaign(project_id, campaign_id)


@router.patch("/{campaign_id}", response_model=QACampaignView)
def update_campaign(project_id: UUID, campaign_id: UUID, body: UpdateCampaignRequest, application: Application):
    return application.update_campaign(project_id, campaign_id, **body.model_dump(exclude_unset=True))


@router.post("/{campaign_id}/transitions", response_model=QACampaignView)
def transition_campaign(project_id: UUID, campaign_id: UUID, body: TransitionCampaignRequest, application: Application):
    return application.transition_campaign(project_id, campaign_id, **body.model_dump())
