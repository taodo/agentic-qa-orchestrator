"""Bounded Experience storage and provenance from real persisted QA records."""
from sqlalchemy import select
from qa_sentinel.domain.experience import (ExperienceRecord, ExperienceState,
    ProvenanceReference, MAX_SOURCE_REFS, digest)
from qa_sentinel.domain.qa_run import QARun, QARunTest
from qa_sentinel.domain.qa_run_evidence import QARunEvidence
from .qa_runs import from_row
from .models import ExperienceRow, ExperienceSourceRow, QARunRow, QARunTestRow, QARunEvidenceRow


class ExperienceRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def record(row):
        record = ExperienceRecord.model_validate(row.payload)
        columns = dict(id=record.id, **record.scope.model_dump(), idempotency_key=record.idempotency_key,
            state=record.state, kind=record.kind, content_hash=record.content_hash,
            created_at=record.created_at, expires_at=record.expires_at,
            freshness_seconds=record.freshness_seconds)
        if any(getattr(row, field) != (str(value) if field in {
                "id", "project_id", "campaign_id", "target_id", "idempotency_key"} else value)
                for field, value in columns.items()):
            raise ValueError("Experience storage mismatch")
        return record

    def by_key(self, scope, key):
        row = self.session.scalar(select(ExperienceRow).where(
            ExperienceRow.project_id == str(scope.project_id),
            ExperienceRow.campaign_id == str(scope.campaign_id),
            ExperienceRow.idempotency_key == str(key)))
        return None if row is None else self.record(row)

    def get(self, scope, record_id):
        row = self.session.scalar(select(ExperienceRow).where(
            *self._scope(scope), ExperienceRow.id == str(record_id)))
        return None if row is None else self.record(row)

    @staticmethod
    def _scope(scope):
        return [getattr(ExperienceRow, name) == str(value) for name, value in scope.model_dump().items()]

    def window(self, query):
        # Overflow probe reads identity only, never a 33rd payload/source record.
        ids = list(self.session.scalars(select(ExperienceRow.id).where(*self._scope(query.scope),
            ExperienceRow.id > (str(query.after_id) if query.after_id else ""))
            .order_by(ExperienceRow.id).limit(query.scan_limit + 1)))
        selected = ids[:query.scan_limit]
        rows = list(self.session.scalars(select(ExperienceRow).where(
            *self._scope(query.scope), ExperienceRow.id.in_(selected)).order_by(ExperienceRow.id)))
        return rows, len(ids) > query.scan_limit

    def add_candidate(self, record):
        record = ExperienceRecord.model_validate(record.model_dump())
        if record.state != ExperienceState.CANDIDATE:
            raise ValueError("Only candidate creation is available")
        self.session.add(ExperienceRow(id=str(record.id),
            **{k:str(v) for k,v in record.scope.model_dump().items()},
            idempotency_key=str(record.idempotency_key), kind=record.kind, state=record.state,
            content_hash=record.content_hash, created_at=record.created_at, expires_at=record.expires_at,
            freshness_seconds=record.freshness_seconds, payload=record.model_dump(mode="json")))
        self.session.flush()
        for position, ref in enumerate(record.references, 1):
            self.session.add(ExperienceSourceRow(experience_id=str(record.id), position=position,
                project_id=str(record.scope.project_id), campaign_id=str(record.scope.campaign_id),
                evidence_id=str(ref.evidence_id), run_id=str(ref.run_id), run_test_id=str(ref.run_test_id)))
        self.session.flush()

    def source_rows_match(self, record):
        rows = list(self.session.scalars(select(ExperienceSourceRow).where(
            ExperienceSourceRow.experience_id == str(record.id)).order_by(ExperienceSourceRow.position)
            .limit(MAX_SOURCE_REFS + 1)))
        expected = [(position, str(record.scope.project_id), str(record.scope.campaign_id),
            str(ref.evidence_id), str(ref.run_id), str(ref.run_test_id))
            for position, ref in enumerate(record.references, 1)]
        actual = [(r.position, r.project_id, r.campaign_id, r.evidence_id, r.run_id, r.run_test_id) for r in rows]
        return actual == expected

    def bind_source(self, scope, evidence_id, *, as_of):
        # One exact-owner join; no full Run scan or source/repository/network access.
        evidence, test, run = QARunEvidenceRow, QARunTestRow, QARunRow
        rows = self.session.execute(select(evidence, test, run)
            .join(test, (evidence.run_test_id == test.id) & (evidence.run_id == test.run_id)
                & (evidence.campaign_id == test.campaign_id) & (evidence.project_id == test.project_id))
            .join(run, (test.run_id == run.id) & (test.campaign_id == run.campaign_id)
                & (test.project_id == run.project_id))
            .where(evidence.id == str(evidence_id), evidence.project_id == str(scope.project_id),
                evidence.campaign_id == str(scope.campaign_id))).one_or_none()
        if rows is None:
            raise ValueError("Missing scoped provenance")
        e = from_row(rows[0], QARunEvidence)
        r = from_row(rows[2], QARun)
        t = from_row(rows[1], QARunTest, snapshot_version=r.snapshot_version)
        if (r.target_snapshot is None or r.target_snapshot.target_id != scope.target_id
                or r.target_snapshot.project_id != scope.project_id
                or digest(r.target_snapshot.model_dump(mode="json")) != scope.target_snapshot_hash
                or r.execution_status not in {"COMPLETED", "FAILED", "STOPPED"}
                or r.started_at is None or r.completed_at is None
                or not r.created_at <= r.started_at <= e.recorded_at <= r.completed_at <= as_of
                or t.execution_status != "COMPLETED"):
            raise ValueError("Invalid historical source")
        e.validate_snapshot(t)
        from qa_sentinel.domain.evidence_variants import evidence_policy
        policy = evidence_policy(e.payload)
        policy.validate_result(e.payload, t.qa_result)
        if policy.executor_kind != r.executor_kind:
            raise ValueError("Source executor mismatch")
        return ProvenanceReference(evidence_id=e.id, run_id=r.id, run_test_id=t.id,
            run_snapshot_hash=r.snapshot_hash,
            run_identity_hash=digest(r.model_dump(mode="json", exclude={"execution_status", "qa_outcome",
                "started_at", "completed_at", "execution_error_code", "browser_error_code"})),
            run_test_hash=digest(t.model_dump(mode="json", exclude={"execution_status", "qa_result"})),
            evidence_hash=digest(e.model_dump(mode="json")), recorded_at=e.recorded_at,
            executor_kind=r.executor_kind, qa_result=t.qa_result)
