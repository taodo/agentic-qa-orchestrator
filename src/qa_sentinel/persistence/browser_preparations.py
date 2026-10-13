"""Bounded detached preparation reads and compare-and-swap lifecycle writes."""
from sqlalchemy import select, update
from .models import BrowserPreparationRow, QARunRow
from qa_sentinel.domain.browser_preparation import (BrowserPreparation, BrowserPreparationView,
    PreparationError, start_preparation, start_item, finish_item, finish_preparation)


class BrowserPreparationRepository:
    def __init__(self, session):
        self.session = session

    def get(self, project_id, campaign_id, id):
        row = self.session.scalar(select(BrowserPreparationRow).where(
            BrowserPreparationRow.id == str(id), BrowserPreparationRow.project_id == str(project_id),
            BrowserPreparationRow.campaign_id == str(campaign_id)))
        return None if row is None else BrowserPreparation.model_validate(row.payload)

    def by_key(self, project_id, campaign_id, key):
        row = self.session.scalar(select(BrowserPreparationRow).where(
            BrowserPreparationRow.project_id == str(project_id), BrowserPreparationRow.campaign_id == str(campaign_id),
            BrowserPreparationRow.idempotency_key == key))
        return None if row is None else BrowserPreparation.model_validate(row.payload)

    def add(self, record):
        record = BrowserPreparation.model_validate(record.model_dump())
        if record.status != "CREATED":
            raise PreparationError("PREPARATION_INVALID_STATE")
        values = record.model_dump(mode="json", include={"id", "project_id", "campaign_id", "contract_version", "browser_mode", "idempotency_key", "selection_hash", "selected_count", "status"})
        self.session.add(BrowserPreparationRow(**values, target_id=str(record.target_snapshot.target_id),
            created_at=record.created_at, payload=record.model_dump(mode="json")))
        self.session.flush()
        return record

    def view(self, record):
        run_id = self.session.scalar(select(QARunRow.id).where(QARunRow.preparation_id == str(record.id),
            QARunRow.project_id == str(record.project_id), QARunRow.campaign_id == str(record.campaign_id)))
        return BrowserPreparationView(**record.model_dump(), resulting_run_id=run_id)

    def transition(self, before, action, **arguments):
        functions = {"START": start_preparation, "START_ITEM": start_item, "FINISH_ITEM": finish_item, "FINISH": finish_preparation}
        if action not in functions:
            raise PreparationError("PREPARATION_INVALID_STATE")
        after = functions[action](before, **arguments)
        changed = self.session.execute(update(BrowserPreparationRow).where(
            BrowserPreparationRow.id == str(before.id), BrowserPreparationRow.project_id == str(before.project_id),
            BrowserPreparationRow.campaign_id == str(before.campaign_id), BrowserPreparationRow.status == before.status,
            BrowserPreparationRow.payload == before.model_dump(mode="json"))
            .values(status=after.status, payload=after.model_dump(mode="json")))
        if changed.rowcount != 1:
            raise PreparationError("PREPARATION_INVALID_STATE")
        return after
