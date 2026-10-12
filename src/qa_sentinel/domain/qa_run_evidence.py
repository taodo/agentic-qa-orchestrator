"""Generic bounded result/evidence envelope with closed variant policy dispatch."""
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4
from pydantic import Field, AwareDatetime, StringConstraints, model_validator
from .campaign_content import Frozen
from .qa_run import QAResult, canonical_json
from .evidence_variants import (
    EvidencePayload, evidence_policy, parse_payload,
    MAX_TEST_EVIDENCE, EVIDENCE_PREVIEW_LIMIT, MAX_EVIDENCE_BYTES,
    MAX_EVIDENCE_SUMMARY_CHARS, MAX_EVIDENCE_IDENTITY_CHARS, EVIDENCE_SCHEMA_VERSION, OBSERVATION_KIND,
)


class EvidenceDraft(Frozen):
    schema_version: Literal["qa-run-evidence-v1"] = EVIDENCE_SCHEMA_VERSION
    kind: Literal["EXECUTION_OBSERVATION"] = OBSERVATION_KIND
    source: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=MAX_EVIDENCE_IDENTITY_CHARS, pattern=r"^[a-z][a-z0-9_-]*$")]
    payload: EvidencePayload
    summary: str = Field(min_length=1, max_length=MAX_EVIDENCE_SUMMARY_CHARS, strict=True)

    @model_validator(mode="before")
    @classmethod
    def registered_payload(cls, data):
        if isinstance(data, dict):
            data = {**data, "payload": parse_payload(data.get("source"),
                data.get("schema_version", EVIDENCE_SCHEMA_VERSION),
                data.get("kind", OBSERVATION_KIND), data.get("payload"))}
        return data

    @model_validator(mode="after")
    def safe_payload(self):
        if len(canonical_json(self.payload.model_dump(mode="json"))) > MAX_EVIDENCE_BYTES:
            raise ValueError("Evidence payload exceeds safety bound")
        policy = evidence_policy(self.payload)
        policy.validate_identity(self.source, self.schema_version, self.kind)
        policy.validate_envelope(self.payload, self.summary)
        return self

    def validate_snapshot(self, snapshot):
        evidence_policy(self.payload).validate_snapshot(self.payload, snapshot)


class QARunEvidence(EvidenceDraft):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    campaign_id: UUID
    run_id: UUID
    run_test_id: UUID
    sequence: int = Field(ge=1, le=MAX_TEST_EVIDENCE, strict=True)
    recorded_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TestExecutionResult(Frozen):
    qa_result: QAResult
    evidence: tuple[EvidenceDraft, ...] = Field(min_length=1, max_length=MAX_TEST_EVIDENCE)

    @model_validator(mode="after")
    def completed_result(self):
        if self.qa_result == "NOT_EVALUATED":
            raise ValueError("Execution result must be completed")
        for draft in self.evidence:
            evidence_policy(draft.payload).validate_result(draft.payload, self.qa_result)
        return self
