"""Scoped immutable observation artifacts and one durable attempt per selected item."""
from sqlalchemy import select, update
from .models import BrowserGroundingRow, BrowserGroundingObservationRow
from .browser_preparations import BrowserPreparationRepository
from qa_sentinel.domain.browser_grounding import BrowserGroundingRecord, BrowserGroundingObservation, GroundingLimitation
from qa_sentinel.agents.browser_grounding import validated_constraints


class BrowserGroundingRepository:
    def __init__(self,session):self.session=session

    def active_item(self,scope):
        root=BrowserPreparationRepository(self.session).get(scope.project_id,scope.campaign_id,scope.preparation_id)
        item=None if root is None else next((i for i in root.items if i.id==scope.item_id),None)
        if (root is None or root.status!="PREPARING" or item is None or item.status!="PREPARING" or item.attempt_id!=scope.attempt_id
                or item.original_test_id!=scope.test_id or item.test_hash!=scope.test_hash or root.target_snapshot!=scope.target):
            raise GroundingLimitation("INVALID_REFERENCE")
        from qa_sentinel.domain.browser_grounding import digest
        if digest(item.approval)!=scope.approval_hash:raise GroundingLimitation("INVALID_REFERENCE")
        return item

    def get(self,p,c,id):
        row=self.session.scalar(select(BrowserGroundingRow).where(BrowserGroundingRow.id==str(id),BrowserGroundingRow.project_id==str(p),BrowserGroundingRow.campaign_id==str(c)))
        if row is None:return None
        record=BrowserGroundingRecord.model_validate(row.payload)
        if (str(record.id),str(record.scope.project_id),str(record.scope.campaign_id),record.status)!=(row.id,row.project_id,row.campaign_id,row.status):raise ValueError("Grounding storage identity mismatch")
        if (str(record.scope.preparation_id),str(record.scope.item_id),str(record.scope.attempt_id),str(record.scope.test_id),record.started_at,None if record.observation_id is None else str(record.observation_id)) != (row.preparation_id,row.item_id,row.attempt_id,row.test_id,row.started_at,row.observation_id):raise ValueError("Grounding storage scope mismatch")
        return record

    def by_attempt(self,scope):
        row=self.session.scalar(select(BrowserGroundingRow).where(BrowserGroundingRow.project_id==str(scope.project_id),BrowserGroundingRow.campaign_id==str(scope.campaign_id),BrowserGroundingRow.preparation_id==str(scope.preparation_id),BrowserGroundingRow.item_id==str(scope.item_id),BrowserGroundingRow.attempt_id==str(scope.attempt_id)))
        return None if row is None else self.get(scope.project_id,scope.campaign_id,row.id)

    def observation(self,p,c,id):
        row=self.session.scalar(select(BrowserGroundingObservationRow).where(BrowserGroundingObservationRow.id==str(id),BrowserGroundingObservationRow.project_id==str(p),BrowserGroundingObservationRow.campaign_id==str(c)))
        if row is None:return None
        record=BrowserGroundingObservation.model_validate(row.payload)
        if (str(record.id),str(record.scope.project_id),str(record.scope.campaign_id))!=(row.id,row.project_id,row.campaign_id):raise ValueError("Observation storage identity mismatch")
        if (str(record.scope.preparation_id),str(record.scope.item_id),str(record.scope.attempt_id),str(record.scope.test_id),record.finished_at) != (row.preparation_id,row.item_id,row.attempt_id,row.test_id,row.observed_at):raise ValueError("Observation storage scope mismatch")
        return record

    @staticmethod
    def values(record):
        scope=record.scope
        return dict(id=str(record.id),project_id=str(scope.project_id),campaign_id=str(scope.campaign_id),
            preparation_id=str(scope.preparation_id),item_id=str(scope.item_id),attempt_id=str(scope.attempt_id),
            test_id=str(scope.test_id),payload=record.model_dump(mode="json"))

    def reserve(self,record):
        record=BrowserGroundingRecord.model_validate(record.model_dump())
        self.active_item(record.scope)
        if record.status!="STARTED":raise ValueError("Reserve only a started grounding attempt")
        self.session.add(BrowserGroundingRow(**self.values(record),status=record.status,started_at=record.started_at,observation_id=None));self.session.flush()

    def add_observation(self,observation):
        observation=BrowserGroundingObservation.model_validate(observation.model_dump())
        self.active_item(observation.scope)
        attempt=self.by_attempt(observation.scope)
        if attempt is None or attempt.status!="STARTED" or attempt.scope!=observation.scope or observation.started_at<attempt.started_at:
            raise GroundingLimitation("INVALID_REFERENCE")
        self.session.add(BrowserGroundingObservationRow(**self.values(observation),observed_at=observation.finished_at));self.session.flush()

    def finish(self,record):
        record=BrowserGroundingRecord.model_validate(record.model_dump());old=self.get(record.scope.project_id,record.scope.campaign_id,record.id)
        changing={"status","finished_at","observation_id","observation_hash","intent_hash","output","constraints","metadata","reason","affected_step","browser_error_code"}
        if old is None or old.status!="STARTED" or record.status=="STARTED" or old.model_dump(exclude=changing)!=record.model_dump(exclude=changing):raise ValueError("Grounding completion cannot replay or alter sealed inputs")
        item=self.active_item(record.scope)
        observation=None if record.observation_id is None else self.observation(record.scope.project_id,record.scope.campaign_id,record.observation_id)
        if record.observation_id is not None and (observation is None or observation.scope!=record.scope or observation.observation_hash!=record.observation_hash or observation.finished_at>record.finished_at):raise GroundingLimitation("INVALID_REFERENCE")
        if record.status=="GROUNDED":validated_constraints(record,observation,item.test,item.approval)
        changed=self.session.execute(update(BrowserGroundingRow).where(BrowserGroundingRow.id==str(record.id),BrowserGroundingRow.status=="STARTED").values(status=record.status,observation_id=None if record.observation_id is None else str(record.observation_id),payload=record.model_dump(mode="json")))
        if changed.rowcount!=1:raise ValueError("Grounding completion conflict")
        self.session.flush()
