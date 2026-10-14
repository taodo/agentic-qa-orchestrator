"""Dormant, provider-neutral creation/retrieval; no promotion or workflow wiring."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from pydantic import AwareDatetime, TypeAdapter
from sqlalchemy.exc import SQLAlchemyError
from qa_sentinel.domain.experience import (CreateExperience, ExperienceQuery, ExperienceRecord,
    ExperienceRetrieval, AdvisoryCandidate, ExperienceDisposition, ExperienceState)
from qa_sentinel.domain.qa_run import canonical_json
from qa_sentinel.persistence.unit_of_work import UnitOfWork


class ExperienceError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)  # never raw SQL/input/source/provider exception text


class ExperienceService:
    def __init__(self, session_factory, *, clock=None):
        self.session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self):
        try:
            return TypeAdapter(AwareDatetime).validate_python(self._clock()).astimezone(timezone.utc)
        except (ValueError, TypeError):
            raise ExperienceError("EXPERIENCE_INVALID_CLOCK") from None

    @staticmethod
    def _validate(contract, value):
        try:
            return contract.model_validate(value.model_dump() if isinstance(value, contract) else value)
        except (ValueError, TypeError):
            raise ExperienceError("EXPERIENCE_INVALID_INPUT") from None

    @staticmethod
    def _scope(uow, scope):
        campaign = uow.campaigns.get(scope.campaign_id)
        if (campaign is None or campaign.project_id != scope.project_id
                or uow.targets.get(scope.project_id, scope.target_id) is None):
            raise ExperienceError("EXPERIENCE_SCOPE_NOT_FOUND")
        # A historic captured Target need not remain the Campaign's live association.

    def create(self, command):
        command = self._validate(CreateExperience, command)
        now = self._now()
        try:
            with UnitOfWork(self.session_factory) as uow:
                uow.session.connection(execution_options={"qa_job_write": True})
                self._scope(uow, command.scope)
                existing = uow.experiences.by_key(command.scope, command.idempotency_key)
                if existing is not None:
                    if (existing.scope != command.scope or existing.kind != command.kind
                            or existing.freshness_seconds != command.freshness_seconds
                            or tuple(r.evidence_id for r in existing.references) != tuple(sorted(command.evidence_ids, key=str))):
                        raise ExperienceError("EXPERIENCE_IDEMPOTENCY_CONFLICT")
                    self._provenance(uow, existing, now)
                    return existing
                refs = tuple(uow.experiences.bind_source(command.scope, id, as_of=now)
                    for id in sorted(command.evidence_ids, key=str))
                if any(not 0 <= (now-ref.recorded_at).total_seconds() < command.freshness_seconds for ref in refs):
                    raise ExperienceError("EXPERIENCE_STALE_SOURCE")
                record = ExperienceRecord.seal(id=uuid4(), scope=command.scope,
                    idempotency_key=command.idempotency_key, kind=command.kind, state=ExperienceState.CANDIDATE,
                    created_at=now, expires_at=now+timedelta(seconds=command.freshness_seconds),
                    freshness_seconds=command.freshness_seconds, references=refs)
                uow.experiences.add_candidate(record)
                uow.commit()
                return record
        except ExperienceError:
            raise
        except (ValueError, TypeError):
            raise ExperienceError("EXPERIENCE_INVALID_PROVENANCE") from None
        except SQLAlchemyError:
            raise ExperienceError("EXPERIENCE_PERSISTENCE_ERROR") from None

    @staticmethod
    def _provenance(uow, record, now):
        if not uow.experiences.source_rows_match(record):
            raise ValueError("Source binding mismatch")
        for ref in record.references:
            if uow.experiences.bind_source(record.scope, ref.evidence_id, as_of=now) != ref:
                raise ValueError("Source content mismatch")

    def get(self, scope, record_id):
        from qa_sentinel.domain.experience import ExperienceScope
        scope = self._validate(ExperienceScope, scope)
        now = self._now()
        try:
            record_id = UUID(str(record_id))
        except (ValueError, TypeError):
            raise ExperienceError("EXPERIENCE_INVALID_INPUT") from None
        try:
            with UnitOfWork(self.session_factory) as uow:
                self._scope(uow, scope)
                record = uow.experiences.get(scope, record_id)
                if record is None:
                    raise ExperienceError("EXPERIENCE_NOT_FOUND")
                self._provenance(uow, record, now)
                return record
        except ExperienceError:
            raise
        except (ValueError, TypeError):
            raise ExperienceError("EXPERIENCE_INVALID_PROVENANCE") from None
        except SQLAlchemyError:
            raise ExperienceError("EXPERIENCE_PERSISTENCE_ERROR") from None

    def retrieve(self, query):
        query = self._validate(ExperienceQuery, query)
        now = self._now()
        candidates, dispositions = [], []
        context_bytes = len(canonical_json([]))
        try:
            with UnitOfWork(self.session_factory) as uow:
                self._scope(uow, query.scope)
                rows, scan_limited = uow.experiences.window(query)
                for row in rows:
                    reason = None
                    try:
                        record = uow.experiences.record(row)
                    except (ValueError, TypeError):
                        reason = "INVALID_RECORD"
                    if reason is None:
                        if record.state != ExperienceState.PROMOTED:
                            reason = "NOT_PROMOTED"
                        elif record.kind not in query.kinds:
                            reason = "NOT_REQUESTED_KIND"
                        elif (not record.created_at <= now < record.expires_at
                                or any(not 0 <= (now-r.recorded_at).total_seconds() < record.freshness_seconds
                                    for r in record.references)):
                            reason = "STALE"
                        else:
                            try:
                                self._provenance(uow, record, now)
                            except (ValueError, TypeError):
                                reason = "INVALID_PROVENANCE"
                    if reason is None:
                        candidate = AdvisoryCandidate(experience_id=record.id, kind=record.kind,
                            content_hash=record.content_hash, references=record.references)
                        size = len(canonical_json([dict(**c.model_dump(mode="json"), guidance=c.guidance)
                            for c in (*candidates, candidate)]))
                        if len(candidates) >= query.limit:
                            reason = "RESULT_LIMIT"
                        elif size > query.max_context_bytes:
                            reason = "CONTEXT_LIMIT"
                        else:
                            candidates.append(candidate)
                            context_bytes = size
                            reason = "RETURNED"
                    dispositions.append(ExperienceDisposition(experience_id=row.id, reason=reason))
                return ExperienceRetrieval(scope=query.scope, assessed_at=now, candidates=tuple(candidates),
                    dispositions=tuple(dispositions), scan_limited=scan_limited,
                    next_after_id=rows[-1].id if scan_limited and rows else None,
                    context_bytes=context_bytes, scan_limit=query.scan_limit, result_limit=query.limit,
                    max_context_bytes=query.max_context_bytes)
        except ExperienceError:
            raise
        except (ValueError, TypeError):
            raise ExperienceError("EXPERIENCE_INVALID_PROVENANCE") from None
        except SQLAlchemyError:
            raise ExperienceError("EXPERIENCE_PERSISTENCE_ERROR") from None
