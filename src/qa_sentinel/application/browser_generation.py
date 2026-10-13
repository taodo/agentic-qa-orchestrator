"""Internal planning use case: no Run, browser or tool execution."""
from datetime import datetime, timezone
from pydantic import ValidationError
from qa_sentinel.domain.browser_generation import BrowserPlanGeneration, input_hash
from qa_sentinel.domain.target import TargetSnapshot
from qa_sentinel.execution.browser_policy import BrowserExecutionPolicy, BrowserPolicyError, digest
from qa_sentinel.agents.browser_plan_generation import validate_candidate
from qa_sentinel.models.base import ModelError, ModelMetadata, ProviderErrorCategory
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from .errors import ApplicationError, ApplicationErrorCode as Code

RETRYABLE={'MODEL_'+c.value for c in (ProviderErrorCategory.RATE_LIMIT,ProviderErrorCategory.TIMEOUT,ProviderErrorCategory.CONNECTION,
    ProviderErrorCategory.SERVER_ERROR,ProviderErrorCategory.INCOMPLETE_RESPONSE,ProviderErrorCategory.MALFORMED_RESPONSE)}

def generate(app,project_id,campaign_id,test_id,previous_id=None):
    from .service import identifier,persistence_boundary
    project_id,campaign_id=map(identifier,(project_id,campaign_id))
    generator=app._browser_plan_generator
    if generator is None:raise ApplicationError(Code.GENERATION_NOT_CONFIGURED)
    with persistence_boundary(),UnitOfWork(app._factory) as uow:
        uow.session.connection(execution_options={'qa_job_write':True})
        campaign=app._campaign(uow,project_id,campaign_id)
        if previous_id is not None:
            previous=uow.browser_plans.get(project_id,campaign_id,identifier(previous_id))
            if previous is None:raise ApplicationError(Code.BROWSER_PLAN_NOT_FOUND)
            if previous.status=='STARTED':raise ApplicationError(Code.BROWSER_PLAN_RECONCILIATION_REQUIRED)
            if previous.attempt_number>=3:raise ApplicationError(Code.BROWSER_PLAN_RETRY_EXHAUSTED)
            if uow.browser_plans.has_retry(previous.id):raise ApplicationError(Code.BROWSER_PLAN_RETRY_NOT_ALLOWED)
            if previous.error_code not in RETRYABLE:raise ApplicationError(Code.BROWSER_PLAN_RETRY_NOT_ALLOWED)
            if previous.settings!=generator.settings:raise ApplicationError(Code.BROWSER_PLAN_PROVENANCE_MISMATCH)
            record=BrowserPlanGeneration(**previous.model_dump(exclude={'id','status','started_at','finished_at','error_code','metadata','output','plan_hash','previous_id','attempt_number'}),
                previous_id=previous.id,attempt_number=previous.attempt_number+1)
        else:
            test=app._test_child(uow,project_id,campaign_id,identifier(test_id),'specification')
            if not uow.test_specifications.is_current(test.id) or test.review_status!='APPROVED':raise ApplicationError(Code.REVIEW_NOT_REVIEWABLE)
            if campaign.target_id is None:raise ApplicationError(Code.BROWSER_PLAN_PROVENANCE_MISMATCH)
            target=TargetSnapshot.capture(app._target(uow,project_id,campaign.target_id))
            approval=uow.campaign_reviews.evidence(test,'TEST_SPECIFICATION')
            try:record=BrowserPlanGeneration(project_id=project_id,campaign_id=campaign_id,test=test,approval=approval,target=target,
                test_hash=input_hash(test,approval),target_hash=digest(target),settings=generator.settings)
            except (ValueError,TypeError):raise ApplicationError(Code.GENERATION_CONTEXT_LIMIT) from None
        uow.browser_plans.reserve(record);uow.commit()
    # Durable STARTED precedes exactly one model attempt. No transaction spans provider work.
    metadata=output=error=None
    try:
        policy=BrowserExecutionPolicy() if app._browser_executor is None else app._browser_executor.policy_for(record.target)
        policy.validate_target(record.target)
        response=generator.generate(generator.prepare(record))
        metadata=ModelMetadata.model_validate(response.metadata.model_dump())
        if metadata.status!='completed':raise ModelError(ProviderErrorCategory.INCOMPLETE_RESPONSE,metadata=metadata)
        output=validate_candidate(record,response.parsed_output,policy)
    except BrowserPolicyError:error='BROWSER_PLAN_POLICY_REJECTED'
    except ModelError as failure:
        error=failure.code
        try:metadata=None if failure.metadata is None else ModelMetadata.model_validate(failure.metadata.model_dump())
        except (AttributeError,ValidationError):metadata=None
    except (ValueError,TypeError) as failure:
        error=str(failure) if str(failure) in {'BROWSER_PLAN_INVALID_OUTPUT','BROWSER_PLAN_POLICY_REJECTED','BROWSER_PLAN_GROUNDING_REJECTED','BROWSER_PLAN_INSUFFICIENT_INFORMATION'} else 'BROWSER_PLAN_INVALID_OUTPUT'
    except Exception:error='MODEL_UNKNOWN_PROVIDER_ERROR'
    completed=BrowserPlanGeneration.model_validate({**record.model_dump(),'status':'FAILED' if error else 'SUCCEEDED',
        'finished_at':datetime.now(timezone.utc),'error_code':error,'metadata':metadata,'output':None if error else output,
        'plan_hash':None if error else digest(output.plan)})
    with persistence_boundary(),UnitOfWork(app._factory) as uow:
        uow.browser_plans.finish(completed);uow.commit()
    return completed
