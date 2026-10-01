"""Policy-gated argv execution with bounded pipe draining and explicit cleanup."""
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
import os
import shlex
import subprocess
import tempfile
import threading
import time
from pydantic import BaseModel, ConfigDict
from qa_sentinel.domain.types import Count
from .command_policy import CommandRequest, CommandPolicy, ExecutionConfig
from .process_tree import ProcessTree


class ExecutionStatus(StrEnum):
    COMPLETED = "COMPLETED"
    TIMEOUT = "TIMEOUT"
    FAILED_TO_START = "FAILED_TO_START"
    REJECTED = "REJECTED"


class TestCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    passed: Count = 0
    failed: Count = 0
    skipped: Count = 0
    reliable: bool = False


class CommandExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    executable: str
    args: tuple[str, ...]
    cwd: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    execution_status: ExecutionStatus
    reason_code: str
    counts: TestCounts = TestCounts()


class _Capture:
    def __init__(self, stream, limit):
        self.stream, self.limit = stream, limit
        self.data = bytearray()
        self.truncated = False
        self.error = False

    def drain(self):
        try:
            while chunk := self.stream.read(4096):
                remaining = self.limit - len(self.data)
                self.data.extend(chunk[:remaining])
                self.truncated |= len(chunk) > remaining
        except OSError:
            self.error = True
        finally:
            self.stream.close()


def read_counts(report: Path, limit: int) -> TestCounts:
    from xml.etree import ElementTree
    try:
        if report.is_symlink() or report.resolve(strict=True).parent != report.parent.resolve(strict=True):
            return TestCounts()
        with report.open("rb") as stream:
            data = stream.read(limit + 1)
        text = data.decode("utf-8")
        if len(data) > limit or "\x00" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            return TestCounts()
        root = ElementTree.fromstring(text)
        if root.tag not in {"testsuites", "testsuite"}:
            return TestCounts()
        cases = root.findall(".//testcase")
        if not cases:
            return TestCounts()
        failed = sum(case.find("failure") is not None or case.find("error") is not None for case in cases)
        skipped = sum(case.find("skipped") is not None for case in cases)
        if failed + skipped > len(cases):
            return TestCounts()
        return TestCounts(passed=len(cases) - failed - skipped, failed=failed, skipped=skipped, reliable=True)
    except (OSError, ElementTree.ParseError, ValueError, UnicodeError, RuntimeError):
        return TestCounts()


class CommandRunner:
    def __init__(self, config: ExecutionConfig):
        self.config = config
        self.policy = CommandPolicy(config)

    def run(self, request: CommandRequest) -> CommandExecutionResult:
        request = CommandRequest.model_validate(dict(executable=request.executable, args=request.args,
            cwd=request.cwd, timeout_seconds=request.timeout_seconds, environment=dict(request.environment)))
        started = datetime.now(timezone.utc)
        clock = time.monotonic()
        decision = self.policy.evaluate(request)
        if not decision.allowed:
            return self._result(request, started, clock, ExecutionStatus.REJECTED, decision.reason_code)
        request = CommandRequest(executable=request.executable, args=request.args, cwd=str(self.policy.cwd(request)),
                                 timeout_seconds=request.timeout_seconds, environment=dict(request.environment))
        try:
            with tempfile.TemporaryDirectory(prefix="qa-pytest-", dir=self.config.workspace_root) as directory:
                scratch = Path(directory)
                config_file, report = scratch / "pytest.ini", scratch / "report.xml"
                config_file.write_text("[pytest]\n", encoding="utf-8")
                targets = request.args[2:] or (".",)
                argv = [str(self.config.python_executable), "-P", "-s", "-m", "pytest", *targets,
                    "-c", str(config_file), "--rootdir", str(self.config.workspace_root),
                    "--confcutdir", str(self.config.workspace_root), "--basetemp", str(scratch / "temp"),
                    "--junitxml", str(report), "-p", "no:cacheprovider", "-o", "addopts=",
                    "-o", "pythonpath=" + shlex.quote(self.config.workspace_root.as_posix()),
                    "-o", "junit_logging=no", "-o", "junit_log_passing_tests=false"]
                return self._execute(request, started, clock, scratch, report, argv)
        except OSError:
            return self._result(request, started, clock, ExecutionStatus.FAILED_TO_START, "PROCESS_START_FAILED")

    def _execute(self, request, started, clock, scratch, report, argv):
        process = subprocess.Popen(argv, shell=False, cwd=str(self.policy.cwd(request)),
            env=self.policy.environment(request, scratch), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
        try:
            tree = ProcessTree(process)
        except OSError:
            process.kill()
            process.wait()
            process.stdout.close()
            process.stderr.close()
            raise
        captures = [_Capture(stream, self.config.max_output_bytes) for stream in (process.stdout, process.stderr)]
        threads = [threading.Thread(target=c.drain, daemon=True) for c in captures]
        for thread in threads:
            thread.start()
        timed_out = False
        try:
            try:
                process.wait(timeout=request.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                tree.close()  # Also stop descendants left behind after a normal parent exit.
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
        finally:
            tree.close()
            for thread in threads:
                thread.join(timeout=5)
        if any(t.is_alive() for t in threads) or any(c.error for c in captures):
            return self._result(request, started, clock, ExecutionStatus.FAILED_TO_START, "OUTPUT_CAPTURE_FAILED")
        status = ExecutionStatus.TIMEOUT if timed_out else ExecutionStatus.COMPLETED
        return self._result(request, started, clock, status, "EXECUTION_TIMEOUT" if timed_out else "PROCESS_COMPLETED",
            exit_code=None if timed_out else process.returncode,
            stdout=captures[0].data.decode("utf-8", errors="ignore"), stderr=captures[1].data.decode("utf-8", errors="ignore"),
            stdout_truncated=captures[0].truncated, stderr_truncated=captures[1].truncated,
            counts=read_counts(report, self.config.max_report_bytes) if not timed_out else TestCounts())

    @staticmethod
    def _result(request, started, clock, status, code, **details):
        return CommandExecutionResult(executable="python", args=request.args, cwd=request.cwd,
            started_at=started, finished_at=datetime.now(timezone.utc), duration_ms=int((time.monotonic() - clock) * 1000),
            execution_status=status, reason_code=code, timed_out=status == ExecutionStatus.TIMEOUT,
            **{**dict(exit_code=None, stdout="", stderr="", stdout_truncated=False, stderr_truncated=False), **details})
