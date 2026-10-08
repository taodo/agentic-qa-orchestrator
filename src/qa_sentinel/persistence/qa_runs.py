"""Immutable Run snapshots with narrow lifecycle updates in reserved transactions."""
from .preparation_current import current_requirement,current_test
from sqlalchemy import select, func, update
from qa_sentinel.domain.qa_run_lifecycle import start_run, start_test, finish_test, finish_run, RunLifecycleError
from qa_sentinel.domain.qa_run import (QARun, QARunRequirement, QARunTest, PreparedQARun,
    MAX_SNAPSHOT_RECORDS, SnapshotSizeError)
from .models import (QARunRow, QARunRequirementRow, QARunTestRow,
    CampaignRequirementRow, TestSpecificationRow)
from .campaign_content import requirement_from, row_values
from .test_specifications import TestSpecificationRepository


def from_row(row, contract):
    return contract.model_validate({name: getattr(row, name) for name in contract.model_fields})


class QARunRepository:
    def __init__(self, session):
        self.session = session

    def get(self, project_id, campaign_id, run_id):
        row = self.session.scalar(select(QARunRow).where(QARunRow.id == str(run_id),
            QARunRow.project_id == str(project_id), QARunRow.campaign_id == str(campaign_id)))
        return None if row is None else from_row(row, QARun)

    def exists_in_project(self, project_id, run_id):
        # Metadata-only mismatch check, never disclosing a foreign Project's Run.
        return self.session.scalar(select(QARunRow.id).where(
            QARunRow.project_id == str(project_id), QARunRow.id == str(run_id))) is not None

    def by_key(self, project_id, campaign_id, key):
        row = self.session.scalar(select(QARunRow).where(QARunRow.project_id == str(project_id),
            QARunRow.campaign_id == str(campaign_id), QARunRow.idempotency_key == key))
        return None if row is None else from_row(row, QARun)

    def next_number(self, campaign_id):
        # MAX+1 is safe only inside the caller's BEGIN IMMEDIATE reservation;
        # the campaign/number DB unique constraint is the final guard.
        return self.session.scalar(select(func.coalesce(func.max(QARunRow.run_number), 0)).where(
            QARunRow.campaign_id == str(campaign_id))) + 1

    def approved_content(self, project_id, campaign_id):
        records = []
        for table in (CampaignRequirementRow, TestSpecificationRow):
            rows = list(self.session.scalars(select(table).where(table.project_id == str(project_id),
                table.campaign_id == str(campaign_id), table.review_status == "APPROVED",
                current_requirement() if table is CampaignRequirementRow else current_test())
                .order_by(table.logical_key, table.id).limit(MAX_SNAPSHOT_RECORDS + 1)))
            if len(rows) > MAX_SNAPSHOT_RECORDS:
                raise SnapshotSizeError()
            records.append(rows)
        return ([requirement_from(r) for r in records[0]],
                TestSpecificationRepository(self.session)._specs(records[1]))

    def add(self, prepared):
        prepared = PreparedQARun.model_validate(prepared.model_dump())
        run = prepared.run
        if run.execution_status != "CREATED" or run.qa_outcome != "NOT_EVALUATED" or run.started_at or run.completed_at:
            raise ValueError("Run creation cannot execute")
        if any(t.execution_status != "NOT_STARTED" or t.qa_result != "NOT_EVALUATED" for t in prepared.tests):
            raise ValueError("Run creation cannot evaluate tests")
        self.session.add(QARunRow(**row_values(run)))
        for entries, table in ((prepared.requirements, QARunRequirementRow), (prepared.tests, QARunTestRow)):
            for entry in entries:
                self.session.add(table(**entry.model_dump(mode="json"), project_id=str(run.project_id), campaign_id=str(run.campaign_id)))
        self.session.flush()

    @staticmethod
    def _limit(limit):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Invalid Run list limit")
        return limit + 1

    def list(self, project_id, campaign_id, limit):
        return [from_row(r, QARun) for r in self.session.scalars(select(QARunRow).where(
            QARunRow.project_id == str(project_id), QARunRow.campaign_id == str(campaign_id))
            .order_by(QARunRow.run_number.desc()).limit(self._limit(limit)))]

    def entries(self, run, kind, limit, after_position):
        # Keyset pagination permits reconstruction without unbounded detail fan-out.
        table, contract = (QARunTestRow, QARunTest) if kind == "tests" else (QARunRequirementRow, QARunRequirement)
        return [from_row(r, contract) for r in self.session.scalars(select(table).where(
            table.run_id == str(run.id), table.project_id == str(run.project_id), table.campaign_id == str(run.campaign_id),
            table.position > after_position).order_by(table.position).limit(self._limit(limit)))]

    def all_entries(self, run, kind):
        table, contract = (QARunTestRow, QARunTest) if kind == "tests" else (QARunRequirementRow, QARunRequirement)
        rows = self.session.scalars(select(table).where(table.run_id == str(run.id),
            table.project_id == str(run.project_id), table.campaign_id == str(run.campaign_id))
            .order_by(table.position).limit(MAX_SNAPSHOT_RECORDS + 1))
        entries = tuple(from_row(r, contract) for r in rows)
        if len(entries) > MAX_SNAPSHOT_RECORDS:
            raise SnapshotSizeError()
        return entries

    def preparation(self, run):
        return PreparedQARun(run=run, requirements=self.all_entries(run, "requirements"), tests=self.all_entries(run, "tests"))

    def test(self, run, id):
        row = self.session.scalar(select(QARunTestRow).where(QARunTestRow.id == str(id),
            QARunTestRow.run_id == str(run.id), QARunTestRow.project_id == str(run.project_id), QARunTestRow.campaign_id == str(run.campaign_id)))
        if row is None:
            raise RunLifecycleError("RUN_INVALID_STATE")
        return from_row(row, QARunTest)

    def _save_run_state(self, before, after):
        changed = self.session.execute(update(QARunRow).where(QARunRow.id == str(before.id),
            QARunRow.project_id == str(before.project_id), QARunRow.campaign_id == str(before.campaign_id),
            QARunRow.execution_status == before.execution_status).values(**after.model_dump(
                include={"execution_status", "qa_outcome", "started_at", "completed_at", "execution_error_code"})))
        if changed.rowcount != 1:
            raise RunLifecycleError("RUN_INVALID_STATE")
        return after

    def start(self, run):
        return self._save_run_state(run, start_run(run))

    def finish(self, run, *, failed=False):
        return self._save_run_state(run, finish_run(run, self.all_entries(run, "tests"), failed=failed))

    def _save_test_state(self, run, before, after):
        if run.execution_status != "RUNNING":
            raise RunLifecycleError("RUN_INVALID_STATE")
        changed = self.session.execute(update(QARunTestRow).where(QARunTestRow.id == str(before.id),
            QARunTestRow.run_id == str(run.id), QARunTestRow.project_id == str(run.project_id), QARunTestRow.campaign_id == str(run.campaign_id),
            QARunTestRow.execution_status == before.execution_status, QARunTestRow.qa_result == before.qa_result)
            .values(execution_status=after.execution_status, qa_result=after.qa_result))
        if changed.rowcount != 1:
            raise RunLifecycleError("RUN_INVALID_STATE")
        return after

    def start_test(self, run, test):
        return self._save_test_state(run, test, start_test(test))

    def complete_test(self, run, test, result):
        return self._save_test_state(run, test, finish_test(test, result))
