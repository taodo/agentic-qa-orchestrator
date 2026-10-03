"""Crash evidence is assessed without replay, writes, source repair or execution."""
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sql_event
from qa_sentinel.api import create_api_app
from qa_sentinel.application import ApplicationError, QASentinelApplication, ProjectExecutionResolver
from qa_sentinel.application.reconciliation import ReconciliationStatus as Status
from qa_sentinel.domain.enums import TaskState, AgentName, AgentInvocationStatus
from qa_sentinel.domain.invocation import AgentInvocation
from qa_sentinel.domain.artifact import Artifact
from qa_sentinel.domain.event import Event
from qa_sentinel.domain.test_run import TestRun as Run
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.projects import ProjectWorkspaceBinding, ProjectRuntimeRegistry, ProjectWorkspaceGuard
from qa_sentinel.mutation.service import MutationService
from qa_sentinel.mutation.contracts import MutationConfig
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from qa_sentinel.host import cli, reconciliation as local_reconciliation
from qa_sentinel.host.web import create_host_app
from test_application_workflow import fake_app, snapshot, composition
from test_repository_workflow import setup, values, tool_turn, final, INITIAL, GUARDED
from test_project_workflow import research, proposal
from test_host import config, local, seed
from test_api import no_sockets


@pytest.fixture
def ctx(factory, tmp_path):
    return fake_app(factory, tmp_path)


def add_event(factory, task, name, *, invocation=None, artifact=None, run=None, payload=None):
    event = Event(task_id=task.id, event_type=name, actor=dict(type="ORCHESTRATOR", id="qa-sentinel"),
        correlation=dict(invocation_id=None if invocation is None else invocation.id,
            artifact_id=None if artifact is None else artifact.id, test_run_id=run), payload=payload or {})
    with UnitOfWork(factory) as uow:
        uow.history.append_event(event)
        uow.commit()
    return event


def pending(factory, task, *, agent="RESEARCHER", model="fake", state="RESEARCHING"):
    invocation = AgentInvocation(task_id=task.id, agent=agent, model=model, reasoning_effort="none",
        attempt=1, status="STARTED", started_at=datetime.now(timezone.utc))
    with UnitOfWork(factory) as uow:
        durable = uow.tasks.get(task.id)
        durable.state = TaskState(state)
        durable.current_invocation_id = invocation.id
        uow.invocations.add(invocation)
        uow.tasks.save(durable)
        uow.commit()
    return invocation


def assert_kind(assessment, kind):
    assert any(i.kind == kind for i in assessment.issues)
    assert not assessment.safe_to_run and not assessment.safe_to_resume


def forbidden(*args, **kwargs):
    raise AssertionError("Assessment/blocked continuation must not execute external work")


