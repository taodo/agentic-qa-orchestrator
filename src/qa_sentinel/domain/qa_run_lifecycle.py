"""Explicit Run lifecycle; assertion failures never stop execution."""
from datetime import datetime, timezone
from .qa_run import QARun, QARunTest, QAResult


class RunLifecycleError(ValueError):
    pass


def start_run(run):
    if run.execution_status != "CREATED":
        raise RunLifecycleError("RUN_INVALID_STATE")
    return QARun.model_validate({**run.model_dump(), "execution_status": "RUNNING", "started_at": datetime.now(timezone.utc)})


def start_test(test):
    if test.execution_status != "NOT_STARTED" or test.qa_result != "NOT_EVALUATED":
        raise RunLifecycleError("RUN_INVALID_STATE")
    return QARunTest.model_validate({**test.model_dump(), "execution_status": "RUNNING"})


def finish_test(test, result):
    if test.execution_status != "RUNNING" or result not in {QAResult.PASS, QAResult.FAIL, QAResult.SKIP}:
        raise RunLifecycleError("RUN_INVALID_STATE")
    return QARunTest.model_validate({**test.model_dump(), "execution_status": "COMPLETED", "qa_result": result})


def finish_run(run, tests, *, failed=False):
    if run.execution_status != "RUNNING" or len(tests) != run.test_count or len({t.id for t in tests}) != len(tests) or any(t.run_id != run.id for t in tests):
        raise RunLifecycleError("RUN_INVALID_STATE")
    evaluated = [t.qa_result for t in tests if t.execution_status == "COMPLETED"]
    if failed:
        outcome = "PARTIAL" if evaluated else "NOT_EVALUATED"
    else:
        if len(evaluated) != len(tests):
            raise RunLifecycleError("RUN_INVALID_STATE")
        outcome = "FAIL" if "FAIL" in evaluated else "PASS" if "PASS" in evaluated else "NOT_EVALUATED"
    return QARun.model_validate({**run.model_dump(), "execution_status": "FAILED" if failed else "COMPLETED",
        "qa_outcome": outcome, "completed_at": datetime.now(timezone.utc),
        "execution_error_code": "RUN_EXECUTION_FAILED" if failed else None})
