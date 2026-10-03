"""Operational snapshots: durable facts, explicit bounds and no execution/IO."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import subprocess
import pytest
from pydantic import ValidationError
from sqlalchemy import event, select
from qa_sentinel.application import QASentinelApplication, ProjectExecutionResolver, ApplicationError
from qa_sentinel.projects import ProjectRuntimeRegistry
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence import models as m
from qa_sentinel.domain.event import Event
from qa_sentinel.domain.enums import TaskState, AgentInvocationStatus
from qa_sentinel.domain.execution_job import ExecutionJob
from qa_sentinel.persistence.execution_jobs import values

NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


@pytest.fixture
def app(factory):
    return QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]), []))


def task(app, key="a", state="CREATED"):
    p = next((p for p in app.list_projects().items if p.key == key), None)
    p = p or app.create_project(key=key, name=key)
    t = app.create_task(project_id=p.id, title="Task", requirement="R")
    with UnitOfWork(app._factory) as uow:
        record = uow.tasks.get(t.id)
        record.state = TaskState(state)
        record.updated_at = NOW
        uow.tasks.save(record); uow.commit()
    return t


def job(app, t, status, stamp=NOW):
    record = ExecutionJob(task_id=t.id, project_id=t.project_id, status=status, created_at=stamp,
        started_at=None if status == "QUEUED" else stamp,
        finished_at=stamp if status in {"FAILED", "STOPPED", "SUCCEEDED"} else None,
        safe_error_code={"FAILED": "EXECUTION_FAILED", "STOPPED": "EXECUTION_INTERRUPTED"}.get(status))
    with UnitOfWork(app._factory) as uow:
        uow.session.add(m.ExecutionJobRow(**values(record))); uow.commit()
    return record


def add_event(app, t, kind, *, payload=None, correlation=None, stamp=NOW, identifier=None):
    record = Event(id=identifier or uuid4(), task_id=t.id, event_type=kind, timestamp=stamp,
        actor={"type": "SYSTEM", "id": "fixture"}, correlation=correlation or {}, payload=payload or {})
    with UnitOfWork(app._factory) as uow:
        uow.history.append_event(record); uow.commit()
    return record


def test_empty_and_frozen(app):
    summary = app.get_operational_summary()
    assert all(v == 0 for k, v in summary.model_dump().items() if k not in {"generated_at", "recent_jobs_window"})
    assert summary.recent_jobs_window == 50
    for method in (app.list_project_operational_summaries, app.list_task_operational_summaries, app.list_operational_activity):
        assert method().items == ()
    with pytest.raises(ValidationError): summary.task_count = 4
    app.create_project(key="empty", name="Empty")
    row = app.list_project_operational_summaries().items[0]
    assert row.task_count == row.active_jobs == 0 and row.latest_activity_at is not None


def test_counts_project_scope_and_state_truth(app):
    running = task(app, "a", "IMPLEMENTING"); job(app, running, "RUNNING")
    queued = task(app, "b"); job(app, queued, "QUEUED")
    blocked = task(app, "a", "BLOCKED")
    done = task(app, "a", "DONE"); job(app, done, "SUCCEEDED")
    failed = task(app, "b", "FAILED"); job(app, failed, "FAILED")
    stopped = task(app, "b", "RESEARCHING"); job(app, stopped, "STOPPED")
    succeeded = task(app, "a", "REVIEWING"); job(app, succeeded, "SUCCEEDED")
    summary = app.get_operational_summary()
    assert (summary.project_count, summary.task_count, summary.running_jobs, summary.queued_jobs,
        summary.blocked_tasks, summary.terminal_tasks, summary.recent_failed_jobs, summary.recent_stopped_jobs) == (2, 7, 1, 1, 1, 2, 1, 1)
    rows = {r.task_id: r for r in app.list_task_operational_summaries().items}
    assert rows[succeeded.id].task_state == "REVIEWING" and rows[succeeded.id].latest_execution_status == "SUCCEEDED"
    assert rows[blocked.id].attention == "BLOCKED"
    assert rows[running.id].attention == "ACTIVE"
    assert rows[stopped.id].attention == "ATTENTION"
    projects = {p.project_key: p for p in app.list_project_operational_summaries().items}
    assert projects["a"].task_count == 4 and projects["a"].blocked_tasks == 1 and projects["b"].active_jobs == 1
    assert len(app.list_task_operational_summaries(project_id=running.project_id).items) == 4
    assert all(r.project_id == queued.project_id for r in app.list_operational_activity(project_id=queued.project_id).items)
    assert app.list_task_operational_summaries(active_only=True).total_returned == 2
    assert app.list_task_operational_summaries(attention_only=True).total_returned == 5
    assert app.list_task_operational_summaries(task_state="DONE").items[0].task_id == done.id
    assert app.list_task_operational_summaries(execution_status="STOPPED").items[0].task_id == stopped.id
    assert app.list_task_operational_summaries(attention="BLOCKED").items[0].task_id == blocked.id


@pytest.mark.parametrize("kind,payload", [
    ("MODEL_TURN_STARTED", {"turn_index": 1}), ("MUTATION_RESERVED", {}),
    ("MUTATION_RECONCILIATION_REQUIRED", {}), ("MUTATION_FAILED", {"result": {"rollback": "FAILED"}}),
    ("TEST_EXECUTION_STARTED", {})])
def test_durable_unresolved_signal(app, kind, payload):
    t = task(app)
    add_event(app, t, kind, payload=payload, correlation={"invocation_id": uuid4(), "test_run_id": uuid4()})
    row = app.list_task_operational_summaries(reconciliation_attention=True).items[0]
    assert row.task_id == t.id and row.attention == "ATTENTION"
    assert app.get_operational_summary().reconciliation_attention_tasks == 1
    assert app.list_project_operational_summaries().items[0].reconciliation_attention_tasks == 1


@pytest.mark.parametrize("start,finish", [("MODEL_TURN_STARTED", "MODEL_TURN_COMPLETED"),
    ("MODEL_TURN_STARTED", "MODEL_TURN_FAILED"), ("MUTATION_RESERVED", "MUTATION_FAILED")])
def test_matching_outcomes_and_cross_task_isolation(app, start, finish):
    t, other = task(app), task(app, "b")
    invocation = uuid4()
    add_event(app, t, start, payload={"turn_index": 1}, correlation={"invocation_id": invocation})
    add_event(app, other, finish, payload={"turn_index": 1}, correlation={"invocation_id": invocation})
    assert app.get_operational_summary().reconciliation_attention_tasks == 1
    if start == "MODEL_TURN_STARTED":
        add_event(app, t, finish, payload={"turn_index": 2}, correlation={"invocation_id": invocation})
        assert app.get_operational_summary().reconciliation_attention_tasks == 1
    add_event(app, t, finish, payload={"turn_index": 1}, correlation={"invocation_id": invocation})
    assert app.get_operational_summary().reconciliation_attention_tasks == 0


def test_pending_invocation_test_outcome_safe_projection_no_io(app, factory, bundle, store_bundle, monkeypatch):
    with UnitOfWork(factory) as uow:
        bundle["error"] = bundle["error"].model_copy(update={"code": "SECRET_RAW_ERROR", "message": "SECRET_RAW_ERROR"})
        store_bundle(uow, bundle); uow.commit()
    t = bundle["task"]
    add_event(app, t, "TEST_EXECUTION_STARTED", correlation={"test_run_id": bundle["test_run"].id,
        "artifact_id": bundle["artifact"].id}, payload={"stdout": "SECRET_RAW_ERROR"})
    def forbidden(*args, **kwargs): raise AssertionError("Operational read must not execute or inspect files")
    from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
    from qa_sentinel.orchestration.runner import WorkflowRunner
    from qa_sentinel.execution.pytest_runner import PytestRunner
    from qa_sentinel.mutation.service import MutationService
    monkeypatch.setattr(app._resolver, "resolve", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(OpenAIModelAdapter, "generate", forbidden)
    monkeypatch.setattr(WorkflowRunner, "run", forbidden)
    monkeypatch.setattr(PytestRunner, "run", forbidden)
    monkeypatch.setattr(MutationService, "apply", forbidden)
    monkeypatch.setattr(MutationService, "verify_applied", forbidden)
    from pathlib import Path
    for name in ("read_bytes", "read_text", "write_bytes", "write_text", "rglob"):
        monkeypatch.setattr(Path, name, forbidden)
    def snapshot():
        with factory() as session:
            return {table.name: session.execute(select(table)).all() for table in m.Base.metadata.tables.values()}
    before = snapshot()
    statements = []
    def captured(conn, cursor, statement, params, context, many): statements.append(statement)
    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", captured)
    try:
        results = [app.get_operational_summary(), app.list_project_operational_summaries(),
            app.list_task_operational_summaries(), app.list_operational_activity()]
    finally: event.remove(engine, "before_cursor_execute", captured)
    assert len([s for s in statements if s.lstrip().upper().startswith("SELECT")]) == 4
    assert all(s.lstrip().upper().startswith(("SELECT", "BEGIN")) for s in statements)
    assert snapshot() == before
    assert results[2].items[0].reconciliation_attention  # Invocation STARTED retained.
    assert results[2].items[0].latest_error_code == "ERROR_RECORDED"
    assert "SECRET_RAW_ERROR" not in "".join(r.model_dump_json() for r in results)
    # Completed matching TestRun does not itself add a pending test signal.
    with UnitOfWork(factory) as uow:
        invocation = uow.invocations.get(bundle["invocation"].id)
        invocation = invocation.model_copy(update={"status": AgentInvocationStatus.COMPLETED, "finished_at": NOW})
        uow.invocations.save(invocation); uow.commit()
    assert not app.list_task_operational_summaries().items[0].reconciliation_attention


def test_activity_instant_order_stable_ties_bounds_and_project_latest(app):
    t = task(app)
    first = add_event(app, t, "STATE_TRANSITIONED", payload={"to_state": "DONE", "secret": "never"},
        stamp=NOW + timedelta(days=1), identifier=UUID(int=2))
    second = add_event(app, t, "STATE_TRANSITIONED", payload={"to_state": "SECRET"},
        stamp=(NOW + timedelta(days=1)).astimezone(timezone(timedelta(hours=7))), identifier=UUID(int=3))
    add_event(app, t, "STATE_TRANSITIONED", payload={"to_state": "CREATED"}, stamp=NOW, identifier=UUID(int=999))
    add_event(app, t, "ARBITRARY_SECRET", payload={"raw": "never"}, stamp=NOW + timedelta(days=10))
    result = app.list_operational_activity(limit=2)
    assert [r.record_id for r in result.items] == [second.id, first.id]
    assert result.truncated and result.items[0].task_state is None and result.items[1].task_state == "DONE"
    assert result == app.list_operational_activity(limit=2)
    assert app.list_project_operational_summaries().items[0].latest_activity_at == NOW + timedelta(days=1)


def test_recent_jobs_window_and_latest_insertion(app):
    t = task(app)
    job(app, t, "FAILED")
    for i in range(50): job(app, t, "SUCCEEDED", NOW - timedelta(minutes=i))
    assert app.get_operational_summary().recent_failed_jobs == 0
    assert app.list_task_operational_summaries().items[0].latest_execution_status == "SUCCEEDED"
    assert app.list_operational_activity(limit=100).total_returned == 100
    assert app.list_operational_activity(limit=100).truncated


@pytest.mark.parametrize("limit", [0, -1, 101, True, 1.5, "50", None])
def test_limit_validation(app, limit):
    for method in (app.list_project_operational_summaries, app.list_task_operational_summaries, app.list_operational_activity):
        with pytest.raises(ApplicationError, match="INVALID_LIST_LIMIT"): method(limit=limit)


@pytest.mark.parametrize("filters", [{"task_state": "unsafe"}, {"attention": "unsafe"},
    {"execution_status": "unsafe"}, {"active_only": 1}, {"attention_only": "true"},
    {"reconciliation_attention": 1}, {"project_id": "unsafe"}])
def test_strict_filters(app, filters):
    with pytest.raises(ApplicationError, match="INVALID_INPUT"): app.list_task_operational_summaries(**filters)


def test_missing_project_and_truncated_task_title(app):
    with pytest.raises(ApplicationError, match="PROJECT_NOT_FOUND"):
        app.list_task_operational_summaries(project_id=uuid4())
    with pytest.raises(ApplicationError, match="PROJECT_NOT_FOUND"):
        app.list_operational_activity(project_id=uuid4())
    t = task(app)
    with UnitOfWork(app._factory) as uow:
        r = uow.tasks.get(t.id); r.title = "x" * 1000; uow.tasks.save(r); uow.commit()
    assert len(app.list_task_operational_summaries().items[0].title) == 240


def test_project_task_bounds_and_instant_tie_order(app):
    first, second = task(app, "a"), task(app, "b")
    rows = app.list_task_operational_summaries(limit=1)
    assert rows.total_returned == 1 and rows.truncated
    assert rows.items[0].task_id == max(first.id, second.id)
    projects = app.list_project_operational_summaries(limit=1)
    assert projects.truncated and projects.items[0].project_key == "a"
    with pytest.raises(ValidationError): rows.items[0].attention = "NORMAL"
    with pytest.raises(ValidationError): rows.items = ()


def test_test_run_artifact_precondition_and_error_instant_order(app, factory, bundle, store_bundle):
    bundle["invocation"] = bundle["invocation"].model_copy(update={"status": AgentInvocationStatus.COMPLETED, "finished_at": NOW})
    with UnitOfWork(factory) as uow:
        store_bundle(uow, bundle)
        newer = bundle["error"].model_copy(update={"id": uuid4(), "code": "OUTPUT_SCHEMA_INVALID", "created_at": NOW.astimezone(timezone(timedelta(hours=7)))})
        uow.history.append_error(newer); uow.commit()
    t = bundle["task"]
    assert app.list_task_operational_summaries().items[0].latest_error_code == "OUTPUT_SCHEMA_INVALID"
    add_event(app, t, "TEST_EXECUTION_STARTED", correlation={"test_run_id": bundle["test_run"].id, "artifact_id": uuid4()})
    assert app.list_task_operational_summaries().items[0].reconciliation_attention


def test_database_failure_is_safe(app, monkeypatch):
    from qa_sentinel.persistence.operations import OperationalQueries
    def fail(*args): raise RuntimeError("PRIVATE_DATABASE_DETAILS")
    monkeypatch.setattr(OperationalQueries, "summary", fail)
    with pytest.raises(ApplicationError, match="PERSISTENCE_ERROR") as caught: app.get_operational_summary()
    assert "PRIVATE" not in str(caught.value)
