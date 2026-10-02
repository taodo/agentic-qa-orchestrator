"""Application commands, scoping, bounds and detached evidence contracts."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import pytest
from pydantic import ValidationError
from sqlalchemy import event, select, func
from qa_sentinel.application import QASentinelApplication, ProjectExecutionResolver, ApplicationError
from qa_sentinel.projects import ProjectRuntimeRegistry
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence import models as rows
from qa_sentinel.persistence.database import create_engine, create_session_factory
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.event import Event


@pytest.fixture
def app(factory):
    return QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]), []))


def assert_code(code, operation):
    with pytest.raises(ApplicationError) as caught:
        operation()
    assert caught.value.code == code
    assert str(caught.value) == code


def test_project_and_task_commands(app):
    owner = app.create_project(key="project-a", name="A")
    other = app.create_project(key="project-b", name="B")
    assert_code("PROJECT_KEY_EXISTS", lambda: app.create_project(key="project-a", name="Duplicate"))
    updated = app.update_project(owner.id, name="Updated", description="Description")
    assert updated.key == owner.key and updated.id == owner.id and updated.created_at == owner.created_at
    assert updated.updated_at >= owner.updated_at and updated.updated_at.utcoffset() == timedelta(0)
    assert app.get_project(owner.id) == updated
    assert [p.key for p in app.list_projects(limit=1).items] == ["project-a"]
    assert app.list_projects(limit=1).truncated
    task = app.create_task(project_id=str(owner.id), title="T", requirement="R")
    second = app.create_task(project_id=other.id, title="T", requirement="R")
    assert task.project_id == owner.id
    assert app.get_task(task.id) == task
    assert app.get_task_detail(task.id).requirement == "R"
    assert [t.id for t in app.list_tasks_for_project(owner.id).items] == [task.id]
    assert_code("PROJECT_TASK_MISMATCH", lambda: app.get_task(second.id, project_id=owner.id))
    with pytest.raises(ValidationError):
        owner.name = "Mutable"
    with pytest.raises(ValidationError):
        type(owner).model_validate({**owner.model_dump(), "workspace_root": "forbidden"})


@pytest.mark.parametrize("changes", [{"key": "new"}, {"id": uuid4()}, {"created_at": "today"},
    {"workspace_root": "."}, {"name": " "}, {"name": None}, {"description": None}])
def test_update_rejects_unapproved_fields_atomically(app, changes):
    owner = app.create_project(key="project-a", name="A")
    assert_code("INVALID_INPUT", lambda: app.update_project(owner.id, **changes))
    assert app.get_project(owner.id) == owner


@pytest.mark.parametrize("key,name", [("BAD", "A"), ("good", " "), ("", "A")])
def test_domain_project_validation_is_safe(app, key, name):
    assert_code("INVALID_INPUT", lambda: app.create_project(key=key, name=name))
    assert app.list_projects().total_returned == 0


def test_missing_resources_and_invalid_inputs(app):
    missing = uuid4()
    assert_code("PROJECT_NOT_FOUND", lambda: app.get_project(missing))
    assert_code("PROJECT_NOT_FOUND", lambda: app.update_project(missing, name="X"))
    assert_code("PROJECT_NOT_FOUND", lambda: app.create_task(project_id=missing, title="T", requirement="R"))
    assert_code("PROJECT_NOT_FOUND", lambda: app.list_tasks_for_project(missing))
    assert_code("TASK_NOT_FOUND", lambda: app.get_task(missing))
    assert_code("TASK_NOT_FOUND", lambda: app.run_task(missing))
    assert_code("TASK_NOT_FOUND", lambda: app.resume_task(missing))
    assert_code("INVALID_INPUT", lambda: app.get_task("invalid"))
    assert_code("INVALID_INPUT", lambda: app.create_task(project_id="invalid", title="T", requirement="R"))


@pytest.mark.parametrize("limit", [0, -1, 201, True, 1.2, "50", None])
def test_invalid_collection_limits(app, limit):
    assert_code("INVALID_LIST_LIMIT", lambda: app.list_projects(limit=limit))
    assert_code("INVALID_LIST_LIMIT", lambda: app.list_tasks_for_project(uuid4(), limit=limit))
    assert_code("INVALID_LIST_LIMIT", lambda: app.get_task_artifacts(uuid4(), limit=limit))


def test_task_ordering_uses_instant_and_uuid_tie(app, factory):
    p = app.create_project(key="project-a", name="A")
    stamps = ["2026-10-01T12:00:00+07:00", "2026-10-01T06:00:00+00:00", "2026-10-01T06:00:00+00:00"]
    tasks = [Task(id=UUID(int=identifier), project_id=p.id, title="T", requirement="R",
        created_at=datetime.fromisoformat(stamp)) for identifier, stamp in zip([9, 3, 2], stamps)]
    with UnitOfWork(factory) as uow:
        for task in tasks:
            uow.tasks.add(task)
        uow.commit()
    page = app.list_tasks_for_project(p.id, limit=2)
    assert [task.id.int for task in page.items] == [2, 3]
    assert page.truncated and page.total_returned == 2


def counts(factory):
    with UnitOfWork(factory) as uow:
        return {table.name: uow.session.scalar(select(func.count()).select_from(table))
                for table in rows.Base.metadata.tables.values()}


def test_all_read_models_are_safe_detached_and_side_effect_free(app, factory, bundle, store_bundle, monkeypatch):
    import subprocess
    from qa_sentinel.orchestration.runner import WorkflowRunner
    from qa_sentinel.orchestration.workflow_engine import WorkflowEngine
    def forbidden(*args, **kwargs):
        raise AssertionError("Query must not execute")
    for target, name in [(WorkflowRunner, "run"), (WorkflowEngine, "transition"), (subprocess, "Popen")]:
        monkeypatch.setattr(target, name, forbidden)
    monkeypatch.setattr(app._resolver, "resolve", forbidden)
    with UnitOfWork(factory) as uow:
        store_bundle(uow, bundle)
        uow.commit()
    before = counts(factory)
    task = bundle["task"]
    detail = app.get_task_detail(task.id, project_id=task.project_id)
    assert detail.implementation_attempt == 2 and detail.current_invocation_id == bundle["invocation"].id
    operations = [app.get_task_artifacts, app.get_task_invocations, app.get_task_test_runs,
                  app.get_task_errors, app.get_task_decisions, app.get_task_gate_evaluations]
    keys = ["artifact", "invocation", "test_run", "error", "decision", "gate_evaluation"]
    for operation, key in zip(operations, keys):
        result = operation(task.id, project_id=task.project_id)
        assert result.total_returned == 1 and not result.truncated
        assert result.items[0].id == bundle[key].id
        assert result.model_dump_json()
        with pytest.raises(ValidationError):
            result.items[0].task_id = uuid4()
    invocation = app.get_task_invocations(task.id).items[0]
    assert "input_context_refs" not in invocation.model_dump()
    content = app.get_task_artifacts(task.id).items[0].content
    with pytest.raises(TypeError):
        content["nested"]["list"][0] = False
    dumped = app.get_task_artifacts(task.id).model_dump()
    dumped["items"][0]["content"]["nested"]["list"].append("changed")
    assert app.get_task_artifacts(task.id).items[0].model_dump()["content"] == bundle["artifact"].content
    assert app.get_task_test_runs(task.id).items[0].environment == "local"
    assert app.get_task_errors(task.id).items[0].code == "ASSERT"
    assert app.get_task_gate_evaluations(task.id).items[0].checks[0].check == "tests"
    assert app.get_task_decisions(task.id).items[0].reason_code == "EVIDENCE"
    assert app.get_task_timeline(task.id).items[0].correlation.artifact_id == bundle["artifact"].id
    assert counts(factory) == before


@pytest.mark.parametrize("method", ["get_task", "get_task_detail", "get_task_timeline", "get_task_artifacts",
    "get_task_invocations", "get_task_test_runs", "get_task_errors", "get_task_decisions", "get_task_gate_evaluations",
    "run_task", "resume_task"])
def test_project_scoping_on_every_task_operation(app, method):
    a = app.create_project(key="a", name="A")
    b = app.create_project(key="b", name="B")
    task = app.create_task(project_id=b.id, title="T", requirement="R")
    assert_code("PROJECT_TASK_MISMATCH", lambda: getattr(app, method)(task.id, project_id=a.id))
    assert_code("PROJECT_NOT_FOUND", lambda: getattr(app, method)(task.id, project_id=uuid4()))


def test_timeline_chronology_ties_truncation_and_reopen(migrated_factory):
    factory, engine, _ = migrated_factory
    app = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]), []))
    p = app.create_project(key="a", name="A")
    task = app.create_task(project_id=p.id, title="T", requirement="R")
    specifications = [(9, "2026-10-01T07:00:00+00:00"), (8, "2026-10-01T12:00:00+07:00"),
                      (1, "2026-10-01T05:00:00+00:00"), (2, "2026-10-01T04:00:00.000001")]
    with UnitOfWork(factory) as uow:
        for number, stamp in specifications:
            uow.history.append_event(Event(id=UUID(int=number), task_id=task.id, event_type="OBSERVED",
                timestamp=datetime.fromisoformat(stamp), actor=dict(type="SYSTEM", id="qa"), correlation={},
                payload={"status": str(number), "raw_provider_response": "must not expose"}))
        uow.commit()
    page = app.get_task_timeline(task.id, limit=2)
    assert [entry.event_id.int for entry in page.items] == [2, 8]
    assert page.truncated and page.items[-1].timestamp_tied
    assert page.items[-1].details == {"status": "8"}
    complete = app.get_task_timeline(task.id)
    assert [entry.event_id.int for entry in complete.items] == [2, 8, 1, 9]
    assert [entry.timestamp_tied for entry in complete.items] == [False, True, True, False]
    fresh = create_engine(str(engine.url))
    try:
        reopened = QASentinelApplication(create_session_factory(fresh), app._resolver)
        assert reopened.get_task_timeline(task.id) == complete
    finally:
        fresh.dispose()
    assert_code("INVALID_LIST_LIMIT", lambda: app.get_task_timeline(task.id, limit=501))


def test_sql_queries_are_bounded_before_materialization(app, factory, bundle, store_bundle):
    with UnitOfWork(factory) as uow:
        store_bundle(uow, bundle)
        uow.commit()
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if "LIMIT" in statement:
            statements.append((statement, parameters))
    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", capture)
    try:
        app.list_projects(limit=1)
        app.list_tasks_for_project(bundle["task"].project_id, limit=1)
        for method in [app.get_task_timeline, app.get_task_artifacts, app.get_task_invocations,
                       app.get_task_test_runs, app.get_task_errors, app.get_task_decisions, app.get_task_gate_evaluations]:
            method(bundle["task"].id, limit=1)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 9
    assert all(parameters[-2:] == (2, 0) for _, parameters in statements)


@pytest.mark.parametrize("state,resume,code", [("CREATED", None, "TASK_NOT_BLOCKED"),
    ("BLOCKED", None, "TASK_RESUME_STATE_MISSING"), ("BLOCKED", "DONE", "TASK_RESUME_STATE_INVALID"),
    ("BLOCKED", "FAILED", "TASK_RESUME_STATE_INVALID"), ("BLOCKED", "BLOCKED", "TASK_RESUME_STATE_INVALID")])
def test_invalid_resume_leaves_history_and_state_intact(app, factory, state, resume, code):
    p = app.create_project(key="a", name="A")
    task = Task(project_id=p.id, title="T", requirement="R", state=state, resume_state=resume)
    with UnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.commit()
    before = counts(factory)
    assert_code(code, lambda: app.resume_task(task.id))
    assert counts(factory) == before and app.get_task(task.id).state.value == state


@pytest.mark.parametrize("failure", [RuntimeError, ValueError])
def test_internal_persistence_errors_have_safe_contract(app, monkeypatch, failure):
    from qa_sentinel.persistence.repositories import ProjectRepository
    def broken(*args, **kwargs):
        raise failure("synthetic-sensitive-internal-detail")
    monkeypatch.setattr(ProjectRepository, "get", broken)
    assert_code("PERSISTENCE_ERROR", lambda: app.get_project(uuid4()))


def test_failed_project_persistence_rolls_back(app, factory, monkeypatch):
    original = UnitOfWork.commit
    def broken(self):
        raise RuntimeError("synthetic-sensitive-storage-detail")
    monkeypatch.setattr(UnitOfWork, "commit", broken)
    assert_code("PERSISTENCE_ERROR", lambda: app.create_project(key="a", name="A"))
    assert app.list_projects().total_returned == 0
    monkeypatch.setattr(UnitOfWork, "commit", original)
    assert app.create_project(key="a", name="A").key == "a"
