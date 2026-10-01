"""Separate deterministic test evidence provider. No commands or classification."""
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict
from qa_sentinel.agents.base import TestContext
from qa_sentinel.agents.fake import ScenarioExhaustedError
from qa_sentinel.domain.test_run import TestRun
from qa_sentinel.domain.enums import TestExecutionStatus, TestOutcome
from qa_sentinel.domain.types import Count
from qa_sentinel.orchestration.reliability_policy import FailureIdentity
from .base import TestResultProvider


class FakeTestResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    execution_status: TestExecutionStatus = TestExecutionStatus.COMPLETED
    outcome: TestOutcome
    passed_count: Count = 0
    failed_count: Count = 0
    skipped_count: Count = 0
    failure_identity: FailureIdentity | None = None


class FakeTestResultProvider:
    def __init__(self, results: tuple[FakeTestResult, ...], *, repeat_last: bool = False):
        if not isinstance(repeat_last, bool):
            raise ValueError("repeat_last must be a boolean")
        if not results or any(not isinstance(result, FakeTestResult) for result in results):
            raise ValueError("Configure a nonempty typed test-result sequence")
        self.results = tuple(results)
        self.repeat_last = repeat_last

    def _result(self, context: TestContext) -> FakeTestResult:
        index = context.attempt - 1
        if index >= len(self.results):
            if not self.repeat_last:
                raise ScenarioExhaustedError("Configured test-result sequence exhausted")
            index = len(self.results) - 1
        return self.results[index]

    def run(self, context: TestContext) -> TestRun:
        result = self._result(context)
        now = datetime.now(timezone.utc)
        return TestRun(task_id=context.task_id, implementation_artifact_id=context.implementation_artifact_id,
            execution_status=result.execution_status, outcome=result.outcome, environment="fake",
            started_at=now, finished_at=now, passed_count=result.passed_count,
            failed_count=result.failed_count, skipped_count=result.skipped_count)

    def failure_identity(self, context: TestContext) -> FailureIdentity | None:
        return self._result(context).failure_identity

    def execution_failure(self, run: TestRun):
        return None
