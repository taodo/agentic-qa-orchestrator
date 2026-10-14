"""Typed browser UX; real operations are mounted only by trusted local host composition."""
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from qa_sentinel.application.models import CollectionPage
from qa_sentinel.application.browser_ux import ApprovedBrowserFacts, CandidateSummary, CandidateView, PlanningReadiness, candidate
from qa_sentinel.application import QARun, TestSpecificationView
from qa_sentinel.application import ApplicationError, ApplicationErrorCode as Code, Hash
from .dependencies import Application
from .errors import ERROR_RESPONSES

router=APIRouter(prefix='/projects/{project_id}/campaigns/{campaign_id}/browser',tags=['Local Browser'],responses=ERROR_RESPONSES)
class Capability(BaseModel):
    planning: Literal['AVAILABLE','UNAVAILABLE']
    execution: Literal['AVAILABLE','UNAVAILABLE']
    automatic: Literal['AVAILABLE','UNAVAILABLE']
    source_free_review: Literal['AVAILABLE','UNAVAILABLE']
    automatic_reason: str | None=None

class Empty(BaseModel):
    model_config=ConfigDict(extra='forbid')
class AcceptRequest(Empty):
    idempotency_key: str=Field(min_length=1,max_length=128,strict=True)
class FactsRequest(Empty):
    facts: ApprovedBrowserFacts
    non_secret: Literal[True]
    previous_hash: Hash
    reviewer_label: str=Field(min_length=1,max_length=64,strict=True)
    note: str=Field(min_length=1,max_length=1000,strict=True)

    @field_validator('non_secret',mode='before')
    @classmethod
    def explicit_declaration(cls,value):
        if value is not True:raise ValueError('Explicit non-secret declaration required')
        return value

def enabled(request,application,p):
    project=application.get_project(p)
    return project.key in getattr(request.app.state,'browser_project_keys',())
def capabilities(request,application,p):
    import os
    allowed=enabled(request,application,p)
    runtime=allowed and application._browser_executor is not None
    provider=runtime and application._browser_plan_generator is not None and bool(os.environ.get('OPENAI_API_KEY','').strip())
    campaign=application.get_campaign(p,request.path_params['campaign_id'])
    web=allowed and campaign.target_id is not None
    automatic=web and provider and application._browser_observer is not None and application._browser_grounding_reasoner is not None
    return Capability(planning='AVAILABLE' if provider else 'UNAVAILABLE',execution='AVAILABLE' if runtime else 'UNAVAILABLE',
        automatic='AVAILABLE' if automatic else 'UNAVAILABLE',source_free_review='AVAILABLE' if web else 'UNAVAILABLE',
        automatic_reason=None if automatic else 'Configure a WEB Target, install the supported Chromium runtime and supply the model key in the local server environment.')
def require_local(request,application,p):
    if not enabled(request,application,p):raise ApplicationError(Code.GENERATION_NOT_CONFIGURED)

@router.get('/capability',response_model=Capability)
def capability(project_id:UUID,campaign_id:UUID,request:Request,application:Application):
    application.get_campaign(project_id,campaign_id)
    return capabilities(request,application,project_id)

@router.get('/tests/{test_id}/readiness',response_model=PlanningReadiness)
def ready(project_id:UUID,campaign_id:UUID,test_id:UUID,request:Request,application:Application):
    return application.browser_planning_readiness(project_id,campaign_id,test_id,provider_available=capabilities(request,application,project_id).planning=='AVAILABLE')

@router.post('/tests/{test_id}/facts',response_model=TestSpecificationView,status_code=201)
def facts(project_id:UUID,campaign_id:UUID,test_id:UUID,body:FactsRequest,application:Application):
    return application.edit_browser_facts(project_id,campaign_id,test_id,**body.model_dump())

# This router is included only for the trusted local host, never bare/public API.
local_router=APIRouter(prefix=router.prefix,tags=['Local Browser'],responses=ERROR_RESPONSES)
@local_router.post('/tests/{test_id}/generate',response_model=CandidateView)
def generate(project_id:UUID,campaign_id:UUID,test_id:UUID,body:Empty,request:Request,application:Application):
    require_local(request,application,project_id)
    return candidate(application,project_id,campaign_id,application.generate_ready_browser_plan(project_id,campaign_id,test_id,
        provider_available=capabilities(request,application,project_id).planning=='AVAILABLE'))
