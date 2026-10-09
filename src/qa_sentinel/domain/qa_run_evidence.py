"""Bounded executor-neutral result/evidence envelope; only synthetic payloads admitted today."""
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4
from pydantic import Field, AwareDatetime, StringConstraints, model_validator
from .campaign_content import Frozen
from .qa_run import QAResult, MAX_SNAPSHOT_RECORDS, canonical_json

MAX_TEST_EVIDENCE = 20
EVIDENCE_PREVIEW_LIMIT = 5
MAX_EVIDENCE_BYTES = 2048


class SyntheticObservation(Frozen):
    strategy: Literal["synthetic-position-v1"] = "synthetic-position-v1"
    position: int = Field(ge=1, le=MAX_SNAPSHOT_RECORDS, strict=True)
    outcome: Literal["PASS", "FAIL", "SKIP"]

    def safe_summary(self):
        return f"Synthetic fixture position {self.position}: {self.outcome}. No external target was tested."


class EvidenceDraft(Frozen):
    schema_version: Literal["qa-run-evidence-v1"] = "qa-run-evidence-v1"
    kind: Literal["EXECUTION_OBSERVATION"] = "EXECUTION_OBSERVATION"
    source: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")] = "synthetic"
    payload: SyntheticObservation
    summary: str = Field(min_length=1, max_length=512, strict=True)

    @model_validator(mode="after")
    def safe_payload(self):
        # No arbitrary text/environment/paths/headers: a closed typed observation
        # plus an exact generated summary. Later executors must add explicit schemas.
        if self.source != "synthetic" or self.summary != self.payload.safe_summary() or len(canonical_json(self.payload.model_dump(mode="json"))) > MAX_EVIDENCE_BYTES:
            raise ValueError("Invalid bounded evidence")
        return self


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
        if self.qa_result == "NOT_EVALUATED" or any(e.payload.outcome != self.qa_result for e in self.evidence):
            raise ValueError("Evidence must describe the accepted completed result")
        return self