def deny_actions(monkeypatch, bundle):
    monkeypatch.setattr(bundle.runtime, "run", forbidden)
    monkeypatch.setattr(bundle.test_provider, "run", forbidden)
    monkeypatch.setattr(OpenAIModelAdapter, "generate", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(MutationService, "apply", forbidden)
    monkeypatch.setattr(MutationService, "build_snapshots", forbidden)
    if bundle.repository_service:
        monkeypatch.setattr(bundle.repository_service, "execute", forbidden)


def test_clean_frozen_and_fake_assessment_no_filesystem_or_evidence_writes(ctx, factory, monkeypatch):
    app, task, bundle = ctx
    deny_actions(monkeypatch, bundle)
    before = snapshot(factory, task.id)
    monkeypatch.setattr(Path, "stat", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(ProjectWorkspaceGuard, "check", forbidden)  # Writing adoption path prohibited.
    result = app.assess_task_reconciliation(task.id)
    assert result.status == Status.CLEAR and result.safe_to_run and not result.safe_to_resume
    with pytest.raises(Exception): result.safe_to_run = False
    assert snapshot(factory, task.id) == before


@pytest.mark.parametrize("current", [True, False])
def test_started_never_cleared_even_if_not_current(ctx, factory, monkeypatch, current):
    app, task, bundle = ctx
    invocation = pending(factory, task)
    if not current:
        with UnitOfWork(factory) as uow:
            durable = uow.tasks.get(task.id); durable.current_invocation_id = None
            uow.tasks.save(durable); uow.commit()
    deny_actions(monkeypatch, bundle)
    before = snapshot(factory, task.id)
    result = app.assess_task_reconciliation(task.id)
    assert result.status == Status.MANUAL_ACTION_REQUIRED
    assert_kind(result, "AGENT_INVOCATION_PENDING")
    assert str(invocation.id) in result.issues[0].evidence_refs
    assert snapshot(factory, task.id) == before


@pytest.mark.parametrize("mode", ["STARTED", "COMPLETED", "DUPLICATE", "MISSING", "WRONG_ROLE", "INVALID_CONTENT"])
def test_canonical_output_linkage_and_reuse(ctx, factory, workflow_outputs, monkeypatch, mode):
    app, task, bundle = ctx
    invocation = pending(factory, task)
    if mode != "STARTED":
        invocation = invocation.model_copy(update={"status": AgentInvocationStatus.COMPLETED, "finished_at": datetime.now(timezone.utc)})
        with UnitOfWork(factory) as uow:
            uow.invocations.save(invocation); uow.commit()
    if mode != "MISSING":
        artifact = Artifact(task_id=task.id, invocation_id=invocation.id, artifact_type="RESEARCH", schema_version="0.1",
            producer_agent="PLANNER" if mode == "WRONG_ROLE" else "RESEARCHER", producer_model="fake",
            content={} if mode == "INVALID_CONTENT" else workflow_outputs["research"].model_dump(mode="json"))
        with UnitOfWork(factory) as uow:
            uow.artifacts.add(artifact)
            if mode == "DUPLICATE": uow.artifacts.add(artifact.model_copy(update={"id": uuid4()}))
            uow.commit()
    result = app.assess_task_reconciliation(task.id)
    if mode == "COMPLETED":
        assert result.status == Status.RECOVERABLE and result.safe_to_run
        original = bundle.runtime.run
        calls = []
        def capture(agent, context):
            calls.append(agent); return original(agent, context)
        monkeypatch.setattr(bundle.runtime, "run", capture)
        assert app.run_task(task.id).state == TaskState.DONE
        assert AgentName.RESEARCHER not in calls
    else:
        assert result.status == Status.INCONSISTENT
        assert_kind(result, "EVIDENCE_INCONSISTENT")


@pytest.mark.parametrize("outcome", [None, "MODEL_TURN_COMPLETED", "MODEL_TURN_FAILED", "DUPLICATE", "OTHER_INVOCATION"])
def test_provider_reservations_require_same_invocation_and_turn(ctx, factory, outcome):
    app, task, _ = ctx
    invocation = pending(factory, task, model="real-model")
    start = add_event(factory, task, "MODEL_TURN_STARTED", invocation=invocation, payload={"turn_index": 1})
    if outcome:
        add_event(factory, task, "MODEL_TURN_COMPLETED" if outcome in {"DUPLICATE", "OTHER_INVOCATION"} else outcome,
            invocation=invocation if outcome != "OTHER_INVOCATION" else None, payload={"turn_index": 1})
    if outcome == "DUPLICATE":
        add_event(factory, task, "MODEL_TURN_COMPLETED", invocation=invocation, payload={"turn_index": 1})
    result = app.assess_task_reconciliation(task.id)
    if outcome in {None, "OTHER_INVOCATION"}:
        assert_kind(result, "PROVIDER_CALL_UNCERTAIN")
        assert any(str(start.id) in issue.evidence_refs for issue in result.issues)
    elif outcome == "DUPLICATE":
        assert result.status == Status.INCONSISTENT
    else:
        assert not any(i.kind == "PROVIDER_CALL_UNCERTAIN" for i in result.issues)
        assert_kind(result, "AGENT_INVOCATION_PENDING")  # Completed turn is not final invocation completion.


@pytest.mark.parametrize("name", ["MUTATION_RESERVED", "MUTATION_RECONCILIATION_REQUIRED"])
def test_mutation_uncertainty_not_inferred_from_proposal(ctx, factory, name):
    app, task, _ = ctx
    invocation = pending(factory, task, agent="IMPLEMENTER", state="IMPLEMENTING")
    add_event(factory, task, name, invocation=invocation, payload={"result": {"rollback": "FAILED"}, "source": "PRIVATE"})
    assert_kind(app.assess_task_reconciliation(task.id), "IMPLEMENTATION_MUTATION_UNCERTAIN")


@pytest.mark.parametrize("durable_run", [False, True, "WRONG_LINK"])
def test_test_reservation_requires_test_run_not_completion_event(ctx, factory, durable_run):
    app, task, _ = ctx
    # A clean completed fake workflow supplies a valid canonical implementation.
    app.run_task(task.id)
    implementation = next(a for a in app.get_task_artifacts(task.id).items if a.artifact_type.value == "IMPLEMENTATION")
    run_id = uuid4()
    add_event(factory, task, "TEST_EXECUTION_STARTED", artifact=implementation, run=run_id, payload={"attempt": 2})
    if durable_run:
        now = datetime.now(timezone.utc)
        run = Run(id=run_id, task_id=task.id, implementation_artifact_id=implementation.id,
            execution_status="COMPLETED", outcome="PASS", environment="fake", started_at=now, finished_at=now,
            passed_count=1, failed_count=0, skipped_count=0)
        with UnitOfWork(factory) as uow:
            uow.history.append_test_run(run); uow.commit()
        if durable_run == "WRONG_LINK":
            add_event(factory, task, "TEST_EXECUTION_STARTED", run=run_id, payload={"attempt": 3})
    result = app.assess_task_reconciliation(task.id)
    if durable_run is False: assert_kind(result, "TEST_EXECUTION_PENDING")
    elif durable_run == "WRONG_LINK": assert result.status == Status.INCONSISTENT
    else: assert result.status == Status.CLEAR and result.safe_to_run


@pytest.mark.parametrize("core_pending", [False, True])
def test_interrupted_job_is_informational_not_core_completion(ctx, factory, core_pending):
    app, task, _ = ctx
    job = app.request_task_execution(task.id)
    assert app.assess_task_reconciliation(task.id).status == Status.RECOVERABLE
    app.claim_next_execution_job()
    app.reconcile_execution_jobs()
    if core_pending: pending(factory, task)
    result = app.assess_task_reconciliation(task.id)
    assert any(i.kind == "EXECUTION_JOB_INTERRUPTED" and i.severity == "INFO" for i in result.issues)
    assert app.get_execution_job(job.id).safe_error_code == "EXECUTION_INTERRUPTED"
    if core_pending: assert_kind(result, "AGENT_INVOCATION_PENDING")
    else: assert result.status == Status.RECOVERABLE and result.safe_to_run


@pytest.mark.parametrize("operation", ["run_task", "resume_task", "request_task_execution"])
@pytest.mark.parametrize("uncertainty", ["AGENT", "TEST", "MUTATION", "PROVIDER"])
def test_all_entrypoints_block_before_work_and_queue_write(ctx, factory, monkeypatch, operation, uncertainty):
    app, task, bundle = ctx
    invocation = pending(factory, task, agent="IMPLEMENTER" if uncertainty == "MUTATION" else "RESEARCHER")
    if uncertainty == "TEST": add_event(factory, task, "TEST_EXECUTION_STARTED", run=uuid4())
    if uncertainty == "MUTATION": add_event(factory, task, "MUTATION_RESERVED", invocation=invocation)
    if uncertainty == "PROVIDER": add_event(factory, task, "MODEL_TURN_STARTED", invocation=invocation, payload={"turn_index": 1})
    with UnitOfWork(factory) as uow:
        durable = uow.tasks.get(task.id); durable.state = TaskState.BLOCKED; durable.resume_state = TaskState.RESEARCHING
        uow.tasks.save(durable); uow.commit()
    deny_actions(monkeypatch, bundle)
    before = snapshot(factory, task.id)
    with pytest.raises(ApplicationError, match="TASK_RECONCILIATION_REQUIRED"):
        getattr(app, operation)(task.id)
    assert not app.list_task_execution_jobs(task.id).items
    assert snapshot(factory, task.id) == before


def test_safe_blocked_resume_advisory_and_clean_work(ctx, factory):
    app, task, _ = ctx
    with UnitOfWork(factory) as uow:
        durable = uow.tasks.get(task.id); durable.state = TaskState.BLOCKED; durable.resume_state = TaskState.RESEARCHING
        uow.tasks.save(durable); uow.commit()
    result = app.assess_task_reconciliation(task.id)
    assert result.safe_to_resume and result.safe_to_run and result.status == Status.CLEAR
    assert app.resume_task(task.id).state == TaskState.RESEARCHING
    assert app.run_task(task.id).state == TaskState.DONE


@pytest.mark.parametrize("drift", ["ANCHOR", "ROOT", "REMOVED_ROOT"])
def test_workspace_drift_never_adopts_new_identity(ctx, factory, tmp_path, drift):
    app, task, bundle = ctx
    app.run_task(task.id)
    if drift == "ANCHOR":
        add_event(factory, task, "PROJECT_WORKSPACE_BOUND", payload={"workspace_identity": "wrong"})
    else:
        root = tmp_path / "other"; root.mkdir()
        binding = ProjectWorkspaceBinding(project_id=task.project_id, workspace_root=root)
        # Physical service triggers accepted real root validation.
        changed = replace(bundle, binding=binding, mutation_service=MutationService(MutationConfig(root)))
        app = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([binding]), [changed]))
        if drift == "REMOVED_ROOT": root.rmdir()
    assert_kind(app.assess_task_reconciliation(task.id), "WORKSPACE_DRIFT")


