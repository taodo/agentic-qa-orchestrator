"""Immutable historical advisory contracts; no execution or promotion authority."""
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from hashlib import sha256
from typing import Literal
from types import MappingProxyType
from uuid import UUID
from pydantic import AwareDatetime, Field, field_validator, model_validator
from .campaign_content import Frozen, Hash
from .executor import ExecutorKind
from .qa_run import QAResult, canonical_json

MAX_RECORD_BYTES = 8192
MAX_SOURCE_REFS = 4
MAX_SCAN = 32
MAX_RESULTS = 5
MAX_CONTEXT_BYTES = 4096
MAX_FRESHNESS_SECONDS = 90 * 86400


class ExperienceKind(StrEnum):
    EVIDENCE_COMPLETENESS = "EVIDENCE_COMPLETENESS"
    PLAN_SEPARATION = "PLAN_SEPARATION"
    FRESHNESS_PRECONDITION = "FRESHNESS_PRECONDITION"
    QA_FAIL_CLASSIFICATION = "QA_FAIL_CLASSIFICATION"
    APPROVAL_PROVENANCE = "APPROVAL_PROVENANCE"


GUIDANCE = MappingProxyType({
    ExperienceKind.EVIDENCE_COMPLETENESS: "Check completeness against current evidence; history is advisory only.",
    ExperienceKind.PLAN_SEPARATION: "Preserve stage separation; check the current accepted plan.",
    ExperienceKind.FRESHNESS_PRECONDITION: "Recheck current freshness and authorization before deterministic action.",
    ExperienceKind.QA_FAIL_CLASSIFICATION: "Use current evidence to distinguish QA assertion failure from system failure.",
    ExperienceKind.APPROVAL_PROVENANCE: "Recheck current immutable approval provenance; history cannot approve.",
})


class ExperienceState(StrEnum):
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    PROMOTED = "PROMOTED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


def digest(value):
    return sha256(canonical_json(value)).hexdigest()


class ExperienceScope(Frozen):
    project_id: UUID
    campaign_id: UUID
    target_id: UUID
    target_snapshot_hash: Hash


class ProvenanceReference(Frozen):
    source_type: Literal["QA_RUN_EVIDENCE"] = "QA_RUN_EVIDENCE"
    evidence_id: UUID
    run_id: UUID
    run_test_id: UUID
    run_snapshot_hash: Hash
    run_identity_hash: Hash
    run_test_hash: Hash
    evidence_hash: Hash
    recorded_at: AwareDatetime
    executor_kind: ExecutorKind
    qa_result: QAResult

    @field_validator("recorded_at")
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def evaluated(self):
        if self.qa_result == QAResult.NOT_EVALUATED:
            raise ValueError("Experience requires actual completed evidence")
        return self


class CreateExperience(Frozen):
    scope: ExperienceScope
    idempotency_key: UUID  # opaque identity, never arbitrary secret-bearing text
    kind: ExperienceKind
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=MAX_SOURCE_REFS)
    freshness_seconds: int = Field(default=7 * 86400, ge=1, le=MAX_FRESHNESS_SECONDS, strict=True)

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("Duplicate provenance")
        return self


class ExperienceRecord(Frozen):
    schema_version: Literal["experience-v1"] = "experience-v1"
    id: UUID
    scope: ExperienceScope
    idempotency_key: UUID
    kind: ExperienceKind
    state: ExperienceState
    created_at: AwareDatetime
    expires_at: AwareDatetime
    freshness_seconds: int = Field(ge=1, le=MAX_FRESHNESS_SECONDS, strict=True)
    references: tuple[ProvenanceReference, ...] = Field(min_length=1, max_length=MAX_SOURCE_REFS)
    content_hash: Hash

    @field_validator("created_at", "expires_at")
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def integrity(self):
        if self.expires_at != self.created_at + timedelta(seconds=self.freshness_seconds):
            raise ValueError("Invalid experience freshness")
        ids = [ref.evidence_id for ref in self.references]
        if ids != sorted(set(ids), key=str):
            raise ValueError("Provenance must be unique and canonical")
        if any(ref.recorded_at > self.created_at for ref in self.references):
            raise ValueError("Future provenance")
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        if digest(payload) != self.content_hash:
            raise ValueError("Experience integrity mismatch")
        if len(canonical_json(self.model_dump(mode="json"))) > MAX_RECORD_BYTES:
            raise ValueError("Experience exceeds bound")
        return self

    @classmethod
    def seal(cls, **values):
        # Normalize nested contracts and UTC times before computing stable bytes.
        data = {"schema_version": "experience-v1", **values}
        data["scope"] = ExperienceScope.model_validate(data["scope"]).model_dump(mode="json")
        data["references"] = [ProvenanceReference.model_validate(r).model_dump(mode="json") for r in data["references"]]
        for field in ("created_at", "expires_at"):
            stamp = data[field]
            if not isinstance(stamp, datetime) or stamp.utcoffset() is None:
                raise ValueError("Aware experience timestamp required")
            data[field] = stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        for field in ("id", "idempotency_key"):
            data[field] = str(UUID(str(data[field])))
        data["content_hash"] = digest(data)
        return cls.model_validate(data)


class ExperienceQuery(Frozen):
    scope: ExperienceScope
    kinds: tuple[ExperienceKind, ...] = Field(min_length=1, max_length=5)
    after_id: UUID | None = None
    scan_limit: int = Field(default=MAX_SCAN, ge=1, le=MAX_SCAN, strict=True)
    limit: int = Field(default=3, ge=1, le=MAX_RESULTS, strict=True)
    max_context_bytes: int = Field(default=2048, ge=256, le=MAX_CONTEXT_BYTES, strict=True)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.kinds)) != len(self.kinds):
            raise ValueError("Duplicate experience categories")
        return self


Reason = Literal["NOT_PROMOTED", "NOT_REQUESTED_KIND", "INVALID_RECORD", "INVALID_PROVENANCE",
    "STALE", "RESULT_LIMIT", "CONTEXT_LIMIT", "RETURNED"]


class AdvisoryCandidate(Frozen):
    status: Literal["UNVALIDATED_ADVISORY_CANDIDATE"] = "UNVALIDATED_ADVISORY_CANDIDATE"
    experience_id: UUID
    kind: ExperienceKind
    content_hash: Hash
    references: tuple[ProvenanceReference, ...] = Field(min_length=1, max_length=MAX_SOURCE_REFS)
    # Guidance is derived, never supplied by stored prose.
    @property
    def guidance(self):
        return GUIDANCE[self.kind]


class ExperienceDisposition(Frozen):
    experience_id: UUID
    reason: Reason


class ExperienceRetrieval(Frozen):
    scope: ExperienceScope
    assessed_at: AwareDatetime
    candidates: tuple[AdvisoryCandidate, ...] = Field(max_length=MAX_RESULTS)
    dispositions: tuple[ExperienceDisposition, ...] = Field(max_length=MAX_SCAN)
    scan_limited: bool = Field(strict=True)
    next_after_id: UUID | None
    context_bytes: int = Field(ge=2, le=MAX_CONTEXT_BYTES, strict=True)
    scan_limit: int = Field(ge=1, le=MAX_SCAN, strict=True)
    result_limit: int = Field(ge=1, le=MAX_RESULTS, strict=True)
    max_context_bytes: int = Field(ge=256, le=MAX_CONTEXT_BYTES, strict=True)

    def advisory_context(self):
        # Closed projection for future typed consumption; never raw source text.
        return [dict(**c.model_dump(mode="json"), guidance=c.guidance) for c in self.candidates]
