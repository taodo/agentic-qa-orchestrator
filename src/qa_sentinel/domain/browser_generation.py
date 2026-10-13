"""Immutable planning inputs/candidates; none of these records is execution evidence."""
from datetime import datetime, timezone
from typing import Literal, Annotated
from uuid import UUID, uuid4
from pydantic import Field, AwareDatetime, model_validator
from .campaign_content import Frozen, Hash
from .campaign_review import ApprovalEvidence
from .test_specification import CampaignTestSpecification
from .target import TargetSnapshot
from .browser_execution import BrowserExecutionPlan, Locator, RelativeURL, Text
from .qa_run import validate_approval, canonical_json
from qa_sentinel.models.base import ModelSettings, ModelMetadata
from hashlib import sha256

PROMPT_VERSION='browser-plan-generator-v1'
MAX_RECORD_BYTES=262144

def input_hash(test,approval):
    return sha256(canonical_json({'test':test.model_dump(mode='json'),'approval':approval.model_dump(mode='json')})).hexdigest()

def object_hash(value):
    return sha256(canonical_json(value.model_dump(mode='json'))).hexdigest()

class ApprovedBrowserFacts(Frozen):
    contract_version:Literal['browser-facts-v1']='browser-facts-v1'
    required_actions:tuple[tuple[Literal['NAVIGATE','CLICK','FILL','SELECT','CHECK','PRESS','WAIT_FOR'],...],...]=Field(min_length=1,max_length=20)
    locators:tuple[Locator,...]=Field(max_length=20)
    paths:tuple[RelativeURL,...]=Field(max_length=20)
    input_values:tuple[Text,...]=Field(max_length=20)

    @model_validator(mode='after')
    def operation_bound(self):
        if sum(len(actions) for actions in self.required_actions)>50:raise ValueError('Approved operation bound')
        return self

class BrowserPlanOutput(Frozen):
    disposition:Literal['CANDIDATE','CANNOT_PLAN']
    plan:BrowserExecutionPlan | None
    step_bindings:tuple[Annotated[int,Field(ge=1,le=20,strict=True)],...]=Field(max_length=50)
    unable_reason:Literal['MISSING_LOCATOR','MISSING_NAVIGATION','UNSUPPORTED_EXPECTATION','MISSING_INFORMATION'] | None

    @model_validator(mode='after')
    def shape(self):
        if self.disposition=='CANDIDATE':
            if self.plan is None or self.unable_reason is not None or len(self.step_bindings)!=len(self.plan.steps):
                raise ValueError('Invalid candidate shape')
        elif self.plan is not None or self.step_bindings or self.unable_reason is None:
            raise ValueError('Cannot-plan must not contain a plan')
        return self

class BrowserPlanGeneration(Frozen):
    id:UUID=Field(default_factory=uuid4)
    project_id:UUID
    campaign_id:UUID
    test:CampaignTestSpecification
    approval:ApprovalEvidence
    target:TargetSnapshot
    test_hash:Hash
    target_hash:Hash
    agent:Literal['PLANNER']='PLANNER'
    origin:Literal['AI']='AI'
    prompt_version:Literal['browser-plan-generator-v1']=PROMPT_VERSION
    settings:ModelSettings
    previous_id:UUID | None=None
    attempt_number:int=Field(default=1,ge=1,le=3,strict=True)
    status:Literal['STARTED','SUCCEEDED','FAILED']='STARTED'
    started_at:AwareDatetime=Field(default_factory=lambda:datetime.now(timezone.utc))
    finished_at:AwareDatetime | None=None
    error_code:Annotated[str,Field(pattern=r'^(MODEL_[A-Z_]+|BROWSER_PLAN_(INVALID_OUTPUT|POLICY_REJECTED|INSUFFICIENT_INFORMATION|GROUNDING_REJECTED))$')] | None=None
    metadata:ModelMetadata | None=None
    output:BrowserPlanOutput | None=None
    plan_hash:Hash | None=None

    @model_validator(mode='after')
    def invariants(self):
        validate_approval(self.test,self.approval,'TEST_SPECIFICATION')
        if (self.test.project_id,self.test.campaign_id)!=(self.project_id,self.campaign_id) or self.target.project_id!=self.project_id:
            raise ValueError('Planning owner mismatch')
        if self.test_hash!=input_hash(self.test,self.approval) or self.target_hash!=object_hash(self.target):raise ValueError('Planning input hash mismatch')
        if (self.previous_id is None)!=(self.attempt_number==1):raise ValueError('Invalid retry lineage')
        if self.status=='STARTED':
            if any(v is not None for v in (self.finished_at,self.error_code,self.metadata,self.output,self.plan_hash)):raise ValueError('Started is not complete')
        else:
            if self.finished_at is None or self.finished_at<self.started_at:raise ValueError('Invalid completion time')
            if self.status=='SUCCEEDED':
                if self.error_code or self.output is None or self.output.disposition!='CANDIDATE' or self.plan_hash!=object_hash(self.output.plan):raise ValueError('Invalid successful candidate')
                if self.metadata is None or self.metadata.status!='completed':raise ValueError('Provider did not complete')
            elif self.error_code is None or self.output is not None or self.plan_hash is not None:raise ValueError('Failed generation cannot own a plan')
        if len(canonical_json(self.model_dump(mode='json')))>MAX_RECORD_BYTES:raise ValueError('Planning record bound exceeded')
        return self

class BrowserPlanAcceptance(Frozen):
    generation_id:UUID
    project_id:UUID
    campaign_id:UUID
    run_id:UUID
    run_test_id:UUID
    plan_hash:Hash
    accepted_at:AwareDatetime=Field(default_factory=lambda:datetime.now(timezone.utc))