@pytest.mark.parametrize("drift", [False, True])
def test_real_applied_hash_checks_detached_and_no_execution(migrated_factory, tmp_path, mock_openai, monkeypatch, drift):
    factory, engine, _ = migrated_factory
    mock = mock_openai([tool_turn(), research(INITIAL), final(values()[AgentName.PLANNER], AgentName.PLANNER),
        proposal(INITIAL, "# reconciliation\n"), values()[AgentName.REVIEWER]])
    harness = setup(factory, tmp_path / "target", mock, real_implementation=True)
    app, bundles = composition(factory, [harness])
    assert app.run_task(harness.task.id).state == TaskState.DONE
    if drift: (harness.root / "calculator.py").write_text("# external edit\n", encoding="utf-8")
    deny_actions(monkeypatch, bundles[0])
    before = snapshot(factory, harness.task.id)
    original = harness.mutation.verify_applied
    calls = []
    def verify(*args):
        assert not any(connection.in_transaction() for connection in connections)
        calls.append(args); return original(*args)
    connections = []
    def track(connection): connections.append(connection)
    sql_event.listen(engine, "engine_connect", track)
    monkeypatch.setattr(harness.mutation, "verify_applied", verify)
    result = app.assess_task_reconciliation(harness.task.id)
    assert calls and len(mock.calls) == 5
    if drift: assert_kind(result, "WORKSPACE_DRIFT")
    else: assert result.status == Status.CLEAR
    assert snapshot(factory, harness.task.id) == before


