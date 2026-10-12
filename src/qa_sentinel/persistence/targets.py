"""Project-scoped, bounded Target persistence; no runtime/network composition."""
from sqlalchemy import select
from qa_sentinel.domain.target import TargetUnderTest
from .models import TargetRow, CampaignTargetRow


def from_row(row):
    return TargetUnderTest.model_validate({name:getattr(row,name) for name in TargetUnderTest.model_fields})


class TargetRepository:
    def __init__(self, session):
        self.session = session

    def get(self, project_id, target_id):
        row = self.session.scalar(select(TargetRow).where(TargetRow.project_id==str(project_id), TargetRow.id==str(target_id)))
        return None if row is None else from_row(row)

    def list(self, project_id, limit):
        return [from_row(r) for r in self.session.scalars(select(TargetRow).where(TargetRow.project_id==str(project_id)).order_by(TargetRow.id).limit(limit+1))]

    def add(self, target):
        values = target.model_dump(mode="json")
        values.update(created_at=target.created_at, updated_at=target.updated_at)
        self.session.add(TargetRow(**values)); self.session.flush()

    def save(self, target):
        row = self.session.get(TargetRow, str(target.id))
        if row is None or row.project_id != str(target.project_id):
            raise ValueError("Target owner is immutable")
        for name in ("name","type","environment","configuration"):
            setattr(row,name,target.model_dump(mode="json")[name])
        row.updated_at=target.updated_at; self.session.flush()

    def associate(self, campaign, target_id):
        row = self.session.get(CampaignTargetRow, str(campaign.id))
        if target_id is None:
            if row is not None: self.session.delete(row)
        elif row is None:
            self.session.add(CampaignTargetRow(campaign_id=str(campaign.id),project_id=str(campaign.project_id),target_id=str(target_id)))
        else:
            if row.project_id != str(campaign.project_id): raise ValueError("Campaign owner is immutable")
            row.target_id=str(target_id)
        self.session.flush()
