from pathlib import Path
import os
import subprocess
import pytest
from qa_sentinel.agents.fake import FakeAgentRuntime, FakeScenario, FakeResponse
from qa_sentinel.agents.scenarios import division_scenario, DIVISION_REQUIREMENT
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.artifact import Artifact
from qa_sentinel.domain.enums import TaskState as S, AgentName, InvestigationActionType
from qa_sentinel.execution.command_policy import ExecutionConfig, CommandRequest
from qa_sentinel.execution.command_runner import CommandRunner, ExecutionStatus
from qa_sentinel.execution.pytest_runner import PytestRunner
from qa_sentinel.execution.service import TestExecutionService as ExecutionService, PytestTestResultProvider
from qa_sentinel.execution.base import TestExecutionPendingError as PendingError
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.repositories import HistoryRepository
from qa_sentinel.persistence.database import create_engine, create_session_factory
from qa_sentinel.orchestration.runner import WorkflowRunner, RunnerStoppedError


def command(root, *, timeout=120, environment=None, args=None):
    return CommandRequest(cwd=str(root), timeout_seconds=timeout, environment=environment or {},
        args=args or ("-m", "pytest", "tests", "-q", "--tb=short"))


def service(factory, root, *, output_limit=256 * 1024, allowed_names=()):
    config = ExecutionConfig(root, max_output_bytes=output_limit,
        python_path=(Path(pytest.__file__).resolve().parents[1],), allowed_environment_names=allowed_names)
    return ExecutionService(factory, PytestRunner(CommandRunner(config)))


def seed(factory, state=S.TESTING):
    task = Task(title="Real division evidence", requirement=DIVISION_REQUIREMENT, state=state)
    implementation = Artifact(task_id=task.id, artifact_type="IMPLEMENTATION", schema_version="0.1", content={"synthetic": True})
    with UnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.artifacts.add(implementation)
        uow.commit()
    return task, implementation


def test_real_pytest_pass_counts_and_history_survive_reopen(migrated_factory, calculator_workspace):
    factory, engine, _ = migrated_factory
    root = calculator_workspace(extra="\ndef test_skipped():\n    pytest.skip('synthetic skip')\n")
    task, implementation = seed(factory)
    run = service(factory, root).execute(task_id=task.id, implementation_artifact_id=implementation.id, request=command(root))
    assert run.execution_status.value == "COMPLETED" and run.outcome.value == "PASS"
    assert (run.passed_count, run.failed_count, run.skipped_count) == (3, 0, 1)
    assert run.environment == "local-pytest"
    fresh = create_engine(str(engine.url))
    try:
        with UnitOfWork(create_session_factory(fresh)) as uow:
            assert uow.history.get_test_run(run.id) == run
            assert uow.tasks.get(task.id) == task
            assert not uow.history.list_errors(task.id)
            events = uow.history.list_events(task.id)
            assert {e.event_type for e in events} == {"TEST_EXECUTION_STARTED", "TEST_EXECUTION_COMPLETED"}
            assert all(e.correlation.test_run_id == run.id for e in events)
            report = uow.artifacts.get(run.report_artifact_id)
            assert report.artifact_type.value == "TEST_RESULT" and report.content["exit_code"] == 0
            assert "stdout" not in report.content and "stderr" not in report.content
    finally:
        fresh.dispose()
    assert not list(root.glob("qa-pytest-*"))


def test_real_assertion_failure_is_product_evidence(migrated_factory, calculator_workspace):
    factory, _, _ = migrated_factory
    root = calculator_workspace(failing=True)
    task, implementation = seed(factory)
    run = service(factory, root).execute(task_id=task.id, implementation_artifact_id=implementation.id, request=command(root))
    assert run.outcome.value == "FAIL" and run.execution_status.value == "COMPLETED"
    assert (run.passed_count, run.failed_count) == (2, 1)
    with UnitOfWork(factory) as uow:
        assert not uow.history.list_errors(task.id)
        assert uow.artifacts.get(run.report_artifact_id).content["exit_code"] == 1


