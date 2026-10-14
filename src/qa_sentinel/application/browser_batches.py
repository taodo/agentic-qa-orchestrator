"""Sequential durable browser batches over accepted grounding and Run boundaries."""
from contextlib import nullcontext
from collections import Counter
from uuid import UUID,uuid4,uuid5
from pydantic import Field,AwareDatetime
from sqlalchemy import select
from qa_sentinel.domain.browser_preparation import CreateBrowserPreparation,now
from qa_sentinel.domain.browser_batch import BrowserBatchPlan,BrowserBatchSubmission,BatchRequirement
from qa_sentinel.domain.browser_grounding import GroundingLimitation,BrowserGroundingRecord,digest,ACTION_HINTS
from qa_sentinel.domain.target import TargetSnapshot
from qa_sentinel.domain.browser_execution import BrowserExecutionPlan,BrowserPlanEnvelope
from qa_sentinel.domain.browser_generation import BrowserPlanOutput
from qa_sentinel.domain.qa_run import (QARun,QARunTest,QARunRequirement,PreparedQARun,CampaignSnapshot,
    BROWSER_SNAPSHOT_VERSION,snapshot_fingerprint)
from qa_sentinel.execution.browser_policy import run_test_snapshot_digest
from qa_sentinel.agents.browser_grounding import validated_constraints
from qa_sentinel.agents.browser_plan_generation import validate_system_candidate
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.models import QARunRow,BrowserGroundingRow
from .models import View,CollectionPage
from .qa_run_results import QARunEvidenceView,evidence_page
from .errors import ApplicationError,ApplicationErrorCode as Code


class BatchItemView(View):
    id: UUID
    test_id: UUID
    position: int
    key: str
    title: str
    preparation_status: str
    outcome: str
    reason: str | None=None
    affected_step: int | None=None
    hint: str | None=None
    run_test_id: UUID | None=None
    execution_status: str | None=None
    qa_result: str | None=None
    evidence_count: int | None=None
    evidence: CollectionPage[QARunEvidenceView] | None=None


class BatchView(View):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    status: str
    browser_mode: str
    target_snapshot: TargetSnapshot
    selected_count: int
    summary: dict[str,int]
    run: QARun | None=None
    processing: bool
    reconciliation_required: bool
    interruption_acknowledged_at: AwareDatetime | None=None
    items: CollectionPage[BatchItemView]
    duration_seconds: float | None=None


def _owner(app,uow,p,c,id):
    app._campaign(uow,p,c)
    root=uow.browser_preparations.get(p,c,id)
    submission=uow.browser_batches.submission(p,c,id)
    if root is None or submission is None:raise ApplicationError(Code.BROWSER_BATCH_NOT_FOUND)
    if (root.selection_hash,root.browser_mode)!=(submission.selection_hash,submission.browser_mode):raise ValueError("Batch submission seal mismatch")
    return root,submission


def _configured(app):
    if app._browser_observer is None or app._browser_grounding_reasoner is None or app._browser_executor is None:
        raise ApplicationError(Code.BROWSER_BATCH_NOT_CONFIGURED)


def submit(app,p,c,**arguments):
    from .service import identifier,persistence_boundary
    p,c=map(identifier,(p,c));_configured(app)
    try:command=CreateBrowserPreparation(**arguments)
    except ValueError:raise ApplicationError(Code.INVALID_INPUT) from None
    with persistence_boundary(),UnitOfWork(app._factory) as uow:
        app._campaign(uow,p,c)
        existing=uow.browser_preparations.by_key(p,c,command.idempotency_key)
        if existing is not None and (tuple(i.original_test_id for i in existing.items)!=command.test_specification_ids or existing.browser_mode!=command.browser_mode):
            raise ApplicationError(Code.PREPARATION_IDEMPOTENCY_CONFLICT)
    if existing is None:
        view=app.create_browser_preparation(p,c,**command.model_dump())
        id=view.id
    else:id=existing.id
    with persistence_boundary(),UnitOfWork(app._factory) as uow:
        uow.session.connection(execution_options={"qa_job_write":True})
        root=uow.browser_preparations.get(p,c,id)
        if uow.browser_batches.submission(p,c,id) is None:
            if root.status!="CREATED":raise ApplicationError(Code.BROWSER_BATCH_RECONCILIATION_REQUIRED)
            uow.browser_batches.submit(root);uow.commit()
    if app._execution_notify is not None:app._execution_notify()
    return read(app,p,c,id)


