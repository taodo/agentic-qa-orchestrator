"""Pytest exit-code interpretation, separate from process execution and workflow routing."""
from pydantic import BaseModel, ConfigDict
from qa_sentinel.domain.enums import TestExecutionStatus, TestOutcome, ErrorType
from qa_sentinel.domain.test_run import TestRun
from qa_sentinel.orchestration.reliability_policy import FailureDisposition as D
from .command_runner import CommandRunner, CommandExecutionResult, ExecutionStatus


class PytestInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    execution_status: TestExecutionStatus
    outcome: TestOutcome
    reason_code: str
    error_type: ErrorType | None = None
    disposition: D | None = None


def interpret(result: CommandExecutionResult) -> PytestInterpretation:
    def failed(code, error, disposition, status=TestExecutionStatus.FAILED):
        return PytestInterpretation(execution_status=status, outcome=TestOutcome.UNKNOWN,
                                    reason_code=code, error_type=error, disposition=disposition)
    if result.execution_status == ExecutionStatus.REJECTED:
        return failed(result.reason_code, ErrorType.POLICY_VIOLATION, D.TERMINAL)
    if result.execution_status == ExecutionStatus.TIMEOUT:
        return failed("EXECUTION_TIMEOUT", ErrorType.ENVIRONMENT_ERROR, D.TRANSIENT, TestExecutionStatus.INCOMPLETE)
    if result.execution_status == ExecutionStatus.FAILED_TO_START:
        return failed(result.reason_code, ErrorType.ENVIRONMENT_ERROR, D.STRUCTURAL)
    if result.exit_code in {0, 1}:
        return PytestInterpretation(execution_status=TestExecutionStatus.COMPLETED,
            outcome=TestOutcome.PASS if result.exit_code == 0 else TestOutcome.FAIL,
            reason_code="TESTS_PASSED" if result.exit_code == 0 else "TESTS_FAILED")
    code, error, disposition = {
        2: ("PYTEST_INTERRUPTED", ErrorType.ENVIRONMENT_ERROR, D.STRUCTURAL),
        3: ("PYTEST_INTERNAL_ERROR", ErrorType.TOOL_ERROR, D.STRUCTURAL),
        4: ("PYTEST_USAGE_ERROR", ErrorType.TOOL_ERROR, D.CORRECTABLE),
        5: ("NO_TESTS_COLLECTED", ErrorType.TOOL_ERROR, D.STRUCTURAL),
    }.get(result.exit_code, ("PYTEST_UNEXPECTED_EXIT", ErrorType.TOOL_ERROR, D.STRUCTURAL))
    return failed(code, error, disposition)


def to_test_run(result, *, task_id, implementation_artifact_id, run_id, report_artifact_id):
    conclusion = interpret(result)
    counts = result.counts if result.counts.reliable and conclusion.execution_status == TestExecutionStatus.COMPLETED else None
    return TestRun(id=run_id, task_id=task_id, implementation_artifact_id=implementation_artifact_id,
        report_artifact_id=report_artifact_id, execution_status=conclusion.execution_status,
        outcome=conclusion.outcome, environment="local-pytest", started_at=result.started_at,
        finished_at=result.finished_at, passed_count=0 if counts is None else counts.passed,
        failed_count=0 if counts is None else counts.failed, skipped_count=0 if counts is None else counts.skipped)


class PytestRunner:
    def __init__(self, command_runner: CommandRunner):
        self.command_runner = command_runner

    def run(self, request) -> CommandExecutionResult:
        return self.command_runner.run(request)
