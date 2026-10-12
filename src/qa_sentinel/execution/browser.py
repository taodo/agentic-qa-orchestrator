"""Future port. Task 5.1 contains no registered browser runtime."""
from typing import Protocol
from qa_sentinel.domain.browser_execution import BrowserPlanEnvelope
from qa_sentinel.domain.qa_run import QARun, QARunTest
from qa_sentinel.domain.qa_run_evidence import TestExecutionResult
from .browser_policy import BrowserExecutionPolicy


class BrowserExecutor(Protocol):
    def execute(self, envelope: BrowserPlanEnvelope, run: QARun, test: QARunTest) -> TestExecutionResult: ...


class BrowserRuntimeUnavailable(RuntimeError):
    pass


class UnavailableBrowserExecutor:
    """Validate before refusal, never fall back to synthetic or claim execution."""
    def execute(self, envelope, run, test):
        BrowserExecutionPolicy().validate_envelope(envelope, run, test)
        raise BrowserRuntimeUnavailable("BROWSER_RUNTIME_UNAVAILABLE")