def next_batch(app):
    if app._browser_observer is None or app._browser_grounding_reasoner is None or app._browser_executor is None:return None
    from .service import persistence_boundary
    with persistence_boundary(),UnitOfWork(app._factory) as uow:
        return uow.browser_batches.next(app._browser_batch_project_keys)


def _requirements(uow,item):
    values=[]
    for id in item.test.requirement_ids:
        content=uow.campaign_content.requirement(id)
        if content is None or (content.project_id,content.campaign_id)!=(item.test.project_id,item.test.campaign_id) or not uow.campaign_content.is_current(id):raise GroundingLimitation("INVALID_REFERENCE")
        values.append(BatchRequirement(content=content,approval=uow.campaign_reviews.evidence(content,"REQUIREMENT")))
    return tuple(values)


def _seal_item(app,p,c,id,item_id):
    from .service import persistence_boundary
    with persistence_boundary(),UnitOfWork(app._factory) as uow:
        root,_=_owner(app,uow,p,c,id);item=next(i for i in root.items if i.id==item_id)
    grounding=app.ground_browser_preparation_item(p,c,id,item.id,item.attempt_id)
    # Reload authoritative artifacts. The returned object is deliberately not trusted.
    with persistence_boundary(),UnitOfWork(app._factory) as uow:
        uow.session.connection(execution_options={"qa_job_write":True})
        root,_=_owner(app,uow,p,c,id);item=next(i for i in root.items if i.id==item_id)
        grounding=uow.browser_groundings.get(p,c,grounding.id)
        status,reason="RUNNABLE",None
        receipt=None
        if grounding is None:raise ApplicationError(Code.PERSISTENCE_ERROR)
        if grounding.status=="STARTED":raise ApplicationError(Code.BROWSER_BATCH_RECONCILIATION_REQUIRED)
        if grounding.status=="SYSTEM_ERROR":status,reason="SYSTEM_ERROR","PREPARATION_SYSTEM_ERROR"
        elif grounding.status=="NEEDS_ATTENTION":
            status="NEEDS_ATTENTION"
            reason=grounding.reason if grounding.reason in {"INSUFFICIENT_TEST_INFORMATION","AMBIGUOUS_TARGET","UNSUPPORTED_BEHAVIOR","POLICY_REJECTED","GROUNDING_UNAVAILABLE"} else "GROUNDING_UNAVAILABLE"
        else:
            try:
                observed=uow.browser_groundings.observation(p,c,grounding.observation_id)
                constraints=validated_constraints(grounding,observed,item.test,item.approval)
                plan=BrowserExecutionPlan(steps=constraints.action_manifest,redirect_limit=0,screenshot_limit=0)
                output=BrowserPlanOutput(disposition="CANDIDATE",plan=plan,step_bindings=constraints.step_bindings,unable_reason=None)
                policy=app._browser_executor.policy_for(root.target_snapshot)
                validate_system_candidate(grounding,observed,item.test,item.approval,output,policy)
                receipt=BrowserBatchPlan(scope=grounding.scope,selection_hash=root.selection_hash,browser_mode=root.browser_mode,
                    grounding_id=grounding.id,observation_id=observed.id,observation_hash=observed.observation_hash,
                    plan=plan,plan_hash=digest(plan),runtime_identity=app._browser_executor.identity,requirements=_requirements(uow,item))
                uow.browser_batches.add_plan(root,item,receipt)
            except GroundingLimitation as error:
                receipt=None
                status="NEEDS_ATTENTION";reason="POLICY_REJECTED" if error.reason=="POLICY_REJECTED" else "GROUNDING_UNAVAILABLE"
            except ValueError:receipt=None;status,reason="NEEDS_ATTENTION","GROUNDING_UNAVAILABLE"
        uow.browser_preparations.transition(root,"FINISH_ITEM",item_id=item.id,attempt_id=item.attempt_id,status=status,reason_code=reason,
            grounding_id=None if receipt is None else receipt.grounding_id,observation_hash=None if receipt is None else receipt.observation_hash,plan_hash=None if receipt is None else receipt.plan_hash)
        uow.commit()


