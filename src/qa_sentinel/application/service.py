"""Use-case boundary. Execution and transitions belong exclusively to core."""
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from uuid import UUID
from pydantic import ValidationError
from qa_sentinel.domain.project import Project
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.enums import TaskState
from qa_sentinel.domain.execution_job import ExecutionJob, ExecutionJobStatus as JobStatus, ExecutionJobError
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.orchestration.runner import WorkflowRunner
from qa_sentinel.orchestration.workflow_engine import WorkflowEngine
from qa_sentinel.orchestration.errors import WorkflowError
from qa_sentinel.orchestration.state_machine import TERMINAL_STATES
from .commands import CreateTask, UpdateProject
from .errors import ApplicationError, ApplicationErrorCode as Code
from .runtime import ProjectExecutionResolver
from .reconciliation import ReconciliationEvidence, ReconciliationStatus, assess
from .models import (
    CollectionPage, ProjectView, TaskSummary, TaskDetail, TimelineEntry,
    ArtifactView, InvocationView, TestRunView, ErrorView, DecisionView, GateEvaluationView,
    ExecutionJobView,
)
from .operations import (
    OperationalAttention, OperationalSummaryView, ProjectOperationalSummaryView,
    TaskOperationalSummaryView, OperationalActivityView,
)


def identifier(value):
    try:
        return value if isinstance(value, UUID) else UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise ApplicationError(Code.INVALID_INPUT) from None


def list_limit(value, maximum=200):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ApplicationError(Code.INVALID_LIST_LIMIT)
    return value


def project_view(record):
    return ProjectView.model_validate(record.model_dump())


def task_view(record, detail=False):
    view = TaskDetail if detail else TaskSummary
    return view.model_validate(record.model_dump(include=set(view.model_fields)))


def record_view(record, view):
    return view.model_validate(record.model_dump(include=set(view.model_fields)))


def page(records, limit, view):
    items = tuple(record_view(record, view) for record in records[:limit])
    return CollectionPage[view](items=items, total_returned=len(items), truncated=len(records) > limit)


@contextmanager
def persistence_boundary():
    """Keep database/model implementation exceptions out of the public contract."""
    try:
        yield
    except ApplicationError:
        raise
    except Exception:
        raise ApplicationError(Code.PERSISTENCE_ERROR) from None


