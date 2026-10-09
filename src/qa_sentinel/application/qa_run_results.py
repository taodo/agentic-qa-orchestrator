"""Detached bounded operational reads; persisted QA results remain authoritative."""
from pydantic import Field, model_validator
from qa_sentinel.domain.qa_run import QARun, QARunTest, MAX_SNAPSHOT_RECORDS
from qa_sentinel.domain.qa_run_evidence import QARunEvidence, MAX_TEST_EVIDENCE
from .models import View, CollectionPage


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


class QARunTestResult(QARunTest):
    evidence_count: int = Field(ge=0, le=MAX_TEST_EVIDENCE)
    evidence: CollectionPage[QARunEvidence]


class QARunResults(View):
    run: QARun
    summary: QARunResultSummary
    tests: CollectionPage[QARunTestResult]

    @model_validator(mode="after")
    def complete_snapshot_count(self):
        if self.summary.total != self.run.test_count:
            raise ValueError("Persisted tests do not match Run snapshot count")
        return self