def test_real_environment_excludes_parent_secrets_and_pytest_addopts(migrated_factory, calculator_workspace, monkeypatch):
    factory, _, _ = migrated_factory
    monkeypatch.setenv("SYNTHETIC_PARENT_TOKEN", "never-forward")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--deliberately-unapproved-option")
    root = calculator_workspace(extra="\ndef test_environment():\n    import os\n"
        "    assert 'SYNTHETIC_PARENT_TOKEN' not in os.environ\n"
        "    assert 'PYTEST_ADDOPTS' not in os.environ\n"
        "    assert os.environ['APP_MODE'] == 'testing'\n    assert os.environ['PATH']\n")
    task, implementation = seed(factory)
    execution = service(factory, root, allowed_names=("APP_MODE",))
    run = execution.execute(task_id=task.id, implementation_artifact_id=implementation.id,
                            request=command(root, environment={"APP_MODE": "testing"}))
    assert run.outcome.value == "PASS" and run.passed_count == 4


def test_real_output_is_bounded_without_persisting_raw_logs(migrated_factory, calculator_workspace):
    factory, _, _ = migrated_factory
    root = calculator_workspace(extra="\ndef test_output():\n    import sys\n"
        "    print('synthetic-output-' * 256)\n    sys.stderr.write('synthetic-error-' * 256)\n")
    execution = service(factory, root, output_limit=128)
    result = execution.pytest_runner.run(command(root, args=("-m", "pytest", "tests", "-q", "-s")))
    assert result.exit_code == 0 and result.stdout_truncated and result.stderr_truncated
    assert len(result.stdout.encode()) <= 128 and len(result.stderr.encode()) <= 128
    task, implementation = seed(factory)
    run = execution.execute(task_id=task.id, implementation_artifact_id=implementation.id,
                            request=command(root, args=("-m", "pytest", "tests", "-q", "-s")))
    with UnitOfWork(factory) as uow:
        report = uow.artifacts.get(run.report_artifact_id)
        assert report.content["stdout_truncated"] and report.content["stderr_truncated"]
        persisted = str([e.model_dump() for e in uow.history.list_events(task.id)]) + str(report.content)
        assert "synthetic-output-" not in persisted and "synthetic-error-" not in persisted
        assert len(str(report.content)) < 2048