class QASentinelApplication:
    def __init__(self, session_factory, execution_resolver: ProjectExecutionResolver, *, execution_admission=None, execution_notify=None):
        self._factory = session_factory
        self._resolver = execution_resolver
        # Optional trusted host coordination, never supplied by HTTP/model inputs.
        self._execution_admission = execution_admission
        self._execution_notify = execution_notify

    @staticmethod
    def _project(uow, project_id):
        project = uow.projects.get(project_id)
        if project is None:
            raise ApplicationError(Code.PROJECT_NOT_FOUND)
        return project

    def _task(self, uow, task_id, project_id=None):
        if project_id is not None:
            self._project(uow, project_id)
        task = uow.tasks.get(task_id)
        if task is None:
            raise ApplicationError(Code.TASK_NOT_FOUND)
        if project_id is not None and task.project_id != project_id:
            raise ApplicationError(Code.PROJECT_TASK_MISMATCH)
        self._project(uow, task.project_id)
        return task

    def create_project(self, *, key, name, description="") -> ProjectView:
        try:
            project = Project(key=key, name=name, description=description)
        except ValidationError:
            raise ApplicationError(Code.INVALID_INPUT) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            if uow.projects.get_by_key(project.key) is not None:
                raise ApplicationError(Code.PROJECT_KEY_EXISTS)
            uow.projects.add(project)
            result = project_view(project)
            uow.commit()
            return result

    def update_project(self, project_id, **changes) -> ProjectView:
        project_id = identifier(project_id)
        try:
            command = UpdateProject.model_validate(changes)
        except ValidationError:
            raise ApplicationError(Code.INVALID_INPUT) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            project = self._project(uow, project_id)
            for field in command.model_fields_set:
                setattr(project, field, getattr(command, field))
            project.updated_at = datetime.now(timezone.utc)
            uow.projects.save(project)
            result = project_view(project)
            uow.commit()
            return result

    def get_project(self, project_id) -> ProjectView:
        project_id = identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            return project_view(self._project(uow, project_id))

    def list_projects(self, *, limit=50) -> CollectionPage[ProjectView]:
        limit = list_limit(limit)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            return page(uow.reads.projects(limit), limit, ProjectView)

    def get_operational_summary(self) -> OperationalSummaryView:
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            return OperationalSummaryView.model_validate(uow.operations.summary())

    @staticmethod
    def _operational_page(rows, limit, view):
        items = tuple(view.model_validate(row) for row in rows[:limit])
        return CollectionPage[view](items=items, total_returned=len(items), truncated=len(rows) > limit)

    def list_project_operational_summaries(self, *, limit=50) -> CollectionPage[ProjectOperationalSummaryView]:
        limit = list_limit(limit, 100)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            return self._operational_page(uow.operations.projects(limit), limit, ProjectOperationalSummaryView)

    def list_task_operational_summaries(self, *, project_id=None, task_state=None,
            execution_status=None, attention=None, reconciliation_attention=None,
            active_only=False, attention_only=False, limit=50) -> CollectionPage[TaskOperationalSummaryView]:
        limit = list_limit(limit, 100)
        project_id = None if project_id is None else identifier(project_id)
        try:
            task_state = None if task_state is None else TaskState(task_state)
            execution_status = None if execution_status is None else JobStatus(execution_status)
            attention = None if attention is None else OperationalAttention(attention)
            if any(type(v) is not bool for v in (active_only, attention_only)) or (
                    reconciliation_attention is not None and type(reconciliation_attention) is not bool):
                raise ValueError
        except (TypeError, ValueError):
            raise ApplicationError(Code.INVALID_INPUT) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            if project_id is not None:
                self._project(uow, project_id)
            rows = uow.operations.tasks(limit, project_id=project_id, task_state=task_state,
                execution_status=execution_status, attention=attention,
                reconciliation_attention=reconciliation_attention, active_only=active_only, attention_only=attention_only)
            return self._operational_page(rows, limit, TaskOperationalSummaryView)

    def list_operational_activity(self, *, project_id=None, limit=50) -> CollectionPage[OperationalActivityView]:
        limit = list_limit(limit, 100)
        project_id = None if project_id is None else identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            if project_id is not None:
                self._project(uow, project_id)
            return self._operational_page(uow.operations.activity(limit, project_id), limit, OperationalActivityView)

    def create_task(self, *, project_id, title, requirement) -> TaskSummary:
        try:
            command = CreateTask(project_id=project_id, title=title, requirement=requirement)
        except ValidationError:
            raise ApplicationError(Code.INVALID_INPUT) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._project(uow, command.project_id)
            task = Task(**command.model_dump())
            uow.tasks.add(task)
            result = task_view(task)
            uow.commit()
            return result

    def get_task(self, task_id, *, project_id=None) -> TaskSummary:
        return self._get_task(task_id, project_id, False)

    def get_task_detail(self, task_id, *, project_id=None) -> TaskDetail:
        return self._get_task(task_id, project_id, True)

    def _get_task(self, task_id, project_id, detail):
        task_id = identifier(task_id)
        project_id = None if project_id is None else identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            return task_view(self._task(uow, task_id, project_id), detail)

    def list_tasks_for_project(self, project_id, *, limit=50) -> CollectionPage[TaskSummary]:
        project_id, limit = identifier(project_id), list_limit(limit)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._project(uow, project_id)
            return page(uow.reads.tasks(project_id, limit), limit, TaskSummary)

    def run_task(self, task_id, *, project_id=None) -> TaskDetail:
        task_id = identifier(task_id)
        admission = self._execution_admission
        with admission.task(task_id) if admission else nullcontext():
            self._assert_execution_available(task_id, getattr(admission, "job_id", None), project_id=project_id)
            self._assert_reconciled(task_id, project_id=project_id)
            return self._run_task(task_id, project_id=project_id)

    def assess_task_reconciliation(self, task_id, *, project_id=None):
        task_id = identifier(task_id)
        project_id = None if project_id is None else identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            task = self._task(uow, task_id, project_id)
            evidence = ReconciliationEvidence(task, tuple(uow.invocations.list_by_task(task_id)),
                tuple(uow.artifacts.list_by_task(task_id)), tuple(uow.history.list_events(task_id)),
                tuple(uow.history.list_test_runs(task_id)), tuple(uow.history.list_errors(task_id)),
                tuple(uow.execution_jobs.list_by_task(task_id, 200)))
        # Detached evidence only. No transaction spans even read-only hash verification.
        return assess(evidence, self._resolver.resolve(task.project_id))

    def _assert_reconciled(self, task_id, *, project_id=None):
        assessment = self.assess_task_reconciliation(task_id, project_id=project_id)
        if assessment.status in {ReconciliationStatus.MANUAL_ACTION_REQUIRED, ReconciliationStatus.INCONSISTENT}:
            raise ApplicationError(Code.TASK_RECONCILIATION_REQUIRED)

    def _assert_execution_available(self, task_id, allowed_job_id=None, *, project_id=None):
        project_id = None if project_id is None else identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._task(uow, task_id, project_id)
            active = uow.execution_jobs.active(task_id)
            if allowed_job_id is not None and (active is None or active.id != allowed_job_id or active.status != JobStatus.RUNNING):
                raise ApplicationError(Code.EXECUTION_JOB_INVALID_STATE)
            if active is not None and allowed_job_id is None:
                raise ApplicationError(Code.TASK_EXECUTION_ALREADY_ACTIVE)

    def _run_task(self, task_id, *, project_id=None) -> TaskDetail:
        task = self.get_task_detail(task_id, project_id=project_id)
        bundle = self._resolver.resolve(task.project_id)
        # No application transaction survives this point or wraps model/tool calls.
        try:
            runner = WorkflowRunner(self._factory, bundle.runtime, bundle.test_provider,
                workspace_binding=bundle.binding, repository_service=bundle.repository_service,
                mutation_service=bundle.mutation_service)
            runner.run(task.id)
        except Exception:
            # Includes reconciliation and unexpected host failures. Core evidence/state
            # remains authoritative; this boundary never retries or changes it.
            raise ApplicationError(Code.RUNTIME_STOPPED) from None
        return self.get_task_detail(task.id, project_id=task.project_id)

    def resume_task(self, task_id, *, project_id=None) -> TaskDetail:
        task_id = identifier(task_id)
        admission = self._execution_admission
        with admission.task(task_id) if admission else nullcontext():
            self._assert_execution_available(task_id, project_id=project_id)
            return self._resume_task(task_id, project_id=project_id)

    def _resume_task(self, task_id, *, project_id=None) -> TaskDetail:
        task = self.get_task_detail(task_id, project_id=project_id)
        if task.state != TaskState.BLOCKED:
            raise ApplicationError(Code.TASK_NOT_BLOCKED)
        if task.resume_state is None:
            raise ApplicationError(Code.TASK_RESUME_STATE_MISSING)
        # FAILED is a separate terminal command edge from BLOCKED, never a resume.
        if task.resume_state in TERMINAL_STATES or task.resume_state == TaskState.BLOCKED:
            raise ApplicationError(Code.TASK_RESUME_STATE_INVALID)
        self._assert_reconciled(task_id, project_id=project_id)
        try:
            WorkflowEngine(self._factory).transition(task_id=task.id, to_state=task.resume_state,
                reason_code="APPLICATION_RESUME", reason_details="Explicit host continuation",
                trigger="APPLICATION_RESUME")
        except WorkflowError:
            raise ApplicationError(Code.TASK_RESUME_STATE_INVALID) from None
        except Exception:
            raise ApplicationError(Code.RUNTIME_STOPPED) from None
        return self.get_task_detail(task.id, project_id=task.project_id)

    @contextmanager
    def _job_write(self):
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            # Set before the first statement/BEGIN; each lifecycle transaction ends
            # before any workflow call. SQLite serializes these short writer units.
            uow.session.connection(execution_options={"qa_job_write": True})
            yield uow

    def request_task_execution(self, task_id, *, project_id=None) -> ExecutionJobView:
        task_id = identifier(task_id)
        project_id = None if project_id is None else identifier(project_id)
        admission = self._execution_admission
        with admission.submission(task_id) if admission else nullcontext():
            self._assert_execution_available(task_id, project_id=project_id)
            self._assert_reconciled(task_id, project_id=project_id)
            with self._job_write() as uow:
                task = self._task(uow, task_id, project_id)
                if uow.execution_jobs.active(task.id) is not None:
                    raise ApplicationError(Code.TASK_EXECUTION_ALREADY_ACTIVE)
                if task.state in TERMINAL_STATES:
                    raise ApplicationError(Code.TASK_EXECUTION_TERMINAL)
                self._resolver.resolve(task.project_id)  # Lookup only, no execution.
                job = ExecutionJob(task_id=task.id, project_id=task.project_id)
                uow.execution_jobs.add(job)
                uow.commit()
        if self._execution_notify is not None:
            # Wakeup is advisory; the persisted queue is always authoritative.
            try:
                self._execution_notify()
            except Exception:
                pass
        return record_view(job, ExecutionJobView)

    def get_execution_job(self, job_id, *, project_id=None) -> ExecutionJobView:
        job_id = identifier(job_id)
        project_id = None if project_id is None else identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            job = uow.execution_jobs.get(job_id)
            if job is None:
                raise ApplicationError(Code.EXECUTION_JOB_NOT_FOUND)
            self._task(uow, job.task_id, job.project_id)
            if project_id is not None and project_id != job.project_id:
                raise ApplicationError(Code.PROJECT_TASK_MISMATCH)
            return record_view(job, ExecutionJobView)

    def list_task_execution_jobs(self, task_id, *, project_id=None, limit=50) -> CollectionPage[ExecutionJobView]:
        task_id, limit = identifier(task_id), list_limit(limit)
        project_id = None if project_id is None else identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            task = self._task(uow, task_id, project_id)
            jobs = uow.execution_jobs.list_by_task(task_id, limit)
            if any(job.project_id != task.project_id for job in jobs):
                raise ApplicationError(Code.PROJECT_TASK_MISMATCH)
            return page(jobs, limit, ExecutionJobView)

    # Trusted worker operations: no public HTTP route exposes lifecycle writes.
    def claim_next_execution_job(self) -> ExecutionJobView | None:
        with self._job_write() as uow:
            if uow.execution_jobs.running() is not None:
                raise ApplicationError(Code.EXECUTION_JOB_INVALID_STATE)
            job = uow.execution_jobs.next_queued()
            if job is None:
                return None
            self._task(uow, job.task_id, job.project_id)
            job = ExecutionJob.model_validate({**job.model_dump(), "status": JobStatus.RUNNING,
                "started_at": max(datetime.now(timezone.utc), job.created_at)})
            if not uow.execution_jobs.transition(job, JobStatus.QUEUED):
                raise ApplicationError(Code.EXECUTION_JOB_INVALID_STATE)
            uow.commit()
            return record_view(job, ExecutionJobView)

    def finish_execution_job(self, job_id, *, status, safe_error_code=None) -> ExecutionJobView:
        job_id = identifier(job_id)
        with self._job_write() as uow:
            job = uow.execution_jobs.get(job_id)
            if job is None:
                raise ApplicationError(Code.EXECUTION_JOB_NOT_FOUND)
            if job.status != JobStatus.RUNNING:
                raise ApplicationError(Code.EXECUTION_JOB_INVALID_STATE)
            self._task(uow, job.task_id, job.project_id)
            try:
                job = ExecutionJob.model_validate({**job.model_dump(), "status": status,
                    "safe_error_code": safe_error_code, "finished_at": max(datetime.now(timezone.utc), job.started_at)})
            except ValidationError:
                raise ApplicationError(Code.EXECUTION_JOB_INVALID_STATE) from None
            if not uow.execution_jobs.transition(job, JobStatus.RUNNING):
                raise ApplicationError(Code.EXECUTION_JOB_INVALID_STATE)
            uow.commit()
            return record_view(job, ExecutionJobView)

    def reconcile_execution_jobs(self) -> int:
        # Startup only, with exclusive host ownership. Never rerun uncertain work.
        with self._job_write() as uow:
            job = uow.execution_jobs.running()
            if job is None:
                return 0
            job = ExecutionJob.model_validate({**job.model_dump(), "status": JobStatus.STOPPED,
                "safe_error_code": ExecutionJobError.EXECUTION_INTERRUPTED,
                "finished_at": max(datetime.now(timezone.utc), job.started_at)})
            if not uow.execution_jobs.transition(job, JobStatus.RUNNING):
                raise ApplicationError(Code.EXECUTION_JOB_INVALID_STATE)
            uow.commit()
            return 1

    def _records(self, task_id, project_id, limit, query, view):
        task_id, limit = identifier(task_id), list_limit(limit)
        project_id = None if project_id is None else identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._task(uow, task_id, project_id)
            return page(getattr(uow.reads, query)(task_id, limit), limit, view)

    def get_task_artifacts(self, task_id, *, project_id=None, limit=50) -> CollectionPage[ArtifactView]:
        return self._records(task_id, project_id, limit, "artifacts", ArtifactView)

    def get_task_invocations(self, task_id, *, project_id=None, limit=50) -> CollectionPage[InvocationView]:
        return self._records(task_id, project_id, limit, "invocations", InvocationView)

    def get_task_test_runs(self, task_id, *, project_id=None, limit=50) -> CollectionPage[TestRunView]:
        return self._records(task_id, project_id, limit, "test_runs", TestRunView)

    def get_task_errors(self, task_id, *, project_id=None, limit=50) -> CollectionPage[ErrorView]:
        return self._records(task_id, project_id, limit, "errors", ErrorView)

    def get_task_decisions(self, task_id, *, project_id=None, limit=50) -> CollectionPage[DecisionView]:
        return self._records(task_id, project_id, limit, "decisions", DecisionView)

    def get_task_gate_evaluations(self, task_id, *, project_id=None, limit=50) -> CollectionPage[GateEvaluationView]:
        return self._records(task_id, project_id, limit, "gate_evaluations", GateEvaluationView)

    def get_task_timeline(self, task_id, *, project_id=None, limit=50) -> CollectionPage[TimelineEntry]:
        task_id, limit = identifier(task_id), list_limit(limit, maximum=500)
        project_id = None if project_id is None else identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._task(uow, task_id, project_id)
            rows = uow.reads.timeline(task_id, limit)
            items = []
            for index, (event, insertion, instant) in enumerate(rows[:limit]):
                tied = ((index > 0 and rows[index - 1][2] == instant) or
                        (index + 1 < len(rows) and rows[index + 1][2] == instant))
                allowed = {"from_state", "to_state", "reason_code", "error_code", "agent",
                           "status", "attempt", "domain", "turn_index", "tool", "defect_cycle"}
                details = {key: value for key, value in event.payload.items()
                           if key in allowed and isinstance(value, (str, int, bool, type(None)))}
                items.append(TimelineEntry(index=index + 1, insertion_order=insertion,
                    timestamp=event.timestamp, timestamp_tied=tied, event_id=event.id, task_id=event.task_id,
                    category="EVENT", event_type=event.event_type, actor=event.actor,
                    correlation=event.correlation, summary=event.event_type, details=details))
            return CollectionPage[TimelineEntry](items=tuple(items), total_returned=len(items), truncated=len(rows) > limit)
