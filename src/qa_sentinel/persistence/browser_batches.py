"""Scoped immutable command/plan/Run receipts; no external work in repositories."""
from sqlalchemy import select,update,exists,text
from .models import (BrowserBatchSubmissionRow,BrowserBatchPlanRow,BrowserBatchRunItemRow,
    BrowserPreparationRow,QARunRow,ProjectRow)
from .browser_preparations import BrowserPreparationRepository
from .browser_groundings import BrowserGroundingRepository
from qa_sentinel.domain.browser_batch import BrowserBatchSubmission,BrowserBatchPlan
from qa_sentinel.domain.browser_grounding import GroundingLimitation,digest
from qa_sentinel.domain.browser_generation import BrowserPlanOutput
from qa_sentinel.agents.browser_plan_generation import validate_system_candidate


class BrowserBatchRepository:
    def __init__(self,session):self.session=session

    def submission(self,p,c,id):
        row=self.session.scalar(select(BrowserBatchSubmissionRow).where(BrowserBatchSubmissionRow.preparation_id==str(id),BrowserBatchSubmissionRow.project_id==str(p),BrowserBatchSubmissionRow.campaign_id==str(c)))
        if row is None:return None
        value=BrowserBatchSubmission.model_validate(row.payload)
        if (str(value.preparation_id),str(value.project_id),str(value.campaign_id),value.created_at)!=(row.preparation_id,row.project_id,row.campaign_id,row.created_at):raise ValueError("Submission storage mismatch")
        return value

    def submit(self,root):
        value=BrowserBatchSubmission(preparation_id=root.id,project_id=root.project_id,campaign_id=root.campaign_id,selection_hash=root.selection_hash,browser_mode=root.browser_mode)
        self.session.add(BrowserBatchSubmissionRow(preparation_id=str(root.id),project_id=str(root.project_id),campaign_id=str(root.campaign_id),created_at=value.created_at,payload=value.model_dump(mode="json")));self.session.flush()

    def next(self,keys=None):
        table=BrowserPreparationRow
        query=select(table).join(BrowserBatchSubmissionRow,table.id==BrowserBatchSubmissionRow.preparation_id).outerjoin(QARunRow,QARunRow.preparation_id==table.id).where(
            ((table.status=="CREATED") | ((table.status=="COMPLETED") & ((QARunRow.execution_status=="CREATED") | (QARunRow.id.is_(None) & text("EXISTS (SELECT 1 FROM json_each(browser_preparations.payload,'$.items') i WHERE json_extract(i.value,'$.status')='RUNNABLE')"))))),
            text("json_extract(browser_batch_submissions.payload,'$.interruption_acknowledged_at') IS NULL"))
        if keys is not None:query=query.join(ProjectRow,ProjectRow.id==table.project_id).where(ProjectRow.key.in_(keys))
        row=self.session.scalar(query.order_by(table.created_at,table.id).limit(1))
        return None if row is None else (row.project_id,row.campaign_id,row.id)

    def plan(self,p,c,prep,item):
        row=self.session.scalar(select(BrowserBatchPlanRow).where(BrowserBatchPlanRow.project_id==str(p),BrowserBatchPlanRow.campaign_id==str(c),BrowserBatchPlanRow.preparation_id==str(prep),BrowserBatchPlanRow.item_id==str(item)))
        if row is None:return None
        value=BrowserBatchPlan.model_validate(row.payload);scope=value.scope
        if (str(value.id),str(scope.project_id),str(scope.campaign_id),str(scope.preparation_id),str(scope.item_id),str(scope.attempt_id),str(scope.test_id),str(value.grounding_id),str(value.observation_id),value.plan_hash)!=(row.id,row.project_id,row.campaign_id,row.preparation_id,row.item_id,row.attempt_id,row.test_id,row.grounding_id,row.observation_id,row.plan_hash):raise ValueError("Plan storage identity mismatch")
        return value

    def validate_plan(self,root,item,receipt):
        receipt=BrowserBatchPlan.model_validate(receipt.model_dump())
        scope=receipt.scope
        if (scope.project_id,scope.campaign_id,scope.preparation_id,scope.item_id,scope.attempt_id,scope.test_id,scope.test_hash,scope.approval_hash,scope.target,receipt.selection_hash,receipt.browser_mode)!=(root.project_id,root.campaign_id,root.id,item.id,item.attempt_id,item.original_test_id,item.test_hash,digest(item.approval),root.target_snapshot,root.selection_hash,root.browser_mode):raise GroundingLimitation("INVALID_REFERENCE")
        repository=BrowserGroundingRepository(self.session)
        grounding=repository.get(root.project_id,root.campaign_id,receipt.grounding_id)
        observed=repository.observation(root.project_id,root.campaign_id,receipt.observation_id)
        if grounding is None or observed is None or grounding.scope!=scope or observed.scope!=scope or receipt.observation_hash!=observed.observation_hash or grounding.observation_id!=observed.id or grounding.finished_at>receipt.created_at:raise GroundingLimitation("INVALID_REFERENCE")
        output=BrowserPlanOutput(disposition="CANDIDATE",plan=receipt.plan,step_bindings=grounding.constraints.step_bindings if grounding.constraints else (),unable_reason=None)
        validate_system_candidate(grounding,observed,item.test,item.approval,output,scope.policy)
        if tuple(r.content.id for r in receipt.requirements)!=item.test.requirement_ids:raise GroundingLimitation("INVALID_REFERENCE")
        if any((r.content.project_id,r.content.campaign_id)!=(root.project_id,root.campaign_id) for r in receipt.requirements):raise GroundingLimitation("INVALID_REFERENCE")
        return receipt

    def add_plan(self,root,item,receipt):
        self.validate_plan(root,item,receipt)
        BrowserGroundingRepository(self.session).active_item(receipt.scope)
        scope=receipt.scope
        self.session.add(BrowserBatchPlanRow(id=str(receipt.id),project_id=str(scope.project_id),campaign_id=str(scope.campaign_id),preparation_id=str(scope.preparation_id),item_id=str(scope.item_id),attempt_id=str(scope.attempt_id),test_id=str(scope.test_id),grounding_id=str(receipt.grounding_id),observation_id=str(receipt.observation_id),plan_hash=receipt.plan_hash,payload=receipt.model_dump(mode="json")));self.session.flush()

    def validate_run(self,prepared,*,require_links=False):
        run=prepared.run
        root=BrowserPreparationRepository(self.session).get(run.project_id,run.campaign_id,run.preparation_id)
        if self.submission(run.project_id,run.campaign_id,root.id) is None:return  # Historical/internal v3 compatibility.
        links={}
        if require_links:
            links={row.run_test_id:row for row in self.session.scalars(select(BrowserBatchRunItemRow).where(BrowserBatchRunItemRow.run_id==str(run.id),BrowserBatchRunItemRow.project_id==str(run.project_id),BrowserBatchRunItemRow.campaign_id==str(run.campaign_id)).limit(501))}
            if set(links)!={str(t.id) for t in prepared.tests}:raise GroundingLimitation("INVALID_REFERENCE")
        for test in prepared.tests:
            item=next(i for i in root.items if i.original_test_id==test.content.id)
            plan=self.plan(run.project_id,run.campaign_id,root.id,item.id)
            if plan is None:raise GroundingLimitation("INVALID_REFERENCE")
            self.validate_plan(root,item,plan)
            if require_links and (links[str(test.id)].preparation_id,links[str(test.id)].item_id,links[str(test.id)].plan_receipt_id)!=(str(root.id),str(item.id),str(plan.id)):raise GroundingLimitation("INVALID_REFERENCE")
            if test.browser_plan.plan!=plan.plan or run.runtime_identity!=plan.runtime_identity:raise GroundingLimitation("INVALID_REFERENCE")
            mapped={r.content.id:r for r in prepared.requirements}
            if any(r.content!=mapped[r.content.id].content or r.approval!=mapped[r.content.id].approval for r in plan.requirements):raise GroundingLimitation("INVALID_REFERENCE")

    def link_run(self,prepared):
        self.validate_run(prepared);run=prepared.run
        root=BrowserPreparationRepository(self.session).get(run.project_id,run.campaign_id,run.preparation_id)
        for test in prepared.tests:
            item=next(i for i in root.items if i.original_test_id==test.content.id)
            plan=self.plan(run.project_id,run.campaign_id,root.id,item.id)
            self.session.add(BrowserBatchRunItemRow(run_test_id=str(test.id),project_id=str(run.project_id),campaign_id=str(run.campaign_id),run_id=str(run.id),preparation_id=str(root.id),item_id=str(item.id),plan_receipt_id=str(plan.id)))
        self.session.flush()

    def acknowledge(self,before,after):
        if before.interruption_acknowledged_at is not None:return before
        result=self.session.execute(update(BrowserBatchSubmissionRow).where(BrowserBatchSubmissionRow.preparation_id==str(before.preparation_id),BrowserBatchSubmissionRow.project_id==str(before.project_id),BrowserBatchSubmissionRow.campaign_id==str(before.campaign_id),BrowserBatchSubmissionRow.payload==before.model_dump(mode="json")).values(payload=after.model_dump(mode="json")))
        if result.rowcount!=1:raise ValueError("Interruption acknowledgement conflict")
        return after