@local_router.get('/generations',response_model=CollectionPage[CandidateSummary])
def history(project_id:UUID,campaign_id:UUID,request:Request,application:Application):
    require_local(request,application,project_id)
    page=application.list_browser_plan_generations(project_id,campaign_id,limit=20)
    # Bounded explicit history; output is reviewed only in the detail response.
    return {'items':[candidate(application,project_id,campaign_id,r).model_dump(exclude={'output'}) for r in page.items],
        'truncated':page.truncated,'total_returned':page.total_returned}
@local_router.get('/generations/{generation_id}',response_model=CandidateView)
def get(project_id:UUID,campaign_id:UUID,generation_id:UUID,request:Request,application:Application):
    require_local(request,application,project_id)
    return candidate(application,project_id,campaign_id,application.get_browser_plan_generation(project_id,campaign_id,generation_id))
@local_router.post('/generations/{generation_id}/accept',response_model=QARun,status_code=201)
def accept(project_id:UUID,campaign_id:UUID,generation_id:UUID,body:AcceptRequest,request:Request,application:Application):
    require_local(request,application,project_id)
    return application.accept_browser_plan_generation(project_id,campaign_id,generation_id,**body.model_dump())
@local_router.post('/runs/{run_id}/start',response_model=QARun)
def start(project_id:UUID,campaign_id:UUID,run_id:UUID,body:Empty,request:Request,application:Application):
    require_local(request,application,project_id)
    return application.start_browser_qa_run(project_id,campaign_id,run_id)


from qa_sentinel.application.browser_batches import BatchView,BatchHistoryItem,CreateBrowserPreparation
from qa_sentinel.application import ReviewState

class BrowserApproval(Empty):
    reviewer_label: str=Field(min_length=1,max_length=64,strict=True)
    note: str | None=Field(default=None,min_length=1,max_length=1000,strict=True)
    previous_hash: Hash | None=None

class BrowserBulkApproval(Empty):
    test_ids: tuple[UUID,...]=Field(min_length=1,max_length=500)
    expected_hashes: dict[str,Hash]=Field(min_length=1,max_length=500)
    reviewer_label: str=Field(min_length=1,max_length=64,strict=True)
    note: str | None=Field(default=None,min_length=1,max_length=1000,strict=True)


def require_web(request,application,p,c):
    require_local(request,application,p)
    campaign=application.get_campaign(p,c)
    if campaign.target_id is None:raise ApplicationError(Code.TARGET_NOT_FOUND)

@local_router.post('/tests/{test_id}/review',response_model=ReviewState)
def source_free_review(project_id:UUID,campaign_id:UUID,test_id:UUID,body:BrowserApproval,request:Request,application:Application):
    require_web(request,application,project_id,campaign_id)
    return application.review_source_free_campaign_test(project_id,campaign_id,test_id,**body.model_dump())

@local_router.post('/tests/approve-selection')
def source_free_bulk_review(project_id:UUID,campaign_id:UUID,body:BrowserBulkApproval,request:Request,application:Application):
    require_web(request,application,project_id,campaign_id)
    return application.approve_browser_tests(project_id,campaign_id,**body.model_dump())

@local_router.post('/batches',response_model=BatchView,status_code=201)
def submit_batch(project_id:UUID,campaign_id:UUID,body:CreateBrowserPreparation,request:Request,application:Application):
    require_web(request,application,project_id,campaign_id)
    if capabilities(request,application,project_id).automatic!='AVAILABLE':raise ApplicationError(Code.BROWSER_BATCH_NOT_CONFIGURED)
    return application.submit_browser_batch(project_id,campaign_id,**body.model_dump())

@local_router.get('/batches',response_model=CollectionPage[BatchHistoryItem])
def batch_history(project_id:UUID,campaign_id:UUID,request:Request,application:Application,limit:int=20):
    require_local(request,application,project_id)
    return application.list_browser_batches(project_id,campaign_id,limit=limit)

@local_router.get('/batches/{preparation_id}',response_model=BatchView)
def get_batch(project_id:UUID,campaign_id:UUID,preparation_id:UUID,request:Request,application:Application,limit:int=50,after_position:int=0):
    require_local(request,application,project_id)
    return application.get_browser_batch(project_id,campaign_id,preparation_id,limit=limit,after_position=after_position)

@local_router.post('/batches/{preparation_id}/acknowledge-interruption',response_model=BatchView)
def acknowledge_batch(project_id:UUID,campaign_id:UUID,preparation_id:UUID,body:Empty,request:Request,application:Application):
    require_local(request,application,project_id)
    return application.acknowledge_browser_batch_interruption(project_id,campaign_id,preparation_id)