def _materialize(app,p,c,id):
    from .service import persistence_boundary
    with persistence_boundary(),UnitOfWork(app._factory) as uow:
        uow.session.connection(execution_options={"qa_job_write":True})
        root,_=_owner(app,uow,p,c,id)
        if root.status!="COMPLETED":raise ApplicationError(Code.PREPARATION_INVALID_STATE)
        prior=uow.browser_preparations.view(root).resulting_run_id
        if prior is not None:return uow.qa_runs.get(p,c,prior)
        items=[i for i in root.items if i.status=="RUNNABLE"]
        if not items:return None
        receipts=[];needed={}
        for item in items:
            receipt=uow.browser_batches.plan(p,c,id,item.id)
            if receipt is None:raise ApplicationError(Code.PERSISTENCE_ERROR)
            receipt=uow.browser_batches.validate_plan(root,item,receipt)
            if receipt.runtime_identity!=app._browser_executor.identity:raise ApplicationError(Code.RUN_INVALID_STATE)
            receipts.append(receipt)
            for required in receipt.requirements:
                if required.content.id in needed and needed[required.content.id]!=required:raise ApplicationError(Code.REVIEW_EVIDENCE_INVALID)
                needed[required.content.id]=required
        run_id=uuid4()
        reqs=tuple(QARunRequirement(id=uuid5(run_id,"requirement:"+str(r.content.id)),run_id=run_id,original_requirement_id=r.content.id,position=n,content=r.content,approval=r.approval)
            for n,r in enumerate(sorted(needed.values(),key=lambda r:str(r.content.id)),1))
        req_ids={r.content.id:r.id for r in reqs}
        campaign=CampaignSnapshot.model_validate(app._campaign(uow,p,c).model_dump(include=set(CampaignSnapshot.model_fields)))
        readiness=app.get_campaign_readiness(p,c)  # Reuse the authoritative read; no model/tool work.
        run=QARun(id=run_id,project_id=p,campaign_id=c,run_number=uow.qa_runs.next_number(c),idempotency_key="batch-"+str(id),
            snapshot_version=BROWSER_SNAPSHOT_VERSION,snapshot_hash="0"*64,target_snapshot=root.target_snapshot,executor_kind="WEB_BROWSER",
            runtime_identity=app._browser_executor.identity,campaign_snapshot=campaign,readiness_at_creation=readiness,preparation_id=id,requirement_count=len(reqs),test_count=len(items))
        sealed=[]
        for position,(item,receipt) in enumerate(zip(items,receipts),1):
            test=QARunTest(id=uuid5(run_id,"test:"+str(item.original_test_id)),run_id=run_id,original_test_specification_id=item.original_test_id,position=position,
                content=item.test,approval=item.approval,snapshot_version=BROWSER_SNAPSHOT_VERSION,linked_requirement_snapshot_ids=tuple(req_ids[r] for r in item.test.requirement_ids))
            envelope=BrowserPlanEnvelope(project_id=p,campaign_id=c,run_id=run_id,run_test_id=test.id,origin="DETERMINISTIC",test_snapshot_hash=run_test_snapshot_digest(test),
                target_snapshot_hash=digest(root.target_snapshot),plan_hash=receipt.plan_hash,plan=receipt.plan)
            receipt.scope.policy.validate_envelope(envelope,run,test)
            sealed.append(QARunTest.model_validate({**test.model_dump(),"snapshot_version":BROWSER_SNAPSHOT_VERSION,"browser_plan":envelope}))
        run=QARun.model_validate({**run.model_dump(),"snapshot_hash":snapshot_fingerprint(campaign,reqs,sealed,BROWSER_SNAPSHOT_VERSION,root.target_snapshot,run.runtime_identity,id)})
        prepared=PreparedQARun(run=run,requirements=reqs,tests=tuple(sealed))
        uow.qa_runs.add(prepared);uow.browser_batches.link_run(prepared);uow.commit()
        return run


