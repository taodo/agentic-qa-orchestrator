"""Detached bounded operational reads; persisted QA results remain authoritative."""
from pydantic import Field, model_validator
from qa_sentinel.domain.qa_run import QARun, QARunTest, MAX_SNAPSHOT_RECORDS
from qa_sentinel.domain.qa_run_evidence import QARunEvidence, MAX_TEST_EVIDENCE
from .models import View, CollectionPage
from qa_sentinel.domain.evidence_variants import EvidencePresentation, evidence_policy


class QARunResultSummary(View):
    total: int = Field(ge=0, le=MAX_SNAPSHOT_RECORDS)
    completed: int = Field(ge=0, le=MAX_SNAPSHOT_RECORDS)
    passed: int = Field(ge=0, le=MAX_SNAPSHOT_RECORDS)
    failed: int = Field(ge=0, le=MAX_SNAPSHOT_RECORDS)
    skipped: int = Field(ge=0, le=MAX_SNAPSHOT_RECORDS)
    not_evaluated: int = Field(ge=0, le=MAX_SNAPSHOT_RECORDS)
    remaining: int = Field(ge=0, le=MAX_SNAPSHOT_RECORDS)

    @model_validator(mode="after")
    def consistent_counts(self):
        if (self.total != self.completed + self.remaining or
                self.completed != self.passed + self.failed + self.skipped or
                self.remaining != self.not_evaluated):
            raise ValueError("Inconsistent persisted Run result counts")
        return self


class QARunEvidenceView(QARunEvidence):
    """Read-only policy projection; never stored or accepted as executor input."""
    presentation: EvidencePresentation

    @classmethod
    def from_record(cls, record):
        return cls(**record.model_dump(),
            presentation=evidence_policy(record.payload).presentation(record.payload))


def evidence_page(records, limit):
    items = tuple(QARunEvidenceView.from_record(record) for record in records[:limit])
    return CollectionPage[QARunEvidenceView](items=items, total_returned=len(items), truncated=len(records) > limit)


class QARunTestResult(QARunTest):
    evidence_count: int = Field(ge=0, le=MAX_TEST_EVIDENCE)
    evidence: CollectionPage[QARunEvidenceView]


class QARunResults(View):
    run: QARun
    summary: QARunResultSummary
    tests: CollectionPage[QARunTestResult]

    @model_validator(mode="after")
    def complete_snapshot_count(self):
        if self.summary.total != self.run.test_count:
            raise ValueError("Persisted tests do not match Run snapshot count")
        return self