def test_api_typed_safe_read_404_and_all_conflicts(migrated_factory, tmp_path, monkeypatch):
    factory, _, _ = migrated_factory
    app, task, bundle = fake_app(factory, tmp_path)
    pending(factory, task)
    with UnitOfWork(factory) as uow:
        durable = uow.tasks.get(task.id); durable.state = TaskState.BLOCKED; durable.resume_state = TaskState.RESEARCHING
        uow.tasks.save(durable); uow.commit()
    add_event(factory, task, "TEST_EXECUTION_STARTED", run=uuid4(), payload={"path": "C:/PRIVATE", "secret": "PRIVATE"})
    deny_actions(monkeypatch, bundle)
    with TestClient(create_api_app(app)) as client:
        response = client.get(f"/api/v1/tasks/{task.id}/reconciliation")
        assert response.status_code == 200
        data = response.json()
        assert set(data) == {"task_id", "status", "safe_to_run", "safe_to_resume", "issues"}
        assert "PRIVATE" not in response.text
        assert client.get(f"/api/v1/tasks/{uuid4()}/reconciliation").status_code == 404
        for path in ("run", "resume", "executions"):
            response = client.post(f"/api/v1/tasks/{task.id}/{path}")
            assert response.status_code == 409 and response.json()["error"]["code"] == "TASK_RECONCILIATION_REQUIRED"
    assert not app.list_task_execution_jobs(task.id).items


