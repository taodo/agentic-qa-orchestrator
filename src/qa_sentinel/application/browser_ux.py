"""Bounded operator preparation over existing approval and browser use cases."""
import json
from typing import Literal
from uuid import UUID
from qa_sentinel.domain.browser_generation import ApprovedBrowserFacts, BrowserPlanOutput
from qa_sentinel.domain.target import TargetSnapshot
from qa_sentinel.domain.test_specification import TestDesign
from qa_sentinel.agents.browser_plan_generation import approved_facts
from qa_sentinel.execution.browser_policy import BrowserExecutionPolicy, relative_destination
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from .models import View
from .errors import ApplicationError, ApplicationErrorCode as Code

class PlanningReadiness(View):
    status: Literal['AVAILABLE','TARGET_NOT_WEB','TEST_NOT_APPROVED','FACTS_MISSING','FACTS_INVALID','POLICY_REJECTED','PROVIDER_UNAVAILABLE']
    test_id: UUID
    target: TargetSnapshot | None

class CandidateSummary(View):
    id: UUID
    test_id: UUID
    test_key: str
    test_title: str
    target: TargetSnapshot
    test_hash: str
    target_hash: str
    origin: Literal['AI']
    prompt_version: str
    status: Literal['STARTED','SUCCEEDED','FAILED']
    error_code: str | None
    configured_model: str
    provider_model: str | None
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    total_tokens: int | None
    plan_hash: str | None
    accepted_run_id: UUID | None

class CandidateView(CandidateSummary):
    output: BrowserPlanOutput | None

def candidate(app,p,c,record):
    receipt=app.get_browser_plan_acceptance(p,c,record.id)
    metadata=record.metadata
    return CandidateView(id=record.id,test_id=record.test.id,test_key=record.test.key,test_title=record.test.title,
        target=record.target,test_hash=record.test_hash,target_hash=record.target_hash,origin=record.origin,
        prompt_version=record.prompt_version,status=record.status,error_code=record.error_code,
        configured_model=record.settings.model,provider_model=None if metadata is None else metadata.model,
        **{key:None if metadata is None else getattr(metadata,key) for key in ('input_tokens','output_tokens','reasoning_tokens','total_tokens')},
        plan_hash=record.plan_hash,output=record.output,accepted_run_id=None if receipt is None else receipt.run_id)

def validate_facts(facts,test):
    facts=ApprovedBrowserFacts.model_validate(facts)
    if (len(facts.required_actions)!=len(test.steps) or not facts.required_actions[0]
            or facts.required_actions[0][0]!='NAVIGATE'):raise ValueError()
    for path in facts.paths:relative_destination('https://example.invalid',path)
    if any(getattr(loc,'exact',True) is not True for loc in facts.locators):raise ValueError()
    return facts

def readiness(app,p,c,t,*,provider_available):
    from .service import identifier,persistence_boundary
    p,c,t=map(identifier,(p,c,t))
    with persistence_boundary(),UnitOfWork(app._factory) as uow:
        campaign=app._campaign(uow,p,c)
        test=app._test_child(uow,p,c,t,'specification')
        target=None if campaign.target_id is None else TargetSnapshot.capture(app._target(uow,p,campaign.target_id))
        if target is None or target.type!='WEB':status='TARGET_NOT_WEB'
        elif test.review_status!='APPROVED' or not uow.test_specifications.is_current(test.id):status='TEST_NOT_APPROVED'
        else:
            try:
                facts=approved_facts(test)
                if facts is None:status='FACTS_MISSING'
                else:validate_facts(facts,test);status='AVAILABLE'
            except ValueError:status='FACTS_INVALID'
            if status=='AVAILABLE':
                try:
                    policy=BrowserExecutionPolicy() if app._browser_executor is None else app._browser_executor.policy_for(target)
                    policy.validate_target(target)
                except ValueError:status='POLICY_REJECTED'
            if status=='AVAILABLE' and not provider_available:status='PROVIDER_UNAVAILABLE'
    return PlanningReadiness(status=status,test_id=t,target=target)

def edit_facts(app,p,c,t,*,facts,previous_hash,reviewer_label,note):
    test=app.get_campaign_test_specification(p,c,t)
    try:
        facts=validate_facts(facts,test)
        # Existing precondition bounds are retained; never split/truncate approved facts.
        preconditions=[]
        for text in test.preconditions:
            try:value=json.loads(text)
            except ValueError:value=None
            if not isinstance(value,dict) or value.get('contract_version')!='browser-facts-v1':preconditions.append(text)
        preconditions.append(facts.model_dump_json())
        design=TestDesign.model_validate({**{key:getattr(test,key) for key in TestDesign.model_fields}, 'preconditions':preconditions})
    except ValueError:raise ApplicationError(Code.INVALID_INPUT) from None
    return app.edit_campaign_test(p,c,t,design=design.model_dump(),previous_hash=previous_hash,reviewer_label=reviewer_label,note=note)
