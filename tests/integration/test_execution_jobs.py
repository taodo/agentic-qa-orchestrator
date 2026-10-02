"""Durable requests and concurrency proof with file-backed SQLite, no live IO."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading
import time
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from qa_sentinel.api import create_api_app
from qa_sentinel.application import ApplicationError, ApplicationErrorCode as Code, ExecutionJobView, QASentinelApplication
from qa_sentinel.domain.execution_job import ExecutionJob, ExecutionJobStatus as Status
from qa_sentinel.domain.enums import TaskState
from qa_sentinel.host import composition
from qa_sentinel.host.config import HostError
from qa_sentinel.host.web import create_host_app
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from test_host import offline, config, local, seed


@pytest.fixture
def host(config):
    host = composition.compose(config)
    yield host
    host.close()


def task(host):
    project = host.application.list_projects().items[0]
    return host.application.create_task(project_id=project.id, title="Division", requirement="Add division support and reject division by zero.")


def wait_status(app, job_id, expected):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        result = app.get_execution_job(job_id)
        if result.status == expected:
            return result
        threading.Event().wait(0.01)
    pytest.fail(f"Job did not reach {expected}")


def test_job_roundtrip_frozen_view_and_bounded_queries(host):
    target = task(host)
    app = host.application
    job = app.request_task_execution(target.id)
    assert job.task_id == target.id and job.project_id == target.project_id
    assert job.status == Status.QUEUED and app.get_execution_job(job.id) == job
    assert app.get_task_detail(target.id).state == TaskState.CREATED
    page = app.list_task_execution_jobs(target.id)
    assert page.items == (job,) and page.total_returned == 1 and not page.truncated
    assert set(job.model_dump()) == set(ExecutionJobView.model_fields)
    with pytest.raises(Exception): job.status = Status.RUNNING


def test_application_ownership_and_unconfigured_project(host):
    app, target = host.application, task(host)
    other = app.create_project(key="other", name="Other")
    with pytest.raises(ApplicationError, match="PROJECT_TASK_MISMATCH"):
        app.request_task_execution(target.id, project_id=other.id)
    assert not app.list_task_execution_jobs(target.id).items
    job = app.request_task_execution(target.id)
    for operation in (lambda: app.get_execution_job(job.id, project_id=other.id),
        lambda: app.list_task_execution_jobs(target.id, project_id=other.id),
        lambda: app.run_task(target.id, project_id=other.id)):
        with pytest.raises(ApplicationError, match="PROJECT_TASK_MISMATCH"): operation()
    foreign = app.create_task(project_id=other.id, title="Foreign", requirement="Foreign")
    with pytest.raises(ApplicationError, match="PROJECT_RUNTIME_NOT_CONFIGURED"):
        app.request_task_execution(foreign.id)
    assert not app.list_task_execution_jobs(foreign.id).items


@pytest.mark.parametrize("limit", [0, -1, 201, True, "1"])
def test_list_limits_do_not_clamp(host, limit):
    with pytest.raises(ApplicationError, match="INVALID_LIST_LIMIT"):
        host.application.list_task_execution_jobs(task(host).id, limit=limit)


@pytest.mark.parametrize("phase", ["QUEUED", "RUNNING"])
def test_same_task_duplicate_rejected_and_legacy_commands_do_not_bypass_job(host, phase):
    app, target = host.application, task(host)
    job = app.request_task_execution(target.id)
    if phase == "RUNNING": app.claim_next_execution_job()
    for operation in (lambda: app.request_task_execution(target.id), lambda: app.run_task(target.id), lambda: app.resume_task(target.id)):
        with pytest.raises(ApplicationError, match="TASK_EXECUTION_ALREADY_ACTIVE"): operation()
    assert len(app.list_task_execution_jobs(target.id).items) == 1
    assert app.get_execution_job(job.id).status == phase


@pytest.mark.parametrize("independent", [False, True])
def test_simultaneous_duplicate_requests_return_stable_error(host, independent):
    app, target = host.application, task(host)
    barrier = threading.Barrier(2)
    def request():
        barrier.wait(5)
        caller = QASentinelApplication(app._factory, host.resolver) if independent else app
        try: return caller.request_task_execution(target.id)
        except ApplicationError as exc: return exc.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: request(), range(2)))
    assert sum(isinstance(value, ExecutionJobView) for value in results) == 1
    assert Code.TASK_EXECUTION_ALREADY_ACTIVE in results


def test_database_active_and_running_constraints_independent_of_host_lock(host):
    app, a, b = host.application, task(host), task(host)
    first, second = app.request_task_execution(a.id), app.request_task_execution(b.id)
    with pytest.raises(IntegrityError):
        with UnitOfWork(app._factory) as uow:
            uow.execution_jobs.add(ExecutionJob(task_id=a.id, project_id=a.project_id)); uow.commit()
    assert app.claim_next_execution_job().id == first.id
    with pytest.raises(IntegrityError):
        with host.engine.begin() as connection:
            connection.execute(text("update execution_jobs set status='RUNNING', started_at=created_at where id=:id"), {"id": str(second.id)})
    with pytest.raises(ApplicationError, match="EXECUTION_JOB_INVALID_STATE"): app.claim_next_execution_job()
    assert app.get_execution_job(second.id).status == Status.QUEUED


def test_claim_and_completion_state_checks_and_timestamps(host):
    app, target = host.application, task(host)
    job = app.request_task_execution(target.id)
    with pytest.raises(ApplicationError, match="EXECUTION_JOB_INVALID_STATE"):
        app.finish_execution_job(job.id, status="SUCCEEDED")
    claimed = app.claim_next_execution_job()
    assert claimed.id == job.id and claimed.created_at <= claimed.started_at and claimed.finished_at is None
    for status, error in [("QUEUED", None), ("STOPPED", "raw-sensitive-exception"), ("FAILED", None)]:
        with pytest.raises(ApplicationError, match="EXECUTION_JOB_INVALID_STATE"):
            app.finish_execution_job(job.id, status=status, safe_error_code=error)
    done = app.finish_execution_job(job.id, status="SUCCEEDED")
    assert done.started_at <= done.finished_at and done.safe_error_code is None
    with pytest.raises(ApplicationError, match="EXECUTION_JOB_INVALID_STATE"):
        app.finish_execution_job(job.id, status="FAILED", safe_error_code="EXECUTION_FAILED")
    assert app.get_task_detail(target.id).state == TaskState.CREATED
    assert app.request_task_execution(target.id).id != job.id


@pytest.mark.parametrize("state", ["DONE", "FAILED"])
def test_terminal_requests_rejected_legacy_check_stays_idempotent(host, monkeypatch, state):
    app, target = host.application, task(host)
    with UnitOfWork(app._factory) as uow:
        record = uow.tasks.get(target.id); record.state = TaskState(state); uow.tasks.save(record); uow.commit()
    with pytest.raises(ApplicationError, match="TASK_EXECUTION_TERMINAL"):
        app.request_task_execution(target.id)
    bundle = host.resolver.resolve(target.project_id)
    def forbidden(*args, **kwargs): raise AssertionError("Terminal checks cannot call agents")
    monkeypatch.setattr(bundle.runtime, "run", forbidden)
    assert app.run_task(target.id).state == state
    assert not app.list_task_execution_jobs(target.id).items


def test_job_success_does_not_mean_done_or_resume_blocked_task(host):
    app, target = host.application, task(host)
    with UnitOfWork(app._factory) as uow:
        record = uow.tasks.get(target.id)
        record.state, record.resume_state = TaskState.BLOCKED, TaskState.PLANNING
        uow.tasks.save(record); uow.commit()
    job = app.request_task_execution(target.id)
    assert host.worker.execute_one()
    assert app.get_execution_job(job.id).status == Status.SUCCEEDED
    assert app.get_task_detail(target.id).state == TaskState.BLOCKED
    assert app.resume_task(target.id).state == TaskState.PLANNING
    assert not app.get_task_invocations(target.id).items


def test_running_committed_and_no_db_transaction_spans_workflow(host, monkeypatch):
    app, target = host.application, task(host)
    job = app.request_task_execution(target.id)
    calls = []
    def run(task_id, **kwargs):
        assert host.engine.pool.checkedout() == 0
        # A fresh connection sees the durable claim and can write during external work.
        with host.engine.begin() as connection:
            assert connection.scalar(text("select status from execution_jobs where id=:id"), {"id": str(job.id)}) == "RUNNING"
            connection.execute(text("update projects set name=name where id=:id"), {"id": str(target.project_id)})
        calls.append(task_id)
        return app.get_task_detail(task_id)
    monkeypatch.setattr(app, "_run_task", run)
    assert host.worker.execute_one() and calls == [target.id]
    assert app.get_execution_job(job.id).status == Status.SUCCEEDED


def test_unclaimed_worker_context_cannot_enter_workflow(host, monkeypatch):
    app, target = host.application, task(host)
    queued = app.request_task_execution(target.id)
    def forbidden(*args, **kwargs): pytest.fail("QUEUED must never enter workflow")
    monkeypatch.setattr(app, "_run_task", forbidden)
    with host.worker.admission.job(queued.id):
        with pytest.raises(ApplicationError, match="EXECUTION_JOB_INVALID_STATE"):
            app.run_task(target.id)


def test_malformed_persisted_job_ownership_fails_before_work(host, monkeypatch):
    app, target = host.application, task(host)
    other = app.create_project(key="foreign", name="Foreign")
    bad = ExecutionJob(task_id=target.id, project_id=other.id)
    # Deliberate trusted DB corruption; individual FKs cannot prove ownership.
    with UnitOfWork(app._factory) as uow:
        uow.execution_jobs.add(bad); uow.commit()
    with pytest.raises(ApplicationError, match="PROJECT_TASK_MISMATCH"): app.get_execution_job(bad.id)
    with pytest.raises(ApplicationError, match="PROJECT_TASK_MISMATCH"): app.list_task_execution_jobs(target.id)
    def forbidden(*args, **kwargs): pytest.fail("Mismatched ownership entered workflow")
    monkeypatch.setattr(app, "_run_task", forbidden)
    with pytest.raises(HostError): host.worker.execute_one()
    assert host.worker.failed


@pytest.mark.parametrize("failure,status,error", [(ApplicationError(Code.RUNTIME_STOPPED), "STOPPED", "RUNTIME_STOPPED"),
    (RuntimeError("synthetic-raw-secret-exception"), "FAILED", "EXECUTION_FAILED"),
    (ApplicationError(Code.PERSISTENCE_ERROR), "FAILED", "EXECUTION_FAILED")])
def test_safe_stop_and_failure_mapping_never_store_exception(host, monkeypatch, failure, status, error, config):
    app, target = host.application, task(host)
    job = app.request_task_execution(target.id)
    def run(*args, **kwargs): raise failure
    monkeypatch.setattr(app, "_run_task", run)
    assert host.worker.execute_one()
    result = app.get_execution_job(job.id)
    assert result.status == status and result.safe_error_code == error
    assert app.get_task_detail(target.id).state == TaskState.CREATED
    assert b"synthetic-raw-secret-exception" not in config.database.read_bytes()


@pytest.mark.parametrize("operation", ["claim", "finish"])
def test_uncertain_persistence_stops_claims_without_reexecution(host, monkeypatch, operation):
    app, target = host.application, task(host)
    job = app.request_task_execution(target.id)
    calls = []
    monkeypatch.setattr(app, "_run_task", lambda task_id, **kwargs: calls.append(task_id))
    if operation == "claim":
        original = app.claim_next_execution_job
        def fail(): original(); raise RuntimeError("synthetic-sensitive-persistence-error")
        monkeypatch.setattr(app, "claim_next_execution_job", fail)
    else:
        def fail(*args, **kwargs): raise RuntimeError("synthetic-sensitive-persistence-error")
        monkeypatch.setattr(app, "finish_execution_job", fail)
    with pytest.raises(HostError, match="HOST_EXECUTION_PERSISTENCE_UNCERTAIN"):
        host.worker.execute_one()
    assert app.get_execution_job(job.id).status == Status.RUNNING
    assert calls == ([] if operation == "claim" else [target.id]) and host.worker.failed
    assert not host.worker.execute_one()
    assert len(calls) <= 1
    with pytest.raises(ApplicationError, match="RUNTIME_STOPPED"):
        app.request_task_execution(task(host).id)


def test_completion_commit_then_error_does_not_repeat_or_overwrite_success(host, monkeypatch):
    app, target = host.application, task(host)
    job = app.request_task_execution(target.id)
    original = app.finish_execution_job
    monkeypatch.setattr(app, "_run_task", lambda *args, **kwargs: None)
    def fail(*args, **kwargs): original(*args, **kwargs); raise RuntimeError("sensitive-error-after-commit")
    monkeypatch.setattr(app, "finish_execution_job", fail)
    with pytest.raises(HostError): host.worker.execute_one()
    assert host.worker.failed and app.get_execution_job(job.id).status == Status.SUCCEEDED
    assert not host.worker.execute_one()


@pytest.mark.parametrize("tied", [False, True])
def test_fifo_uses_durable_insertion_even_when_timestamps_tie_or_reverse(host, tied):
    app = host.application
    targets = [task(host) for _ in range(3)]
    now = datetime.now(timezone.utc)
    records = [ExecutionJob(task_id=t.id, project_id=t.project_id,
        id=UUID(int=30-index), created_at=now if tied else now - timedelta(days=index)) for index, t in enumerate(targets)]
    with UnitOfWork(app._factory) as uow:
        for record in records: uow.execution_jobs.add(record)
        uow.commit()
    for record in records:
        assert app.claim_next_execution_job().id == record.id
        app.finish_execution_job(record.id, status="SUCCEEDED")
    assert app.claim_next_execution_job() is None


def test_job_lists_newest_insertion_and_truthful_truncation(host):
    app, target = host.application, task(host)
    jobs = []
    for _ in range(3):
        jobs.append(app.request_task_execution(target.id))
        app.claim_next_execution_job(); app.finish_execution_job(jobs[-1].id, status="SUCCEEDED")
    page = app.list_task_execution_jobs(target.id, limit=2)
    assert [j.id for j in page.items] == [j.id for j in jobs[-1:0:-1]]
    assert page.total_returned == 2 and page.truncated


def test_shared_admission_serializes_worker_run_and_resume_but_queues_other_tasks(host, monkeypatch):
    app, a, b = host.application, task(host), task(host)
    job = app.request_task_execution(a.id)
    entered, release = threading.Event(), threading.Event()
    def run(task_id, **kwargs):
        entered.set(); assert release.wait(5); return app.get_task_detail(task_id)
    monkeypatch.setattr(app, "_run_task", run)
    with ThreadPoolExecutor(max_workers=1) as executor:
        work = executor.submit(host.worker.execute_one)
        try:
            assert entered.wait(5)
            for operation in (lambda: app.run_task(b.id), lambda: app.resume_task(b.id)):
                with pytest.raises(ApplicationError, match="RUNTIME_STOPPED"): operation()
            with pytest.raises(ApplicationError, match="TASK_EXECUTION_ALREADY_ACTIVE"): app.request_task_execution(a.id)
            next_job = app.request_task_execution(b.id)
            assert next_job.status == Status.QUEUED and app.get_execution_job(job.id).status == Status.RUNNING
            assert not host.worker.execute_one()
        finally: release.set()
        assert work.result(5)
    assert app.get_execution_job(next_job.id).status == Status.QUEUED


def test_worker_does_not_claim_while_legacy_run_holds_admission(host, monkeypatch):
    app, a, b = host.application, task(host), task(host)
    queued = app.request_task_execution(b.id)
    entered, release = threading.Event(), threading.Event()
    def run(task_id, **kwargs): entered.set(); assert release.wait(5); return app.get_task_detail(task_id)
    monkeypatch.setattr(app, "_run_task", run)
    with ThreadPoolExecutor(max_workers=1) as executor:
        work = executor.submit(app.run_task, a.id)
        try:
            assert entered.wait(5)
            assert not host.worker.execute_one()
            assert app.get_execution_job(queued.id).status == Status.QUEUED
            with pytest.raises(ApplicationError, match="TASK_EXECUTION_ALREADY_ACTIVE"): app.request_task_execution(a.id)
        finally: release.set()
        work.result(5)


def test_reopen_reconciles_running_without_rerun_and_recovers_queued(config):
    first = composition.compose(config)
    a, b = task(first), task(first)
    uncertain = first.application.request_task_execution(a.id)
    queued = first.application.request_task_execution(b.id)
    first.application.claim_next_execution_job()
    first.close()
    second = composition.compose(config)
    calls = []
    second.application._run_task = lambda task_id, **kwargs: calls.append(task_id)
    try:
        second.worker.start()
        wait_status(second.application, queued.id, Status.SUCCEEDED)
        stopped = second.application.get_execution_job(uncertain.id)
        assert stopped.status == Status.STOPPED and stopped.safe_error_code == "EXECUTION_INTERRUPTED"
        assert stopped.finished_at is not None and calls == [b.id]
        assert second.application.get_task_detail(a.id).state == TaskState.CREATED
    finally: second.close()


def test_shutdown_bounded_and_no_new_claims_until_next_process(config, monkeypatch):
    first = composition.compose(config)
    a, b = task(first), task(first)
    current = first.application.request_task_execution(a.id)
    queued = first.application.request_task_execution(b.id)
    entered, release = threading.Event(), threading.Event()
    def run(task_id, **kwargs): entered.set(); assert release.wait(5)
    monkeypatch.setattr(first.application, "_run_task", run)
    first.worker.start()
    try:
        assert entered.wait(5)
        assert not first.worker.stop(timeout=0.01)
        assert first.application.get_execution_job(current.id).status == Status.RUNNING
        assert first.application.get_execution_job(queued.id).status == Status.QUEUED
        with pytest.raises(ApplicationError, match="RUNTIME_STOPPED"): first.application.request_task_execution(task(first).id)
    finally:
        release.set(); assert first.worker.stop(timeout=5); first.close()
    second = composition.compose(config)
    try:
        assert second.application.get_execution_job(current.id).status == Status.SUCCEEDED
        second.worker.start()
        wait_status(second.application, queued.id, Status.SUCCEEDED)
    finally: second.close()


def test_startup_reconciliation_blocks_new_execution_before_worker_starts(host, monkeypatch):
    app, target = host.application, task(host)
    queued = app.request_task_execution(target.id)
    entered, release = threading.Event(), threading.Event()
    original = app.reconcile_execution_jobs
    def reconcile(): entered.set(); assert release.wait(5); return original()
    monkeypatch.setattr(app, "reconcile_execution_jobs", reconcile)
    with ThreadPoolExecutor(max_workers=1) as executor:
        starting = executor.submit(host.worker.start)
        try:
            assert entered.wait(5)
            with pytest.raises(ApplicationError, match="RUNTIME_STOPPED"): app.request_task_execution(task(host).id)
        finally: release.set()
        starting.result(5)
    wait_status(app, queued.id, Status.SUCCEEDED)


def test_failed_thread_start_is_safe_and_close_does_not_join_unstarted_thread(host, monkeypatch):
    def fail(*args, **kwargs): raise RuntimeError("synthetic-private-start-exception")
    monkeypatch.setattr(threading.Thread, "start", fail)
    with pytest.raises(HostError, match="HOST_EXECUTION_WORKER_START_FAILED"):
        host.worker.start()
    assert host.worker.failed
    host.close()  # No raw 'cannot join thread before it is started' error.


def test_duplicate_start_and_repeated_host_close_are_bounded(host, monkeypatch):
    host.worker.start()
    with pytest.raises(HostError, match="HOST_EXECUTION_WORKER_INVALID_STATE"): host.worker.start()
    original = host.worker.stop
    calls = []
    def stop(*args, **kwargs): calls.append(1); return original(*args, **kwargs)
    monkeypatch.setattr(host.worker, "stop", stop)
    host.close(); host.close()
    assert calls == [1]


def test_async_http_contract_no_owner_spoofing_safe_errors_and_limits(host):
    target, other = task(host), task(host)
    with TestClient(create_api_app(host.application)) as client:
        response = client.post(f"/api/v1/tasks/{target.id}/executions")
        assert response.status_code == 202
        job = response.json()
        assert job["status"] == "QUEUED" and job["task_id"] == str(target.id) and job["project_id"] == str(target.project_id)
        assert set(job) == set(ExecutionJobView.model_fields)
        assert client.get(f"/api/v1/executions/{job['id']}").json() == job
        assert client.get(f"/api/v1/tasks/{target.id}/executions").json() == {"items": [job], "total_returned": 1, "truncated": False}
        assert not client.get(f"/api/v1/tasks/{other.id}/executions").json()["items"]
        duplicate = client.post(f"/api/v1/tasks/{target.id}/executions")
        assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "TASK_EXECUTION_ALREADY_ACTIVE"
        unknown = client.get(f"/api/v1/executions/{uuid4()}")
        assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "EXECUTION_JOB_NOT_FOUND"
        for method in (client.get, client.post):
            assert method(f"/api/v1/tasks/{uuid4()}/executions").status_code == 404
        for limit in ("0", "201", "-1", "bad"):
            assert client.get(f"/api/v1/tasks/{target.id}/executions?limit={limit}").status_code == 422
        for body in ({"project_id": str(uuid4())}, {"workspace_root": "/private"}, {"status": "RUNNING"}):
            assert client.post(f"/api/v1/tasks/{other.id}/executions", json=body).status_code == 422
        schema = client.get("/openapi.json").json()
        assert "202" in schema["paths"]["/api/v1/tasks/{task_id}/executions"]["post"]["responses"]
        assert "/api/v1/executions/{execution_id}" in schema["paths"]
        assert not any(key in job for key in ("sequence", "workspace_root", "runtime", "exception", "headers"))


@pytest.mark.parametrize("mode", ["demo", "preview-demo"])
def test_full_host_async_demo_and_preview_remain_fake_only(config, monkeypatch, mode):
    from test_preview import preview, header, USER, PASSWORD
    if mode == "preview-demo":
        monkeypatch.setenv("QA_SENTINEL_PREVIEW_USERNAME", USER)
        monkeypatch.setenv("QA_SENTINEL_PREVIEW_PASSWORD", PASSWORD)
        config = preview(config)
    def forbidden(*args, **kwargs): raise AssertionError("No real composition in demo/preview")
    monkeypatch.setattr(composition, "real_components", forbidden)
    with TestClient(create_host_app(config)) as client:
        headers = header() if mode == "preview-demo" else {}
        project = client.get("/api/v1/projects", headers=headers).json()["items"][0]
        target = client.post(f"/api/v1/projects/{project['id']}/tasks", headers=headers,
            json={"title": "Division", "requirement": "Add division support and reject division by zero."}).json()
        route = f"/api/v1/tasks/{target['id']}/executions"
        if mode == "preview-demo":
            assert client.post(route).status_code == 401
            assert client.get(route).status_code == 401
        result = client.post(route, headers=headers)
        assert result.status_code == 202
        job_id = UUID(result.json()["id"])
        app = client.app.state.host_composition.application
        wait_status(app, job_id, Status.SUCCEEDED)
        assert client.get(f"/api/v1/tasks/{target['id']}", headers=headers).json()["state"] == "DONE"
        assert client.get(f"/api/v1/tasks/{target['id']}/test-runs", headers=headers).json()["items"][0]["environment"] == "fake"
        if mode == "preview-demo": assert client.get(f"/api/v1/executions/{job_id}").status_code == 401
        assert client.post(f"/api/v1/tasks/{target['id']}/run", headers=headers).json()["state"] == "DONE"


def test_real_local_job_uses_existing_resolver_without_persisting_runtime(config, tmp_path, monkeypatch):
    real = local(config, tmp_path)
    owner = seed(real, "real-project")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret-not-persisted")
    composed = composition.compose(real)
    try:
        app = composed.application
        target = app.create_task(project_id=owner, title="Prepared", requirement="Prepared")
        job = app.request_task_execution(target.id)
        def run(task_id, **kwargs):
            detail = app.get_task_detail(task_id)
            bundle = composed.resolver.resolve(detail.project_id)
            assert bundle.binding.workspace_root == real.projects[0].workspace_root
            assert bundle.mutation_service is not None and bundle.repository_service is not None
        monkeypatch.setattr(app, "_run_task", run)
        assert composed.worker.execute_one()
        assert app.get_execution_job(job.id).status == Status.SUCCEEDED
        assert b"synthetic-secret-not-persisted" not in real.database.read_bytes()
        assert str(real.projects[0].workspace_root) not in app.get_execution_job(job.id).model_dump_json()
    finally: composed.close()