@pytest.mark.parametrize("uncertain", [False, True])
def test_cli_readonly_without_key_or_runtime_construction(config, tmp_path, monkeypatch, capsys, uncertain):
    value = local(config, tmp_path)
    project_id = seed(value, "real-project")
    from qa_sentinel.host.database import bootstrap_database
    engine, factory = bootstrap_database(value.database)
    try:
        from qa_sentinel.domain.task import Task
        task = Task(project_id=project_id, title="CLI", requirement="CLI")
        with UnitOfWork(factory) as uow: uow.tasks.add(task); uow.commit()
        if uncertain: pending(factory, task)
        before = snapshot(factory, task.id)
    finally: engine.dispose()
    path = tmp_path / "local.json"; path.write_text(json.dumps(value.model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setattr(OpenAIModelAdapter, "__init__", forbidden)
    monkeypatch.setattr(MutationService, "apply", forbidden)
    monkeypatch.setattr(MutationService, "build_snapshots", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = cli.main(["local", "reconcile", "--config", str(path), "--task", str(task.id)])
    assert result == int(uncertain)
    output = capsys.readouterr()
    assert ("MANUAL_ACTION_REQUIRED" if uncertain else "CLEAR") in output.out and not output.err
    assert str(value.projects[0].workspace_root) not in output.out
    assert "OPENAI_API_KEY" not in output.out
    engine, factory = bootstrap_database(value.database)
    try: assert snapshot(factory, task.id) == before
    finally: engine.dispose()


def test_preview_assessment_protected_and_fake_only(config, monkeypatch):
    monkeypatch.setenv("QA_SENTINEL_PREVIEW_USERNAME", "operator")
    monkeypatch.setenv("QA_SENTINEL_PREVIEW_PASSWORD", "synthetic-long-preview-password")
    host_config = config.model_copy(update={"mode": "preview-demo", "host": "0.0.0.0"})
    app = create_host_app(host_config)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get(f"/api/v1/tasks/{uuid4()}/reconciliation").status_code == 401
        client.auth = ("operator", "synthetic-long-preview-password")
        project = client.get("/api/v1/projects").json()["items"][0]
        task = client.post(f"/api/v1/projects/{project['id']}/tasks", json={"title": "Demo", "requirement": "Division"}).json()
        response = client.get(f"/api/v1/tasks/{task['id']}/reconciliation")
        assert response.json()["status"] == "CLEAR"
        assert "synthetic-long-preview-password" not in response.text


def test_reasoning_only_provider_reservation_without_turn_events(ctx, factory):
    app, task, _ = ctx
    pending(factory, task, model="real-researcher")
    assert_kind(app.assess_task_reconciliation(task.id), "PROVIDER_CALL_UNCERTAIN")


def test_failed_rollback_blocks_even_with_durable_failed_invocation(ctx, factory):
    from qa_sentinel.domain.error import ErrorRecord
    app, task, _ = ctx
    invocation = pending(factory, task, agent="IMPLEMENTER", state="IMPLEMENTING")
    error = ErrorRecord(task_id=task.id, error_type="TOOL_ERROR", code="MUTATION_APPLY_FAILED", severity="ERROR",
        owner="TOOL", retryable=False, blocking=False, source=dict(invocation_id=invocation.id), message="Fixed failure")
    invocation = invocation.model_copy(update={"status": AgentInvocationStatus.FAILED, "error_id": error.id,
        "finished_at": datetime.now(timezone.utc)})
    with UnitOfWork(factory) as uow:
        uow.history.append_error(error); uow.invocations.save(invocation); uow.commit()
    add_event(factory, task, "MUTATION_RESERVED", invocation=invocation)
    add_event(factory, task, "MUTATION_FAILED", invocation=invocation, payload={"result": {
        "success": False, "decision": {"allowed": False, "reason_code": "MUTATION_APPLY_FAILED", "reason": "Fixed failure"},
        "applied": [], "rollback": "FAILED"}})
    assert_kind(app.assess_task_reconciliation(task.id), "IMPLEMENTATION_MUTATION_UNCERTAIN")


@pytest.mark.parametrize("phase", ["completion", "routing"])
def test_actual_applied_writes_with_persistence_failure_are_not_replayed(migrated_factory, tmp_path, mock_openai, monkeypatch, phase):
    from test_implementation_workflow import outputs, setup as implementation_setup, response, advance
    from qa_sentinel.persistence.repositories import ArtifactRepository, HistoryRepository
    from qa_sentinel.application import ProjectExecutionBundle
    factory, _, _ = migrated_factory
    v = outputs(); mock = mock_openai([v[AgentName.RESEARCHER], v[AgentName.PLANNER], response()])
    harness = implementation_setup(factory, tmp_path, mock)
    stage = advance(harness, TaskState.IMPLEMENTING)
    if phase == "completion":
        original = ArtifactRepository.add
        def fail(self, artifact):
            original(self, artifact)
            if artifact.artifact_type.value == "IMPLEMENTATION": raise RuntimeError("PRIVATE")
        monkeypatch.setattr(ArtifactRepository, "add", fail)
    else:
        original = HistoryRepository.append_event
        def fail(self, item):
            original(self, item)
            if item.event_type == "STATE_TRANSITIONED": raise RuntimeError("PRIVATE")
        monkeypatch.setattr(HistoryRepository, "append_event", fail)
    with pytest.raises(RuntimeError): harness.runner._step(stage)
    if phase == "completion": monkeypatch.setattr(ArtifactRepository, "add", original)
    else: monkeypatch.setattr(HistoryRepository, "append_event", original)
    bundle = ProjectExecutionBundle(harness.provider.workspace_binding, harness.runtime, harness.provider, mutation_service=harness.mutation)
    app = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([bundle.binding]), [bundle]))
    deny_actions(monkeypatch, bundle)
    before = snapshot(factory, stage.id); source = (harness.root / "calculator.py").read_bytes()
    assert source == GUARDED.encode()
    result = app.assess_task_reconciliation(stage.id)
    if phase == "completion":
        assert result.status == Status.MANUAL_ACTION_REQUIRED
        assert_kind(result, "IMPLEMENTATION_MUTATION_UNCERTAIN")
        for action in (app.run_task, app.request_task_execution):
            with pytest.raises(ApplicationError, match="TASK_RECONCILIATION_REQUIRED"): action(stage.id)
    else:
        assert result.status == Status.RECOVERABLE and result.safe_to_run
    assert snapshot(factory, stage.id) == before and (harness.root / "calculator.py").read_bytes() == source
    assert len(mock.calls) == 3 and not app.list_task_execution_jobs(stage.id).items


def test_queued_job_with_new_uncertainty_stops_before_work(config):
    from qa_sentinel.host.composition import compose
    host = compose(config)
    try:
        app = host.application; project = app.list_projects().items[0]
        task = app.create_task(project_id=project.id, title="Queued", requirement="Division")
        job = app.request_task_execution(task.id)
        pending(app._factory, task)
        assert host.worker.execute_one()
        assert app.get_execution_job(job.id).status == "FAILED"
        assert app.get_execution_job(job.id).safe_error_code == "EXECUTION_FAILED"
        assert app.get_task(task.id).state == TaskState.RESEARCHING
        assert len(app.get_task_invocations(task.id).items) == 1
        assert not app.get_task_artifacts(task.id).items and not app.get_task_test_runs(task.id).items
    finally: host.close()