def execute(app,p,c,id):
    from .service import identifier,persistence_boundary
    p,c,id=map(identifier,(p,c,id));_configured(app)
    admission=app._execution_admission.enter() if app._execution_admission is not None else nullcontext()
    with admission,app._browser_batch_gate:
        if id in app._active_browser_batches:raise ApplicationError(Code.RUNTIME_STOPPED)
        app._active_browser_batches.add(id)
        try:
            with persistence_boundary(),UnitOfWork(app._factory) as uow:
                uow.session.connection(execution_options={"qa_job_write":True})
                root,submission=_owner(app,uow,p,c,id)
                if submission.interruption_acknowledged_at is not None:return read(app,p,c,id)
                if root.status=="PREPARING":raise ApplicationError(Code.BROWSER_BATCH_RECONCILIATION_REQUIRED)
                if root.status=="FAILED":return read(app,p,c,id)
                if root.status=="CREATED":root=uow.browser_preparations.transition(root,"START");uow.commit()
            if root.status=="PREPARING":
                for selected in root.items:
                    with persistence_boundary(),UnitOfWork(app._factory) as uow:
                        uow.session.connection(execution_options={"qa_job_write":True})
                        current,_=_owner(app,uow,p,c,id)
                        uow.browser_preparations.transition(current,"START_ITEM",item_id=selected.id);uow.commit()
                    _seal_item(app,p,c,id,selected.id)
                with persistence_boundary(),UnitOfWork(app._factory) as uow:
                    uow.session.connection(execution_options={"qa_job_write":True})
                    current,_=_owner(app,uow,p,c,id)
                    uow.browser_preparations.transition(current,"FINISH");uow.commit()
            run=_materialize(app,p,c,id)
            if run is not None:
                if run.execution_status=="CREATED":app.start_browser_qa_run(p,c,run.id)
                elif run.execution_status=="RUNNING":raise ApplicationError(Code.BROWSER_BATCH_RECONCILIATION_REQUIRED)
            return read(app,p,c,id)
        finally:app._active_browser_batches.discard(id)


