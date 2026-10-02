"""Durable execution evidence. Never hold a transaction across subprocess execution."""
from uuid import uuid4
from qa_sentinel.projects import ProjectWorkspaceGuard
from qa_sentinel.domain.enums import TaskState, ArtifactType
from qa_sentinel.domain.artifact import Artifact
from qa_sentinel.domain.error import ErrorRecord
from qa_sentinel.domain.event import Event
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from .base import ExecutionFailure, TestExecutionPendingError
from .pytest_runner import PytestRunner, interpret, to_test_run


class TestExecutionService:
    def __init__(self, session_factory, pytest_runner: PytestRunner, *, workspace_binding=None):
        self.session_factory = session_factory
        self.pytest_runner = pytest_runner
        self.workspace_binding = workspace_binding

    @property
    def workspace_root(self):
        return self.pytest_runner.command_runner.config.workspace_root

    def execute(self, *, task_id, implementation_artifact_id, request):
        with UnitOfWork(self.session_factory) as uow:
            task = uow.tasks.get(task_id)
            if task is None:
                raise ValueError("Execution requires an existing task")
        ProjectWorkspaceGuard(self.session_factory, self.workspace_binding, execution=self).check(task)
        run_id, report_id = uuid4(), uuid4()
        with UnitOfWork(self.session_factory) as uow:
            task, implementation = uow.tasks.get(task_id), uow.artifacts.get(implementation_artifact_id)
            if task is None or implementation is None or implementation.task_id != task_id:
                raise ValueError("Execution requires existing same-task implementation evidence")
            if task.state != TaskState.TESTING or implementation.artifact_type != ArtifactType.IMPLEMENTATION:
                raise ValueError("Execution requires TESTING state and an implementation artifact")
            starts = [e for e in uow.history.list_events(task_id) if e.event_type == "TEST_EXECUTION_STARTED"]
            if any(uow.history.get_test_run(e.correlation.test_run_id) is None for e in starts):
                raise TestExecutionPendingError("Unfinished execution requires explicit reconciliation")
            attempts = [e.payload.get("attempt", 0) for e in uow.history.list_events(task_id)
                        if e.event_type in {"TEST_EXECUTION_STARTED", "TEST_RESULT_RECORDED"}]
            attempt = max(max(attempts, default=0), len(uow.history.list_test_runs(task_id))) + 1
            started = Event(task_id=task_id, event_type="TEST_EXECUTION_STARTED",
                actor=dict(type="ORCHESTRATOR", id="qa-sentinel"),
                correlation=dict(test_run_id=run_id, artifact_id=implementation_artifact_id),
                payload=dict(attempt=attempt, logical_attempt=True))
            uow.history.append_event(started)
            uow.commit()
        result = self.pytest_runner.run(request)
        conclusion = interpret(result)
        report = Artifact(id=report_id, task_id=task_id, artifact_type=ArtifactType.TEST_RESULT,
            schema_version="0.1", content=dict(command_status=result.execution_status.value,
                execution_status=conclusion.execution_status.value,
                outcome=conclusion.outcome.value, exit_code=result.exit_code, duration_ms=result.duration_ms,
                timed_out=result.timed_out, stdout_truncated=result.stdout_truncated,
                stderr_truncated=result.stderr_truncated, counts=result.counts.model_dump(),
                reason_code=conclusion.reason_code, disposition=None if conclusion.disposition is None else conclusion.disposition.value,
                attempt=attempt))
        run = to_test_run(result, task_id=task_id, implementation_artifact_id=implementation_artifact_id,
                          run_id=run_id, report_artifact_id=report.id)
        error = None
        if conclusion.error_type is not None:
            error = ErrorRecord(task_id=task_id, error_type=conclusion.error_type, code=conclusion.reason_code,
                severity="ERROR", owner="TOOL" if conclusion.error_type.value == "TOOL_ERROR" else "ENVIRONMENT"
                if conclusion.error_type.value == "ENVIRONMENT_ERROR" else "ORCHESTRATOR",
                retryable=conclusion.disposition.value == "TRANSIENT", blocking=conclusion.disposition.value != "TRANSIENT",
                source=dict(actor=dict(type="TOOL", id="local-pytest"), tool="pytest"),
                message="Approved test execution did not produce a normal product test conclusion.",
                evidence_refs=(str(run.id), str(report.id)))
        event_type = "TEST_EXECUTION_TIMED_OUT" if result.timed_out else "TEST_EXECUTION_FAILED" if error is not None else "TEST_EXECUTION_COMPLETED"
        event = Event(task_id=task_id, event_type=event_type, timestamp=run.finished_at,
            actor=dict(type="ORCHESTRATOR", id="qa-sentinel"),
            correlation=dict(test_run_id=run.id, artifact_id=report.id),
            payload=dict(attempt=attempt, command_status=result.execution_status.value,
                exit_code=result.exit_code, execution_status=run.execution_status.value,
                outcome=run.outcome.value, duration_ms=result.duration_ms, stdout_truncated=result.stdout_truncated,
                stderr_truncated=result.stderr_truncated, reason_code=conclusion.reason_code))
        with UnitOfWork(self.session_factory) as uow:
            uow.artifacts.add(report)
            uow.history.append_test_run(run)
            if error is not None:
                uow.history.append_error(error)
            uow.history.append_event(event)
            uow.commit()
        return run

    def failure_for(self, run):
        with UnitOfWork(self.session_factory) as uow:
            report = uow.artifacts.get(run.report_artifact_id)
            if report is None or report.task_id != run.task_id:
                raise ValueError("Execution report is missing or unrelated")
            disposition = report.content.get("disposition")
            if disposition is None:
                return None
            errors = [e for e in uow.history.list_errors(run.task_id) if str(run.id) in e.evidence_refs]
            return ExecutionFailure(disposition=disposition, reason_code=report.content["reason_code"],
                                    evidence_refs=tuple(str(e.id) for e in errors))


class PytestTestResultProvider:
    def __init__(self, service: TestExecutionService, request):
        self.service, self.request = service, request

    @property
    def workspace_root(self):
        return self.service.workspace_root

    @property
    def workspace_binding(self):
        return self.service.workspace_binding

    def run(self, context):
        return self.service.execute(task_id=context.task_id,
            implementation_artifact_id=context.implementation_artifact_id, request=self.request)

    def failure_identity(self, context):
        return None  # No log/stack-trace classification in the execution layer.

    def execution_failure(self, run):
        return self.service.failure_for(run)
