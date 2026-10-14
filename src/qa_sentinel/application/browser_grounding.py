"""Single explicit observation/reasoning attempt, never a Run or QA outcome.

Only trusted local composition injects these capabilities. Public/demo factories
remain unconfigured. Transactions never span Chromium, DNS, or provider work.
"""
from pydantic import ValidationError
from qa_sentinel.domain.browser_grounding import (GroundingScope, BrowserGroundingRecord,
    BrowserGroundingObservation, GroundingLimitation, digest, now)
from qa_sentinel.domain.browser_execution import BrowserErrorCode
from qa_sentinel.execution.browser_network import BrowserExecutionError
from qa_sentinel.agents.browser_grounding import test_intent, validate_grounding
from qa_sentinel.models.base import ModelMetadata, ModelError, ProviderErrorCategory
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from .errors import ApplicationError, ApplicationErrorCode as Code


def read(app, project_id, campaign_id, record_id, *, observation=False):
    from .service import identifier, persistence_boundary
    p,c,id=map(identifier,(project_id,campaign_id,record_id))
    with persistence_boundary(),UnitOfWork(app._factory) as uow:
        app._campaign(uow,p,c)
        result=(uow.browser_groundings.observation if observation else uow.browser_groundings.get)(p,c,id)
        if result is None:raise ApplicationError(Code.GROUNDING_NOT_FOUND)
        return result


def ground(app, project_id, campaign_id, preparation_id, item_id, attempt_id):
    from .service import identifier,persistence_boundary
    p,c,preparation_id,item_id,attempt_id=map(identifier,(project_id,campaign_id,preparation_id,item_id,attempt_id))
    observer,reasoner=app._browser_observer,app._browser_grounding_reasoner
    if observer is None or reasoner is None:raise ApplicationError(Code.GENERATION_NOT_CONFIGURED)
    with persistence_boundary(),UnitOfWork(app._factory) as uow:
        uow.session.connection(execution_options={"qa_job_write":True})
        app._campaign(uow,p,c)
        root=uow.browser_preparations.get(p,c,preparation_id)
        if root is None:raise ApplicationError(Code.PREPARATION_NOT_FOUND)
        item=next((i for i in root.items if i.id==item_id),None)
        if item is None or item.attempt_id!=attempt_id:raise ApplicationError(Code.PREPARATION_INVALID_STATE)
        scope=GroundingScope(project_id=p,campaign_id=c,preparation_id=root.id,item_id=item.id,attempt_id=attempt_id,
            test_id=item.original_test_id,test_hash=item.test_hash,approval_hash=digest(item.approval),
            target=root.target_snapshot,target_hash=digest(root.target_snapshot),policy=observer.policy_for(root.target_snapshot))
        previous=uow.browser_groundings.by_attempt(scope)
        if previous is not None:
            if previous.scope!=scope:raise ApplicationError(Code.PREPARATION_INVALID_STATE)
            if previous.status=="STARTED":raise ApplicationError(Code.GROUNDING_RECONCILIATION_REQUIRED)
            return previous  # Replay reads the durable result; never repeats external work.
        if root.status!="PREPARING" or item.status!="PREPARING":raise ApplicationError(Code.PREPARATION_INVALID_STATE)
        record=BrowserGroundingRecord(scope=scope,settings=reasoner.settings,prompt_version="browser-grounder-v2")
        uow.browser_groundings.reserve(record);uow.commit()
    metadata=output=constraints=intent_hash=observation=None
    status,reason,step,browser_error="GROUNDED",None,None,None
    phase="inspection"
    try:
        intent=test_intent(item.test,scope.target)  # Reject secrets/auth before target access.
        candidate=BrowserGroundingObservation.model_validate(observer.observe(scope).model_dump())
        if candidate.scope!=scope:raise GroundingLimitation("INVALID_REFERENCE")
        observation=candidate
        with persistence_boundary(),UnitOfWork(app._factory) as uow:
            uow.session.connection(execution_options={"qa_job_write":True})
            uow.browser_groundings.add_observation(observation);uow.commit()
        phase="reasoning"
        request=reasoner.prepare(record,observation,intent)
        response=reasoner.generate(request)  # Exactly once; no application retries here.
        metadata=ModelMetadata.model_validate(response.metadata.model_dump())
        if metadata.status!="completed":raise ModelError(ProviderErrorCategory.INCOMPLETE_RESPONSE,metadata=metadata)
        constraints,intent_hash=validate_grounding(record,observation,item.test,item.approval,response.parsed_output)
        output=response.parsed_output
    except ApplicationError:
        raise  # A failed observation write leaves STARTED for reconciliation, not replay.
    except GroundingLimitation as failure:
        status,reason,step="NEEDS_ATTENTION",failure.reason,failure.step
    except BrowserExecutionError as failure:
        browser_error=failure.code.value
        if failure.code in {BrowserErrorCode.NETWORK,BrowserErrorCode.REDIRECT,BrowserErrorCode.PLAN}:
            status,reason="NEEDS_ATTENTION","POLICY_REJECTED"
        elif failure.code==BrowserErrorCode.UNSUPPORTED:
            status,reason="NEEDS_ATTENTION","UNSUPPORTED_BEHAVIOR"
        else:status,reason="SYSTEM_ERROR","OBSERVATION_RUNTIME_ERROR"
    except ModelError as failure:
        status,reason="SYSTEM_ERROR","MODEL_UNAVAILABLE"
        try:metadata=None if failure.metadata is None else ModelMetadata.model_validate(failure.metadata.model_dump())
        except (AttributeError,ValidationError):metadata=None
    except (ValidationError,ValueError,TypeError):
        status,reason="NEEDS_ATTENTION","INVALID_REFERENCE"
    except Exception:
        status,reason="SYSTEM_ERROR",("OBSERVATION_RUNTIME_ERROR" if phase=="inspection" else "MODEL_UNAVAILABLE")
    completed=BrowserGroundingRecord.model_validate({**record.model_dump(),"status":status,"finished_at":now(),
        "observation_id":None if observation is None else observation.id,
        "observation_hash":None if observation is None else observation.observation_hash,
        "metadata":metadata,"output":output,"constraints":constraints,"intent_hash":intent_hash,
        "reason":reason,"affected_step":step,"browser_error_code":browser_error})
    with persistence_boundary(),UnitOfWork(app._factory) as uow:
        uow.session.connection(execution_options={"qa_job_write":True})
        uow.browser_groundings.finish(completed);uow.commit()
    return completed