def read(app,p,c,id,*,limit=50,after_position=0):
    from .service import identifier,persistence_boundary,list_limit
    p,c,id=map(identifier,(p,c,id));limit=list_limit(limit,100)
    if type(after_position) is not int or not 0<=after_position<=500:raise ApplicationError(Code.INVALID_INPUT)
    with persistence_boundary(),UnitOfWork(app._factory) as uow:
        root,submission=_owner(app,uow,p,c,id)
        view=uow.browser_preparations.view(root)
        run=None if view.resulting_run_id is None else uow.qa_runs.get(p,c,view.resulting_run_id)
        executions={} if run is None else {t.content.id:t for t in uow.qa_runs.all_entries(run,"tests")}
        processing=id in app._active_browser_batches and (root.status in {"CREATED","PREPARING"} or
            (root.status=="COMPLETED" and ((run is None and any(i.status=="RUNNABLE" for i in root.items)) or (run is not None and run.execution_status in {"CREATED","RUNNING"}))))
        unresolved=not processing and (root.status=="PREPARING" or (run is not None and run.execution_status=="RUNNING"))
        selected=[i for i in root.items if i.position>after_position][:limit+1]
        diagnostics={row.item_id:BrowserGroundingRecord.model_validate(row.payload).model_dump() for row in uow.session.scalars(select(BrowserGroundingRow).where(
            BrowserGroundingRow.project_id==str(p),BrowserGroundingRow.campaign_id==str(c),BrowserGroundingRow.preparation_id==str(id),
            BrowserGroundingRow.item_id.in_([str(i.id) for i in selected[:limit]])).limit(limit))}
        run_test_ids=[executions[i.original_test_id].id for i in selected[:limit] if i.original_test_id in executions]
        previews={} if run is None else uow.qa_runs.evidence_preview(run,run_test_ids,2)
        items=[]
        for item in selected[:limit]:
            test=executions.get(item.original_test_id);diagnostic=diagnostics.get(str(item.id),{})
            reason=diagnostic.get("reason") or item.reason_code
            hint=ACTION_HINTS.get(reason) if reason else None
            if item.status=="NEEDS_ATTENTION":outcome="NEEDS_ATTENTION"
            elif item.status=="SYSTEM_ERROR":outcome="PREPARATION_ERROR"
            elif test is not None and test.execution_status=="COMPLETED":outcome=test.qa_result.value
            elif test is not None and test.execution_status=="RUNNING":
                outcome="EXECUTION_ERROR" if run.execution_status=="FAILED" else "RUNNING" if processing else "INTERRUPTED"
                if run.execution_status=="FAILED":
                    reason=run.browser_error_code.value if run.browser_error_code is not None else "RUN_EXECUTION_FAILED"
                    hint="The browser runtime could not complete this test. Saved evidence remains; unstarted tests are not evaluated. Ask the operator to check Chromium and network setup."
            elif test is not None and run.execution_status=="FAILED":outcome="NOT_EXECUTED"
            elif item.status=="RUNNABLE":outcome="READY"
            elif item.status=="PREPARING":outcome="PREPARING" if processing else "INTERRUPTED"
            else:outcome="PENDING" if root.status!="FAILED" else "NOT_EXECUTED"
            if unresolved or root.error_code=="PREPARATION_INTERRUPTED":hint="This interrupted batch will not replay uncertain work. Review saved outcomes; acknowledge the interruption before explicitly starting a new batch."
            evidence_count,records=previews.get(str(test.id),(0,[])) if test is not None else (None,[])
            evidence=None if test is None else evidence_page(records,2)
            if evidence is not None:evidence=CollectionPage(items=evidence.items,total_returned=len(evidence.items),truncated=evidence_count>len(evidence.items))
            items.append(BatchItemView(id=item.id,test_id=item.original_test_id,position=item.position,key=item.test.key,title=item.test.title,
                preparation_status=item.status,outcome=outcome,reason=reason,affected_step=diagnostic.get("affected_step"),hint=hint,
                run_test_id=None if test is None else test.id,execution_status=None if test is None else test.execution_status,qa_result=None if test is None else test.qa_result,evidence_count=evidence_count,evidence=evidence))
        states=Counter(i.status for i in root.items)
        counts=dict(selected=root.selected_count,pending=states["PENDING"],preparing=states["PREPARING"],runnable=states["RUNNABLE"],needs_attention=states["NEEDS_ATTENTION"],preparation_errors=states["SYSTEM_ERROR"])
        if run is not None:counts.update(uow.qa_runs.result_counts(run))
        else:counts.update(total=0,completed=0,passed=0,failed=0,skipped=0,not_evaluated=0,remaining=0)
        return BatchView(id=id,project_id=p,campaign_id=c,status=root.status,browser_mode=root.browser_mode,target_snapshot=root.target_snapshot,selected_count=root.selected_count,
            summary=counts,run=run,processing=processing,reconciliation_required=unresolved,interruption_acknowledged_at=submission.interruption_acknowledged_at,
            items=CollectionPage(items=tuple(items),total_returned=len(items),truncated=len(selected)>limit),
            duration_seconds=None if run is None or run.started_at is None or run.completed_at is None else (run.completed_at-run.started_at).total_seconds())


