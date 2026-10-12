"""Bounded campaign storage. Transactions belong to the existing UnitOfWork."""
from sqlalchemy import select, func
from qa_sentinel.domain.campaign import CampaignPreparationStatus, validate_campaign_transition
from .models import QACampaignRow, CampaignTargetRow
from qa_sentinel.domain.campaign import QACampaign
from .mappers import campaign_to_orm, campaign_from_orm


class QACampaignRepository:
    def __init__(self, session):
        self.session = session

    def add(self, record):
        row = campaign_to_orm(record)
        if row.status != CampaignPreparationStatus.DRAFT:
            raise ValueError("New campaigns must be DRAFT")
        self.session.add(row)
        self.session.flush()
        if record.target_id is not None:
            self.session.add(CampaignTargetRow(campaign_id=str(record.id), project_id=str(record.project_id), target_id=str(record.target_id)))
            self.session.flush()

    def get(self, record_id):
        row = self.session.get(QACampaignRow, str(record_id))
        if row is None: return None
        target = self.session.get(CampaignTargetRow, str(record_id))
        return QACampaign.model_validate({**campaign_from_orm(row).model_dump(), "target_id": None if target is None else target.target_id})

    def list_for_project(self, project_id, *, limit=50):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Invalid campaign list limit")
        rows = self.session.execute(select(QACampaignRow, CampaignTargetRow.target_id).outerjoin(CampaignTargetRow, CampaignTargetRow.campaign_id==QACampaignRow.id).where(QACampaignRow.project_id == str(project_id))
            .order_by(func.qa_utc_microseconds(QACampaignRow.created_at).desc(), QACampaignRow.id)
            .limit(limit + 1))
        return [QACampaign.model_validate({**campaign_from_orm(row).model_dump(), "target_id": target_id}) for row,target_id in rows]

    def save_metadata(self, record):
        row, values = self._existing(record)
        if row.status != values.status:
            raise ValueError("Metadata cannot change preparation status")
        row.name, row.objective, row.updated_at = values.name, values.objective, values.updated_at
        self.session.flush()

    def save_transition(self, record):
        row, values = self._existing(record)
        validate_campaign_transition(CampaignPreparationStatus(row.status), CampaignPreparationStatus(values.status))
        if (row.name, row.objective) != (values.name, values.objective):
            raise ValueError("Transition cannot change metadata")
        row.status, row.updated_at = values.status, values.updated_at
        self.session.flush()

    def _existing(self, record):
        values = campaign_to_orm(record)
        row = self.session.get(QACampaignRow, str(record.id))
        if row is None:
            raise KeyError(record.id)
        if (row.project_id, row.created_at) != (values.project_id, values.created_at):
            raise ValueError("Campaign ownership and identity are immutable")
        return row, values
