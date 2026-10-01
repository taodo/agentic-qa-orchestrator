"""Testing provider boundary shared by fake and real deterministic execution."""
from typing import Protocol
from pydantic import BaseModel, ConfigDict
from qa_sentinel.agents.base import TestContext
from qa_sentinel.domain.test_run import TestRun
from qa_sentinel.domain.types import NonBlank
from qa_sentinel.orchestration.reliability_policy import FailureDisposition, FailureIdentity


class ExecutionFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    disposition: FailureDisposition
    reason_code: NonBlank
    evidence_refs: tuple[NonBlank, ...] = ()
    changed_input: bool = False


class TestExecutionPendingError(RuntimeError):
    pass


class TestResultProvider(Protocol):
    def run(self, context: TestContext) -> TestRun: ...
    def failure_identity(self, context: TestContext) -> FailureIdentity | None: ...
    def execution_failure(self, run: TestRun) -> ExecutionFailure | None: ...
