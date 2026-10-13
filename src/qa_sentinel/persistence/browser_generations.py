"""Scoped bounded immutable candidates and append-only acceptance receipts."""
from sqlalchemy import select, update
from .models import BrowserPlanGenerationRow as Row, BrowserPlanAcceptanceRow as Acceptance
from qa_sentinel.domain.browser_generation import BrowserPlanGeneration, BrowserPlanAcceptance

class BrowserPlanRepository:
    def __init__(self,session):self.session=session

    @staticmethod
    def decode(row):
        record=BrowserPlanGeneration.model_validate(row.payload)
        if (str(record.id),str(record.project_id),str(record.campaign_id),record.status)!=(row.id,row.project_id,row.campaign_id,row.status):raise ValueError('Stored planning identity mismatch')
        if (str(record.test.id),str(record.target.target_id),None if record.previous_id is None else str(record.previous_id),record.started_at)!=(row.test_id,row.target_id,row.previous_id,row.started_at):raise ValueError('Stored planning input identity mismatch')
        return record

    def get(self,project_id,campaign_id,id):
        row=self.session.scalar(select(Row).where(Row.id==str(id),Row.project_id==str(project_id),Row.campaign_id==str(campaign_id)))
        return None if row is None else self.decode(row)

    def list(self,project_id,campaign_id,limit):
        if type(limit)is not int or not 1<=limit<=50:raise ValueError('Planning list bound')
        return [self.decode(r) for r in self.session.scalars(select(Row).where(Row.project_id==str(project_id),Row.campaign_id==str(campaign_id))
            .order_by(Row.started_at,Row.id).limit(limit+1))]

    def has_retry(self,id):
        return self.session.scalar(select(Row.id).where(Row.previous_id==str(id))) is not None

    def reserve(self,record):
        record=BrowserPlanGeneration.model_validate(record.model_dump())
        if record.status!='STARTED':raise ValueError('Reserve only started')
        if record.previous_id is not None:
            previous=self.get(record.project_id,record.campaign_id,record.previous_id)
            if previous is None or previous.status!='FAILED' or record.attempt_number!=previous.attempt_number+1 or (record.test_hash,record.target_hash,record.settings,record.prompt_version)!=(previous.test_hash,previous.target_hash,previous.settings,previous.prompt_version):raise ValueError('Retry does not match immutable predecessor')
        self.session.add(Row(id=str(record.id),project_id=str(record.project_id),campaign_id=str(record.campaign_id),test_id=str(record.test.id),
            target_id=str(record.target.target_id),previous_id=None if record.previous_id is None else str(record.previous_id),status=record.status,
            started_at=record.started_at,payload=record.model_dump(mode='json')))
        self.session.flush()

    def finish(self,record):
        record=BrowserPlanGeneration.model_validate(record.model_dump())
        old=self.get(record.project_id,record.campaign_id,record.id)
        if old is None or old.status!='STARTED' or record.status=='STARTED':raise ValueError('Planning completion cannot replay')
        changing={'status','finished_at','error_code','metadata','output','plan_hash'}
        if old.model_dump(exclude=changing)!=record.model_dump(exclude=changing):raise ValueError('Planning inputs are immutable')
        changed=self.session.execute(update(Row).where(Row.id==str(record.id),Row.status=='STARTED').values(status=record.status,payload=record.model_dump(mode='json')))
        if changed.rowcount!=1:raise ValueError('Planning completion conflict')
        self.session.flush()

    def acceptance(self,project_id,campaign_id,id):
        row=self.session.scalar(select(Acceptance).where(Acceptance.generation_id==str(id),Acceptance.project_id==str(project_id),Acceptance.campaign_id==str(campaign_id)))
        return None if row is None else BrowserPlanAcceptance.model_validate({name:getattr(row,name) for name in BrowserPlanAcceptance.model_fields})

    def accept(self,record):
        record=BrowserPlanAcceptance.model_validate(record.model_dump())
        candidate=self.get(record.project_id,record.campaign_id,record.generation_id)
        if candidate is None or candidate.status!='SUCCEEDED' or candidate.plan_hash!=record.plan_hash:raise ValueError('Acceptance requires validated candidate')
        from .qa_runs import QARunRepository
        from qa_sentinel.domain.browser_generation import input_hash,object_hash
        runs=QARunRepository(self.session)
        run=runs.get(record.project_id,record.campaign_id,record.run_id)
        test=None if run is None else runs.test(run,record.run_test_id)
        if (run is None or test is None or run.executor_kind!='WEB_BROWSER' or test.browser_plan is None or test.browser_plan.origin!='AI'
                or test.browser_plan.plan!=candidate.output.plan or run.target_snapshot is None or object_hash(run.target_snapshot)!=candidate.target_hash
                or input_hash(test.content,test.approval)!=candidate.test_hash):raise ValueError('Acceptance does not match sealed Run')
        values=record.model_dump(mode='json');values['accepted_at']=record.accepted_at
        self.session.add(Acceptance(**values));self.session.flush()