def acknowledge(app,p,c,id):
    from .service import identifier,persistence_boundary
    p,c,id=map(identifier,(p,c,id))
    admission=app._execution_admission.enter() if app._execution_admission is not None else nullcontext()
    with admission,app._browser_batch_gate,persistence_boundary(),UnitOfWork(app._factory) as uow:
        uow.session.connection(execution_options={"qa_job_write":True})
        root,before=_owner(app,uow,p,c,id)
        run_id=uow.browser_preparations.view(root).resulting_run_id
        run=None if run_id is None else uow.qa_runs.get(p,c,run_id)
        if id in app._active_browser_batches or not (root.status=="PREPARING" or (run is not None and run.execution_status=="RUNNING")):
            raise ApplicationError(Code.PREPARATION_INVALID_STATE)
        after=BrowserBatchSubmission.model_validate({**before.model_dump(),"interruption_acknowledged_at":now()})
        uow.browser_batches.acknowledge(before,after)
        if root.status=="PREPARING":uow.browser_preparations.transition(root,"FINISH",error_code="PREPARATION_INTERRUPTED")
        uow.commit()
    return read(app,p,c,id)


class BatchHistoryItem(View):
    id: UUID
    status: str
    browser_mode: str
    selected_count: int
    created_at: AwareDatetime
    run_id: UUID | None=None
    execution_status: str | None=None
    qa_outcome: str | None=None


def history(app,p,c,*,limit=20):
    from .service import identifier,persistence_boundary,list_limit
    from qa_sentinel.persistence.models import BrowserPreparationRow,BrowserBatchSubmissionRow
    p,c=map(identifier,(p,c));limit=list_limit(limit,20)
    with persistence_boundary(),UnitOfWork(app._factory) as uow:
        app._campaign(uow,p,c)
        rows=uow.session.execute(select(BrowserPreparationRow.id,BrowserPreparationRow.status,BrowserPreparationRow.browser_mode,BrowserPreparationRow.selected_count,BrowserPreparationRow.created_at,QARunRow.id.label("run_id"),QARunRow.execution_status,QARunRow.qa_outcome)
            .join(BrowserBatchSubmissionRow,BrowserBatchSubmissionRow.preparation_id==BrowserPreparationRow.id).outerjoin(QARunRow,QARunRow.preparation_id==BrowserPreparationRow.id)
            .where(BrowserPreparationRow.project_id==str(p),BrowserPreparationRow.campaign_id==str(c)).order_by(BrowserPreparationRow.created_at.desc(),BrowserPreparationRow.id).limit(limit+1)).mappings().all()
        items=tuple(BatchHistoryItem(**row) for row in rows[:limit])
        return CollectionPage(items=items,total_returned=len(items),truncated=len(rows)>limit)


def approve_tests(app,p,c,*,test_ids,expected_hashes,reviewer_label,note=None):
    from .service import identifier,persistence_boundary
    from qa_sentinel.domain.campaign_review import content_hash,SOURCE_FREE_APPROVAL_POLICY,ReviewError,source_free_reviewable
    p,c=map(identifier,(p,c));ids=tuple(map(identifier,test_ids))
    if not 1<=len(ids)<=500 or len(set(ids))!=len(ids) or set(expected_hashes)!={str(id) for id in ids}:raise ApplicationError(Code.INVALID_INPUT)
    command=app._approval_command(reviewer_label,note,"APPROVE")
    with persistence_boundary(),UnitOfWork(app._factory) as uow:
        uow.session.connection(execution_options={"qa_job_write":True})
        app._campaign(uow,p,c)
        values=[]
        for id in ids:
            record=app._test_child(uow,p,c,id,"specification")
            if not uow.test_specifications.is_current(id) or content_hash(record)!=expected_hashes[str(id)]:raise ApplicationError(Code.REVIEW_CONFLICT)
            values.append(record)
        approved=skipped=0
        for record in values:
            if (record.review_status not in {"READY_FOR_REVIEW","NEEDS_CLARIFICATION"} or not source_free_reviewable(record)
                    or any(not uow.campaign_content.is_current(ref) for ref in record.requirement_ids)):
                skipped+=1;continue
            try:uow.campaign_reviews.approve(record,"TEST_SPECIFICATION",command,policy=SOURCE_FREE_APPROVAL_POLICY)
            except ReviewError as error:raise ApplicationError(Code(str(error))) from None
            approved+=1
        uow.commit()
        return {"matched":len(ids),"approved":approved,"skipped":skipped}
