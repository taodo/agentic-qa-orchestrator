"""Inert project-owned Target configuration; no connection probes or execution."""
from uuid import UUID
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from qa_sentinel.application import CreateTarget, UpdateTarget, TargetUnderTest
from qa_sentinel.application.models import CollectionPage, QACampaignView
from .dependencies import Application, CollectionLimit
from .errors import ERROR_RESPONSES

router = APIRouter(prefix="/projects/{project_id}",tags=["Targets Under Test"],responses=ERROR_RESPONSES)


@router.post("/targets",response_model=TargetUnderTest,status_code=201)
def create_target(project_id:UUID,body:CreateTarget,application:Application):
    return application.create_target(project_id,**body.model_dump())


@router.get("/targets",response_model=CollectionPage[TargetUnderTest])
def list_targets(project_id:UUID,application:Application,limit:CollectionLimit=50):
    return application.list_targets(project_id,limit=limit)


@router.get("/targets/{target_id}",response_model=TargetUnderTest)
def get_target(project_id:UUID,target_id:UUID,application:Application):
    return application.get_target(project_id,target_id)


@router.patch("/targets/{target_id}",response_model=TargetUnderTest)
def update_target(project_id:UUID,target_id:UUID,body:UpdateTarget,application:Application):
    return application.update_target(project_id,target_id,**body.model_dump(exclude_unset=True))


class CampaignTargetCommand(BaseModel):
    model_config=ConfigDict(extra="forbid")
    target_id: UUID | None


@router.get("/campaigns/{campaign_id}/target",response_model=TargetUnderTest | None)
def campaign_target(project_id:UUID,campaign_id:UUID,application:Application):
    return application.get_campaign_target(project_id,campaign_id)


@router.put("/campaigns/{campaign_id}/target",response_model=QACampaignView)
def associate_target(project_id:UUID,campaign_id:UUID,body:CampaignTargetCommand,application:Application):
    return application.associate_campaign_target(project_id,campaign_id,**body.model_dump())