def _pid_alive(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = wintypes.DWORD()
        try:
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        stat = Path(f"/proc/{pid}/stat")
        if stat.exists() and stat.read_text().split(") ", 1)[1].startswith("Z"):
            return False
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_real_timeout_terminates_parent_and_child(migrated_factory, calculator_workspace):
    factory, _, _ = migrated_factory
    root = calculator_workspace(extra="\ndef test_slow_child():\n    import os, subprocess, sys, time\n"
        "    from pathlib import Path\n"
        "    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])\n"
        "    Path('child.pid').write_text(str(child.pid))\n    Path('parent.pid').write_text(str(os.getpid()))\n"
        "    time.sleep(10)\n")
    task, implementation = seed(factory)
    run = service(factory, root).execute(task_id=task.id, implementation_artifact_id=implementation.id,
                                         request=command(root, timeout=1.5))
    assert run.outcome.value == "UNKNOWN" and run.execution_status.value == "INCOMPLETE"
    assert run.passed_count == run.failed_count == 0
    assert root.joinpath("child.pid").exists(), "Fixture must actually spawn a child before timeout"
    assert not _pid_alive(int(root.joinpath("child.pid").read_text()))
    assert not _pid_alive(int(root.joinpath("parent.pid").read_text()))
    with UnitOfWork(factory) as uow:
        error, = uow.history.list_errors(task.id)
        assert error.error_type.value == "ENVIRONMENT_ERROR" and error.code == "EXECUTION_TIMEOUT"
        assert any(e.event_type == "TEST_EXECUTION_TIMED_OUT" for e in uow.history.list_events(task.id))


def workflow(factory, root, *, request=None, human_action=False):
    scenario, _ = division_scenario(repair=True)
    if human_action:
        output = scenario.responses[AgentName.INVESTIGATOR][0].output
        output = output.model_copy(update={"recommended_action": output.recommended_action.model_copy(
            update={"type": InvestigationActionType.HUMAN_ACTION})})
        scenario = FakeScenario(responses={**scenario.responses,
            AgentName.INVESTIGATOR: (FakeResponse(output=output),)})
    provider = PytestTestResultProvider(service(factory, root), request or command(root))
    return WorkflowRunner(factory, FakeAgentRuntime(scenario), provider)


def test_workflow_happy_path_uses_real_pytest(migrated_factory, calculator_workspace):
    factory, _, _ = migrated_factory
    root = calculator_workspace()
    task, _ = seed(factory, S.CREATED)
    assert workflow(factory, root).run(task.id).state == S.DONE
    with UnitOfWork(factory) as uow:
        run, = uow.history.list_test_runs(task.id)
        assert run.environment == "local-pytest" and run.passed_count == 3
        assert not uow.history.list_errors(task.id)
        assert any(t.from_state == S.TESTING and t.to_state == S.REVIEWING for t in uow.history.list_transitions(task.id))


def test_real_failure_routes_to_analyzer_not_infrastructure_recovery(migrated_factory, calculator_workspace):
    factory, _, _ = migrated_factory
    root = calculator_workspace(failing=True)
    task, _ = seed(factory, S.CREATED)
    assert workflow(factory, root, human_action=True).run(task.id).state == S.BLOCKED
    with UnitOfWork(factory) as uow:
        assert any(t.from_state == S.TESTING and t.to_state == S.ANALYZING for t in uow.history.list_transitions(task.id))
        assert any(i.agent == AgentName.TEST_ANALYZER for i in uow.invocations.list_by_task(task.id))
        assert not uow.history.list_errors(task.id)
        assert not any(e.event_type == "RETRY_SCHEDULED" for e in uow.history.list_events(task.id))


def test_transient_timeout_retry_survives_service_recreation(migrated_factory, calculator_workspace):
    factory, _, _ = migrated_factory
    root = calculator_workspace(extra="\ndef test_transient_delay():\n    from pathlib import Path\n    import time\n"
        "    marker = Path('delayed-once')\n    if not marker.exists():\n        marker.touch()\n        time.sleep(5)\n")
    task, _ = seed(factory, S.CREATED)
    spec = command(root, timeout=1.5)
    first = workflow(factory, root, request=spec)
    for _ in range(5):
        first._step(first._task(task.id))
    with UnitOfWork(factory) as uow:
        initial, = uow.history.list_test_runs(task.id)
        assert initial.outcome.value == "UNKNOWN"
        retry, = [e for e in uow.history.list_events(task.id) if e.event_type == "RETRY_SCHEDULED"]
        assert retry.payload["domain"] == "TEST_EXECUTION" and retry.correlation.test_run_id == initial.id
    assert workflow(factory, root, request=spec).run(task.id).state == S.DONE
    with UnitOfWork(factory) as uow:
        runs = uow.history.list_test_runs(task.id)
        assert len(runs) == 2 and {r.outcome.value for r in runs} == {"UNKNOWN", "PASS"}
        starts = [e for e in uow.history.list_events(task.id) if e.event_type == "TEST_EXECUTION_STARTED"]
        assert sorted(e.payload["attempt"] for e in starts) == [1, 2]
        assert not any(i.agent == AgentName.TEST_ANALYZER for i in uow.invocations.list_by_task(task.id))


def test_timeout_exhaustion_stops_in_testing_without_analysis(migrated_factory, calculator_workspace):
    factory, _, _ = migrated_factory
    root = calculator_workspace(extra="\ndef test_slow():\n    import time\n    time.sleep(5)\n")
    task, _ = seed(factory, S.CREATED)
    with pytest.raises(RunnerStoppedError, match="no BLOCKED edge"):
        workflow(factory, root, request=command(root, timeout=0.5)).run(task.id)
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(task.id).state == S.TESTING
        assert len(uow.history.list_test_runs(task.id)) == 3
        assert not any(i.agent == AgentName.TEST_ANALYZER for i in uow.invocations.list_by_task(task.id))
        events = uow.history.list_events(task.id)
        assert sum(e.event_type == "RETRY_SCHEDULED" for e in events) == 2
        assert sum(e.event_type == "RETRY_EXHAUSTED" for e in events) == 1
        assert any(e.code == "EXECUTION_TIMEOUT" for e in uow.history.list_errors(task.id))


def test_policy_rejection_persists_without_subprocess(migrated_factory, calculator_workspace, monkeypatch):
    factory, _, _ = migrated_factory
    root = calculator_workspace()
    task, implementation = seed(factory)
    def forbidden(*a, **kw):
        raise AssertionError("Subprocess must not run rejected commands")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    run = service(factory, root).execute(task_id=task.id, implementation_artifact_id=implementation.id,
                                         request=CommandRequest(executable="cmd.exe", cwd=str(root)))
    assert run.outcome.value == "UNKNOWN"
    with UnitOfWork(factory) as uow:
        error, = uow.history.list_errors(task.id)
        assert error.error_type.value == "POLICY_VIOLATION" and error.code == "COMMAND_NOT_ALLOWED"


def test_completion_persistence_failure_rolls_back_all_evidence(migrated_factory, calculator_workspace, monkeypatch):
    factory, _, _ = migrated_factory
    root = calculator_workspace()
    task, implementation = seed(factory)
    execution = service(factory, root)
    original_event = HistoryRepository.append_event
    original_run = execution.pytest_runner.run
    calls = []
    def check_no_transaction(request):
        # An independent writer can commit: execution holds no SQLite transaction.
        with UnitOfWork(factory) as uow:
            uow.tasks.add(Task(title="Independent", requirement="Writer"))
            uow.commit()
        calls.append(request)
        return original_run(request)
    def fail_event(self, event):
        original_event(self, event)
        if event.event_type == "TEST_EXECUTION_COMPLETED":
            raise RuntimeError("Injected completion persistence failure")
    monkeypatch.setattr(execution.pytest_runner, "run", check_no_transaction)
    with monkeypatch.context() as patch:
        patch.setattr(HistoryRepository, "append_event", fail_event)
        with pytest.raises(RuntimeError, match="Injected"):
            execution.execute(task_id=task.id, implementation_artifact_id=implementation.id, request=command(root))
    with UnitOfWork(factory) as uow:
        assert not uow.history.list_test_runs(task.id) and not uow.history.list_errors(task.id)
        assert len(uow.artifacts.list_by_task(task.id)) == 1
        event, = uow.history.list_events(task.id)
        assert event.event_type == "TEST_EXECUTION_STARTED"
    with pytest.raises(PendingError):
        execution.execute(task_id=task.id, implementation_artifact_id=implementation.id, request=command(root))
    assert len(calls) == 1


def test_controlled_config_module_identity_and_space_in_workspace(migrated_factory, calculator_workspace):
    factory, _, _ = migrated_factory
    original = calculator_workspace()
    root = original.parent / "project with spaces"
    original.rename(root)
    root.joinpath("pytest.py").write_text("raise RuntimeError('workspace must not shadow pytest entrypoint')\n")
    root.joinpath("pytest.ini").write_text("[pytest]\naddopts=--deliberately-unapproved-option\n")
    task, implementation = seed(factory)
    run = service(factory, root).execute(task_id=task.id, implementation_artifact_id=implementation.id, request=command(root))
    assert run.outcome.value == "PASS" and run.passed_count == 3


def test_real_start_failure_is_unknown_environment_evidence(migrated_factory, calculator_workspace):
    factory, _, _ = migrated_factory
    root = calculator_workspace()
    task, implementation = seed(factory)
    execution = ExecutionService(factory, PytestRunner(CommandRunner(
        ExecutionConfig(root, python_executable=root / "missing-python.exe"))))
    run = execution.execute(task_id=task.id, implementation_artifact_id=implementation.id, request=command(root))
    assert run.outcome.value == "UNKNOWN" and run.execution_status.value == "FAILED"
    with UnitOfWork(factory) as uow:
        error, = uow.history.list_errors(task.id)
        assert error.code == "PROCESS_START_FAILED" and error.error_type.value == "ENVIRONMENT_ERROR"


def test_timeout_completion_rollback_includes_error_record(migrated_factory, calculator_workspace, monkeypatch):
    from datetime import datetime, timezone
    from qa_sentinel.execution.command_runner import CommandExecutionResult
    factory, _, _ = migrated_factory
    root = calculator_workspace()
    task, implementation = seed(factory)
    execution = service(factory, root)
    now = datetime.now(timezone.utc)
    result = CommandExecutionResult(executable="python", args=("-m", "pytest"), cwd=str(root),
        started_at=now, finished_at=now, duration_ms=1, exit_code=None, timed_out=True,
        stdout="", stderr="", stdout_truncated=False, stderr_truncated=False,
        execution_status="TIMEOUT", reason_code="EXECUTION_TIMEOUT")
    monkeypatch.setattr(execution.pytest_runner, "run", lambda request: result)
    original = HistoryRepository.append_event
    def fail(self, event):
        original(self, event)
        if event.event_type == "TEST_EXECUTION_TIMED_OUT":
            raise RuntimeError("Injected error/event persistence failure")
    monkeypatch.setattr(HistoryRepository, "append_event", fail)
    with pytest.raises(RuntimeError, match="Injected"):
        execution.execute(task_id=task.id, implementation_artifact_id=implementation.id, request=command(root))
    with UnitOfWork(factory) as uow:
        assert not uow.history.list_errors(task.id) and not uow.history.list_test_runs(task.id)
        assert len(uow.artifacts.list_by_task(task.id)) == 1
        event, = uow.history.list_events(task.id)
        assert event.event_type == "TEST_EXECUTION_STARTED"
