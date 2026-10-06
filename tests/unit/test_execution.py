from datetime import datetime, timezone
import io
from pathlib import Path
import subprocess
from uuid import uuid4
import pytest
from qa_sentinel.execution.command_policy import CommandPolicy, CommandRequest, ExecutionConfig
from qa_sentinel.execution.command_runner import (
    CommandRunner, CommandExecutionResult, ExecutionStatus, TestCounts as Counts, read_counts,
)
from qa_sentinel.execution.pytest_runner import interpret, to_test_run


@pytest.fixture
def policy(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_example.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    return CommandPolicy(ExecutionConfig(tmp_path, allowed_environment_names=("APP_MODE",)))


def request(**changes):
    return CommandRequest(**{**dict(cwd=".", args=("-m", "pytest", "tests", "-q", "--tb=short")), **changes})


def test_policy_accepts_minimum_pytest_and_explicit_node(policy):
    assert policy.evaluate(CommandRequest(cwd=".")).allowed
    assert policy.evaluate(request()).allowed
    assert policy.evaluate(request(args=("-m", "pytest", "tests/test_example.py::test_ok", "--disable-warnings"))).allowed
    assert policy.evaluate(request(cwd="tests", args=("-m", "pytest", "test_example.py"))).allowed


@pytest.mark.parametrize("changes,code", [
    ({"executable": "pwsh"}, "COMMAND_NOT_ALLOWED"),
    ({"args": ("-c", "print(1)")}, "COMMAND_NOT_ALLOWED"),
    ({"args": ("-m", "pip")}, "COMMAND_NOT_ALLOWED"),
    ({"args": ("-m", "pytest", "tests", "&&", "anything")}, "COMMAND_NOT_ALLOWED"),
    ({"args": ("-m", "pytest", "tests; anything")}, "COMMAND_NOT_ALLOWED"),
    ({"args": ("-m", "pytest", "tests", "|", "anything")}, "COMMAND_NOT_ALLOWED"),
    ({"args": ("-m", "pytest", "`anything`")}, "COMMAND_NOT_ALLOWED"),
    ({"args": ("-m", "pytest", "$(anything)")}, "COMMAND_NOT_ALLOWED"),
    ({"args": ("-m", "pytest", "tests", ">", "report")}, "COMMAND_NOT_ALLOWED"),
    ({"args": ("-m", "pytest", "-p", "external_plugin")}, "PYTEST_OPTION_NOT_ALLOWED"),
    ({"args": ("-m", "pytest", "--junitxml=outside.xml")}, "PYTEST_OPTION_NOT_ALLOWED"),
    ({"args": ("-m", "pytest", "-c", "external.ini")}, "PYTEST_OPTION_NOT_ALLOWED"),
    ({"args": ("-m", "pytest", "-n", "4")}, "PYTEST_OPTION_NOT_ALLOWED"),
    ({"cwd": "missing"}, "INVALID_CWD"),
    ({"cwd": "tests/test_example.py"}, "INVALID_CWD"),
    ({"timeout_seconds": 121}, "TIMEOUT_NOT_ALLOWED"),
    ({"environment": {"SYNTHETIC_API_KEY": "no"}}, "ENVIRONMENT_NOT_ALLOWED"),
    ({"environment": {"PYTEST_ADDOPTS": "-p external"}}, "ENVIRONMENT_NOT_ALLOWED"),
    ({"environment": {"UNAPPROVED_MODE": "no"}}, "ENVIRONMENT_NOT_ALLOWED"),
])
def test_policy_rejection_never_reaches_process(policy, monkeypatch, changes, code):
    def forbidden(*args, **kwargs):
        raise AssertionError("Rejected request reached subprocess")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = CommandRunner(policy.config).run(request(**changes))
    assert result.execution_status == ExecutionStatus.REJECTED and result.reason_code == code


def test_canonical_workspace_and_target_escape(policy, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Escaping path reached subprocess")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    outside = tmp_path.parent / "outside_test.py"
    outside.write_text("def test_external(): pass", encoding="utf-8")
    for cwd in ("..", str(tmp_path.parent)):
        assert policy.evaluate(request(cwd=cwd)).reason_code == "WORKSPACE_ESCAPE"
        assert CommandRunner(policy.config).run(request(cwd=cwd)).execution_status == ExecutionStatus.REJECTED
    for target in ("../outside_test.py", str(outside), "../outside_test.py::test_external"):
        assert policy.evaluate(request(args=("-m", "pytest", target))).reason_code == "WORKSPACE_ESCAPE"
        assert CommandRunner(policy.config).run(request(args=("-m", "pytest", target))).execution_status == ExecutionStatus.REJECTED


def test_symlink_escape_when_supported(policy, tmp_path):
    outside = tmp_path.parent / "outside_directory"
    outside.mkdir(exist_ok=True)
    (outside / "test_external.py").write_text("def test_external(): pass", encoding="utf-8")
    link = tmp_path / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks require OS privileges unavailable here")
    assert policy.evaluate(request(cwd="linked")).reason_code == "WORKSPACE_ESCAPE"
    assert policy.evaluate(request(args=("-m", "pytest", "linked/test_external.py"))).reason_code == "WORKSPACE_ESCAPE"
    # Directory discovery must also reject the link without naming its file explicitly.
    assert policy.evaluate(CommandRequest(cwd=".")).reason_code == "WORKSPACE_ESCAPE"


def test_environment_is_controlled_and_additions_are_immutable(policy, monkeypatch, tmp_path):
    monkeypatch.setenv("SYNTHETIC_PARENT_TOKEN", "never-forward-this")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--unapproved")
    additions = {"APP_MODE": "testing"}
    spec = request(environment=additions)
    additions["APP_MODE"] = "changed"
    assert policy.evaluate(spec).allowed
    env = policy.environment(spec, tmp_path)
    assert env["APP_MODE"] == "testing" and env["PATH"]
    assert "SYNTHETIC_PARENT_TOKEN" not in env and "PYTEST_ADDOPTS" not in env
    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1" and env["TEMP"] == str(tmp_path)
    with pytest.raises(TypeError):
        spec.environment["APP_MODE"] = "mutation"


class _Tree:
    def __init__(self, process): pass
    def close(self): pass


class _Process:
    pid = 123
    def __init__(self, code=0, timeout=False):
        self.returncode = code
        self.timeout = timeout
        self.killed = False
        self.stdout = io.BytesIO(b"output" * 20)
        self.stderr = io.BytesIO(b"error" * 20)
    def wait(self, timeout=None):
        if self.timeout and not self.killed:
            raise subprocess.TimeoutExpired("pytest", timeout)
        return self.returncode
    def poll(self):
        return None if self.timeout and not self.killed else self.returncode
    def kill(self):
        self.killed = True


def test_runner_uses_argv_shell_false_and_bounded_capture(policy, monkeypatch):
    from qa_sentinel.execution import command_runner
    calls = []
    process = _Process(code=1)
    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return process
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(command_runner, "ProcessTree", _Tree)
    config = ExecutionConfig(policy.config.workspace_root, max_output_bytes=16)
    result = CommandRunner(config).run(request())
    argv, kwargs = calls[0]
    assert isinstance(argv, list) and argv[1:5] == ["-P", "-s", "-m", "pytest"]
    assert kwargs["shell"] is False and kwargs["stdin"] == subprocess.DEVNULL
    assert Path(kwargs["cwd"]).is_absolute() and kwargs["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert result.exit_code == 1 and result.execution_status == ExecutionStatus.COMPLETED
    assert len(result.stdout.encode()) <= 16 and len(result.stderr.encode()) <= 16
    assert result.stdout_truncated and result.stderr_truncated


def test_timeout_and_startup_failure_are_structured(policy, monkeypatch):
    from qa_sentinel.execution import command_runner
    process = _Process(timeout=True)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: process)
    monkeypatch.setattr(command_runner, "ProcessTree", _Tree)
    result = CommandRunner(policy.config).run(request(timeout_seconds=0.1))
    assert process.killed and result.timed_out and result.exit_code is None
    assert result.execution_status == ExecutionStatus.TIMEOUT and not result.counts.reliable
    def missing(*a, **kw):
        raise FileNotFoundError("synthetic path should not enter persisted diagnostics")
    monkeypatch.setattr(subprocess, "Popen", missing)
    result = CommandRunner(policy.config).run(request())
    assert result.execution_status == ExecutionStatus.FAILED_TO_START and result.reason_code == "PROCESS_START_FAILED"
    assert result.stdout == result.stderr == ""


def result(exit_code=0, status=ExecutionStatus.COMPLETED):
    now = datetime.now(timezone.utc)
    return CommandExecutionResult(executable="python", args=("-m", "pytest"), cwd=".",
        started_at=now, finished_at=now, duration_ms=1, exit_code=exit_code, timed_out=status == ExecutionStatus.TIMEOUT,
        stdout="misleading prose: all tests passed", stderr="", stdout_truncated=False, stderr_truncated=False,
        execution_status=status, reason_code="PROCESS_START_FAILED" if status == ExecutionStatus.FAILED_TO_START else "COMMAND_NOT_ALLOWED",
        counts=Counts(passed=2, failed=1, skipped=1, reliable=True))


@pytest.mark.parametrize("exit_code,outcome,code", [
    (0, "PASS", "TESTS_PASSED"), (1, "FAIL", "TESTS_FAILED"),
    (2, "UNKNOWN", "PYTEST_INTERRUPTED"), (3, "UNKNOWN", "PYTEST_INTERNAL_ERROR"),
    (4, "UNKNOWN", "PYTEST_USAGE_ERROR"), (5, "UNKNOWN", "NO_TESTS_COLLECTED"),
    (99, "UNKNOWN", "PYTEST_UNEXPECTED_EXIT"),
])
def test_exit_code_is_authoritative(exit_code, outcome, code):
    conclusion = interpret(result(exit_code))
    assert conclusion.outcome.value == outcome and conclusion.reason_code == code
    assert conclusion.execution_status.value == ("COMPLETED" if exit_code in {0, 1} else "FAILED")
    assert (conclusion.error_type is None) == (exit_code in {0, 1})


@pytest.mark.parametrize("status,outcome,execution_status", [
    (ExecutionStatus.COMPLETED, "PASS", "COMPLETED"),
    (ExecutionStatus.TIMEOUT, "UNKNOWN", "INCOMPLETE"),
    (ExecutionStatus.FAILED_TO_START, "UNKNOWN", "FAILED"),
    (ExecutionStatus.REJECTED, "UNKNOWN", "FAILED"),
])
def test_test_run_conversion(status, outcome, execution_status):
    task_id, implementation_id, run_id, report_id = [uuid4() for _ in range(4)]
    run = to_test_run(result(status=status), task_id=task_id, implementation_artifact_id=implementation_id,
                      run_id=run_id, report_artifact_id=report_id)
    assert run.task_id == task_id and run.implementation_artifact_id == implementation_id
    assert run.id == run_id and run.report_artifact_id == report_id and run.environment == "local-pytest"
    assert run.outcome.value == outcome and run.execution_status.value == execution_status
    if status != ExecutionStatus.COMPLETED:
        assert run.passed_count == run.failed_count == run.skipped_count == 0
    failed = to_test_run(result(1), task_id=task_id, implementation_artifact_id=implementation_id,
                         run_id=run_id, report_artifact_id=report_id)
    assert failed.outcome.value == "FAIL" and failed.failed_count == 1


def test_junit_counts_and_bounded_or_missing_report(tmp_path):
    report = tmp_path / "report.xml"
    report.write_text('<testsuites><testsuite><testcase/><testcase><failure/></testcase><testcase><skipped/></testcase></testsuite></testsuites>')
    assert read_counts(report, 4096) == Counts(passed=1, failed=1, skipped=1, reliable=True)
    assert not read_counts(report, 8).reliable
    report.write_text('<!DOCTYPE x [<!ENTITY a "b">]><testsuites/>')
    assert not read_counts(report, 4096).reliable
    assert not read_counts(tmp_path / "missing.xml", 4096).reliable
    report.write_bytes('<!DOCTYPE x [<!ENTITY a "b">]><testsuites/>'.encode("utf-16"))
    assert not read_counts(report, 4096).reliable
