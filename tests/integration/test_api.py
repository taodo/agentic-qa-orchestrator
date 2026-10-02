"""Socket-free HTTP transport proof over accepted application/core services."""
import ast
import socket
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4
from dataclasses import replace
import pytest
from fastapi.testclient import TestClient
from qa_sentinel.api import create_api_app
from qa_sentinel.api.errors import ERROR_MAPPING
from qa_sentinel.application import (
    QASentinelApplication, ProjectExecutionResolver, ProjectExecutionBundle,
    ApplicationError, ApplicationErrorCode,
)
from qa_sentinel.projects import ProjectRuntimeRegistry, ProjectWorkspaceBinding
from qa_sentinel.agents.scenarios import division_scenario
from qa_sentinel.agents.fake import FakeAgentRuntime, FakeScenario, FakeResponse
from qa_sentinel.execution.fake import FakeTestResultProvider
from qa_sentinel.domain.enums import AgentName as A, TaskState as S
from qa_sentinel.orchestration.workflow_engine import WorkflowEngine
from qa_sentinel.orchestration.runner import WorkflowRunner
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.models import Base
from sqlalchemy import select, func


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch):
    original_connect = socket.socket.connect
    def forbidden(*args, **kwargs):
        raise AssertionError("HTTP tests must not connect to a real socket")
    def guarded_connect(sock, address):
        # Windows implements asyncio's private wakeup socketpair with loopback.
        # Permit only that exact stdlib call site, never an API/provider connection.
        caller = sys._getframe(1).f_code
        fallback = getattr(socket, "_fallback_socketpair", None)
        if fallback is not None and caller is fallback.__code__:
            return original_connect(sock, address)
        return forbidden(sock, address)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def api(migrated_factory):
    factory, _, _ = migrated_factory
    application = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]), []))
    with TestClient(create_api_app(application)) as client:
        yield client, application, factory


def create_project(client, key="a"):
    response = client.post("/api/v1/projects", json={"key": key, "name": key.upper()})
    assert response.status_code == 201, response.text
    return response.json()


def create_task(client, project):
    response = client.post(f"/api/v1/projects/{project['id']}/tasks", json={"title": "Division", "requirement": "Add division"})
    assert response.status_code == 201, response.text
    return response.json()


def configure(application, project, root, *, blocked=False):
    root.mkdir()
    scenario, runs = division_scenario()
    if blocked:
        scenario = FakeScenario(responses={**scenario.responses, A.RESEARCHER: (
            FakeResponse(output=scenario.responses[A.RESEARCHER][0].output.model_copy(
                update={"research_complete": False})), scenario.responses[A.RESEARCHER][0])})
    runtime = FakeAgentRuntime(scenario)
    binding = ProjectWorkspaceBinding(project_id=project["id"], workspace_root=root)
    return ProjectExecutionBundle(binding, runtime, FakeTestResultProvider(runs))


def bind(application, bundles):
    application._resolver = ProjectExecutionResolver(ProjectRuntimeRegistry([b.binding for b in bundles]), bundles)


def counts(factory):
    with UnitOfWork(factory) as uow:
        return {table.name: uow.session.scalar(select(func.count()).select_from(table))
                for table in Base.metadata.tables.values()}


def error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert set(response.json()) == {"error"}
    assert set(response.json()["error"]) == {"code", "message"}


def test_health_openapi_and_no_unversioned_domain_routes(api):
    client, application, _ = api
    assert client.get("/health").json() == {"status": "ok"}
    schema = client.get("/openapi.json").json()
    assert schema["info"] == {"title": "QA Sentinel API", "version": "1.0.0"}
    expected = {"/api/v1/projects", "/api/v1/projects/{project_id}", "/api/v1/projects/{project_id}/tasks",
        "/api/v1/tasks/{task_id}", "/api/v1/tasks/{task_id}/run", "/api/v1/tasks/{task_id}/resume"}
    expected |= {"/api/v1/tasks/{task_id}/" + suffix for suffix in
                 ("timeline", "artifacts", "test-runs", "errors", "decisions", "gates", "invocations")}
    assert set(schema["paths"]) == expected | {"/health"}
    assert schema["paths"]["/api/v1/projects"]["post"]["responses"]["201"]
    error_schema = schema["paths"]["/api/v1/projects"]["get"]["responses"]["422"]["content"]["application/json"]["schema"]
    assert error_schema["$ref"].endswith("/ErrorEnvelope")
    assert client.get("/docs").status_code == 200
    error(client.get("/projects"), 404, "HTTP_ERROR")
    preflight = client.options("/api/v1/projects", headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in preflight.headers
    second = QASentinelApplication(application._factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]), []))
    assert create_api_app(second).state.application is second
    assert client.app.state.application is application


def test_project_commands_lists_and_ownership(api):
    client, application, _ = api
    a, b = create_project(client), create_project(client, "b")
    error(client.post("/api/v1/projects", json={"key": "a", "name": "Duplicate"}), 409, "PROJECT_KEY_EXISTS")
    updated = client.patch(f"/api/v1/projects/{a['id']}", json={"description": "new"})
    assert updated.status_code == 200 and updated.json()["name"] == "A"
    assert updated.json()["created_at"] == a["created_at"]
    assert client.get(f"/api/v1/projects/{a['id']}").json() == updated.json()
    response = client.get("/api/v1/projects?limit=1").json()
    assert response["total_returned"] == 1 and response["truncated"] and len(response["items"]) == 1
    ta, tb = create_task(client, a), create_task(client, b)
    assert ta["project_id"] == a["id"] and tb["project_id"] == b["id"]
    assert [t["id"] for t in client.get(f"/api/v1/projects/{a['id']}/tasks").json()["items"]] == [ta["id"]]
    assert client.get(f"/api/v1/tasks/{tb['id']}").json()["project_id"] == b["id"]
    for spoof in [{"project_id": b["id"]}, {"state": "DONE"}, {"workspace_root": "."}]:
        error(client.post(f"/api/v1/projects/{a['id']}/tasks", json={"title": "T", "requirement": "R", **spoof}), 422, "REQUEST_VALIDATION_ERROR")
    assert application.list_tasks_for_project(a["id"]).total_returned == 1


@pytest.mark.parametrize("body", [{"key": "x"}, {"id": str(uuid4())}, {"created_at": "today"},
    {"workspace_root": "synthetic-sensitive-path"}, {"extra": "synthetic-secret"}, {"name": None}, {"description": None}])
def test_update_rejects_immutable_extra_and_null_fields(api, body):
    client, _, _ = api
    p = create_project(client)
    response = client.patch(f"/api/v1/projects/{p['id']}", json=body)
    error(response, 422, "REQUEST_VALIDATION_ERROR")
    assert "synthetic" not in response.text
    assert client.get(f"/api/v1/projects/{p['id']}").json() == p


LIST_PATHS = ["/api/v1/projects", "/api/v1/projects/{project}/tasks"] + [
    "/api/v1/tasks/{task}/" + suffix for suffix in ("timeline", "artifacts", "test-runs", "errors", "decisions", "gates", "invocations")]


@pytest.mark.parametrize("path", LIST_PATHS)
@pytest.mark.parametrize("limit", ["0", "-1", "501", "text", "1.5", "true"])
def test_every_collection_rejects_invalid_limits(api, path, limit):
    client, _, _ = api
    path = path.format(project=uuid4(), task=uuid4())
    error(client.get(path, params={"limit": limit}), 422, "REQUEST_VALIDATION_ERROR")


def test_maxima_and_malformed_requests(api):
    client, _, _ = api
    p = create_project(client)
    t = create_task(client, p)
    for path in LIST_PATHS:
        path = path.format(project=p["id"], task=t["id"])
        maximum = 500 if path.endswith("timeline") else 200
        assert client.get(path, params={"limit": maximum}).status_code == 200
        error(client.get(path, params={"limit": maximum + 1}), 422, "REQUEST_VALIDATION_ERROR")
    error(client.get("/api/v1/tasks/synthetic-sensitive-uuid"), 422, "REQUEST_VALIDATION_ERROR")
    error(client.post("/api/v1/projects", content='{"name":"synthetic-sensitive-body",', headers={"Content-Type": "application/json"}), 422, "REQUEST_VALIDATION_ERROR")
    error(client.post("/api/v1/projects", json={"key": "a", "name": 123}), 422, "REQUEST_VALIDATION_ERROR")
    error(client.post("/api/v1/projects", json={"key": "BAD", "name": "A"}), 422, "INVALID_INPUT")
    error(client.patch(f"/api/v1/projects/{p['id']}", json={"name": " "}), 422, "INVALID_INPUT")
    error(client.get(f"/api/v1/projects/{uuid4()}"), 404, "PROJECT_NOT_FOUND")
    error(client.get(f"/api/v1/tasks/{uuid4()}"), 404, "TASK_NOT_FOUND")
    error(client.post(f"/api/v1/tasks/{t['id']}/run"), 409, "PROJECT_RUNTIME_NOT_CONFIGURED")
    error(client.post(f"/api/v1/tasks/{t['id']}/resume"), 409, "TASK_NOT_BLOCKED")


@pytest.mark.parametrize("code", list(ApplicationErrorCode))
def test_every_application_error_mapping_uses_code_only(api, monkeypatch, code):
    client, application, _ = api
    def failed(*args, **kwargs):
        exception = ApplicationError(code)
        exception.args = ("synthetic-sensitive-host-path-secret",)
        raise exception
    monkeypatch.setattr(application, "get_task_detail", failed)
    response = client.get(f"/api/v1/tasks/{uuid4()}")
    error(response, ERROR_MAPPING[code][0], code.value)
    assert response.json()["error"]["message"] == ERROR_MAPPING[code][1]
    assert "synthetic" not in response.text


def test_nested_persisted_evidence_serialization_and_gets_have_zero_effects(api, bundle, store_bundle, monkeypatch):
    client, application, factory = api
    with UnitOfWork(factory) as uow:
        store_bundle(uow, bundle)
        uow.commit()
    before = counts(factory)
    def forbidden(*args, **kwargs):
        raise AssertionError("GET cannot execute")
    monkeypatch.setattr(application._resolver, "resolve", forbidden)
    monkeypatch.setattr(WorkflowRunner, "run", forbidden)
    monkeypatch.setattr(WorkflowEngine, "transition", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    task = bundle["task"]
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/v1/projects").status_code == 200
    assert client.get(f"/api/v1/projects/{task.project_id}").status_code == 200
    assert client.get(f"/api/v1/projects/{task.project_id}/tasks").status_code == 200
    detail = client.get(f"/api/v1/tasks/{task.id}").json()
    assert detail["id"] == str(task.id) and detail["state"] == "CREATED"
    assert detail["created_at"].endswith("+07:00")
    for suffix in ("timeline", "artifacts", "test-runs", "errors", "decisions", "gates", "invocations"):
        response = client.get(f"/api/v1/tasks/{task.id}/{suffix}")
        assert response.status_code == 200, response.text
        assert response.json()["total_returned"] == 1
        assert response.json()["truncated"] is False
    artifact = client.get(f"/api/v1/tasks/{task.id}/artifacts").json()["items"][0]
    assert artifact["content"] == bundle["artifact"].content
    assert artifact["artifact_type"] == "IMPLEMENTATION"
    event = client.get(f"/api/v1/tasks/{task.id}/timeline").json()["items"][0]
    assert event["actor"] == {"type": "SYSTEM", "id": "qa"}
    assert event["correlation"]["artifact_id"] == str(bundle["artifact"].id)
    assert "input_context_refs" not in client.get(f"/api/v1/tasks/{task.id}/invocations").json()["items"][0]
    assert counts(factory) == before


def test_http_run_block_resume_continue_and_terminal_idempotence(api, tmp_path, monkeypatch):
    client, application, factory = api
    a, b = create_project(client), create_project(client, "b")
    ta, tb = create_task(client, a), create_task(client, b)
    ba = configure(application, a, tmp_path / "a", blocked=True)
    bb = configure(application, b, tmp_path / "b")
    bind(application, [ba, bb])
    assert client.post(f"/api/v1/tasks/{ta['id']}/run").json()["state"] == "BLOCKED"
    assert client.get(f"/api/v1/tasks/{tb['id']}").json()["state"] == "CREATED"
    before = counts(factory)
    assert client.post(f"/api/v1/tasks/{ta['id']}/run").json()["state"] == "BLOCKED"
    assert counts(factory) == before
    resumed = client.post(f"/api/v1/tasks/{ta['id']}/resume")
    assert resumed.status_code == 200 and resumed.json()["state"] == "RESEARCHING"
    assert counts(factory)["invocations"] == before["invocations"]
    for t in (ta, tb):
        response = client.post(f"/api/v1/tasks/{t['id']}/run")
        assert response.status_code == 200 and response.json()["state"] == "DONE"
        assert client.get(f"/api/v1/tasks/{t['id']}/timeline?limit=1").json()["truncated"]
    before = counts(factory)
    def forbidden(*args, **kwargs):
        raise AssertionError("Terminal/read endpoint cannot execute")
    for bundle in (ba, bb):
        monkeypatch.setattr(bundle.runtime, "run", forbidden)
        monkeypatch.setattr(bundle.test_provider, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    for t in (ta, tb):
        assert client.post(f"/api/v1/tasks/{t['id']}/run").json()["state"] == "DONE"
        assert client.get(f"/api/v1/tasks/{t['id']}").status_code == 200
    assert counts(factory) == before


def test_sensitive_actual_runner_failure_is_safe_and_durable(api, tmp_path, monkeypatch):
    client, application, factory = api
    p = create_project(client)
    t = create_task(client, p)
    bind(application, [configure(application, p, tmp_path / "target")])
    def stop(self, task_id):
        WorkflowEngine(factory).transition(task_id=task_id, to_state=S.RESEARCHING,
            reason_code="START", reason_details="Persisted before stop")
        raise RuntimeError("synthetic-sensitive-provider-credential-path")
    monkeypatch.setattr(WorkflowRunner, "run", stop)
    response = client.post(f"/api/v1/tasks/{t['id']}/run")
    error(response, 409, "RUNTIME_STOPPED")
    assert "synthetic" not in response.text
    assert client.get(f"/api/v1/tasks/{t['id']}").json()["state"] == "RESEARCHING"
    assert client.get(f"/api/v1/tasks/{t['id']}/decisions").json()["items"][0]["reason_code"] == "START"


def test_unexpected_transport_failure_is_generic(api, monkeypatch):
    client, application, _ = api
    def broken(*args, **kwargs):
        raise RuntimeError("synthetic-sensitive-transport-detail")
    monkeypatch.setattr(application, "list_projects", broken)
    with TestClient(client.app, raise_server_exceptions=False) as safe_client:
        response = safe_client.get("/api/v1/projects")
        error(response, 500, "INTERNAL_ERROR")
        assert "synthetic" not in response.text


def test_failed_terminal_run_has_no_execution(api, tmp_path, monkeypatch):
    client, application, factory = api
    p = create_project(client)
    t = create_task(client, p)
    bundle = configure(application, p, tmp_path / "target")
    bind(application, [bundle])
    task_id = UUID(t["id"])
    engine = WorkflowEngine(factory)
    engine.transition(task_id=task_id, to_state=S.BLOCKED, resume_state=S.RESEARCHING,
        reason_code="WAIT", reason_details="Host preparation")
    engine.transition(task_id=task_id, to_state=S.FAILED, reason_code="STOP", reason_details="Host stop")
    def forbidden(*args, **kwargs):
        raise AssertionError("FAILED run cannot execute")
    monkeypatch.setattr(bundle.runtime, "run", forbidden)
    monkeypatch.setattr(bundle.test_provider, "run", forbidden)
    assert client.post(f"/api/v1/tasks/{task_id}/run").json()["state"] == "FAILED"
    before = counts(factory)
    assert client.post(f"/api/v1/tasks/{task_id}/run").json()["state"] == "FAILED"
    assert counts(factory) == before


def test_two_real_project_bundles_and_read_endpoints_are_isolated(api, tmp_path, mock_openai, monkeypatch):
    from test_repository_workflow import setup, tool_turn, final, values, INITIAL, GUARDED
    from test_project_workflow import research, proposal
    from test_application_workflow import composition
    from qa_sentinel.domain.project import Project
    client, application, factory = api
    other = "def add(a, b):\n    return sum((a, b))\n# B\n"
    mock = mock_openai([tool_turn(), research(INITIAL), final(values()[A.PLANNER], A.PLANNER),
        proposal(INITIAL, "# A\n"), values()[A.REVIEWER],
        tool_turn(), research(other), final(values()[A.PLANNER], A.PLANNER),
        proposal(other, "# B\n"), values()[A.REVIEWER]])
    a = setup(factory, tmp_path / "a", mock, real_implementation=True, project=Project(key="a", name="A"))
    b = setup(factory, tmp_path / "b", mock, real_implementation=True, project=Project(key="b", name="B"))
    (b.root / "calculator.py").write_bytes(other.encode())
    prepared, bundles = composition(factory, [a, b])
    application._resolver = prepared._resolver
    assert client.post(f"/api/v1/tasks/{a.task.id}/run").json()["state"] == "DONE"
    assert len(mock.calls) == 5
    assert (b.root / "calculator.py").read_bytes() == other.encode()
    assert client.get(f"/api/v1/tasks/{b.task.id}/artifacts").json()["total_returned"] == 0
    assert client.post(f"/api/v1/tasks/{b.task.id}/run").json()["state"] == "DONE"
    assert not mock.queue and len(mock.calls) == 10
    assert (a.root / "calculator.py").read_bytes() == (GUARDED + "# A\n").encode()
    assert (b.root / "calculator.py").read_bytes() == (GUARDED + "# B\n").encode()
    before = counts(factory)
    files = {p: (p.read_bytes(), p.stat().st_mtime_ns) for h in (a, b) for p in h.root.rglob("*") if p.is_file()}
    def forbidden(*args, **kwargs):
        raise AssertionError("GET endpoints cannot call model/tool/mutator/process")
    for h in (a, b):
        monkeypatch.setattr(h.runtime, "run", forbidden)
        monkeypatch.setattr(h.reader, "execute", forbidden)
        monkeypatch.setattr(h.mutation, "build_snapshots", forbidden)
        monkeypatch.setattr(h.mutation, "apply", forbidden)
        monkeypatch.setattr(h.provider, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    for h in (a, b):
        assert client.get(f"/api/v1/tasks/{h.task.id}").json()["project_id"] == str(h.task.project_id)
        for suffix in ("timeline", "artifacts", "test-runs", "errors", "decisions", "gates", "invocations"):
            response = client.get(f"/api/v1/tasks/{h.task.id}/{suffix}")
            assert response.status_code == 200, response.text
            assert all(item["task_id"] == str(h.task.id) for item in response.json()["items"])
        assert client.post(f"/api/v1/tasks/{h.task.id}/run").json()["state"] == "DONE"
    assert counts(factory) == before and len(mock.calls) == 10
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files} == files


@pytest.mark.parametrize("component", ["repository_service", "mutation_service", "test_provider"])
def test_http_wrong_workspace_service_stops_before_calls(api, tmp_path, mock_openai, monkeypatch, component):
    from test_repository_workflow import setup
    from test_application_workflow import composition
    client, application, factory = api
    mock = mock_openai([])
    a = setup(factory, tmp_path / "a", mock, real_implementation=True)
    b = setup(factory, tmp_path / "b", mock, real_implementation=True)
    _, bundles = composition(factory, [a, b])
    wrong = replace(bundles[0], **{component: getattr(bundles[1], component)})
    bind(application, [wrong, bundles[1]])
    def forbidden(*args, **kwargs):
        raise AssertionError("Guard must prevent cross-project effects")
    for h in (a, b):
        monkeypatch.setattr(h.runtime, "run", forbidden)
        monkeypatch.setattr(h.reader, "execute", forbidden)
        monkeypatch.setattr(h.mutation, "build_snapshots", forbidden)
        monkeypatch.setattr(h.mutation, "apply", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    response = client.post(f"/api/v1/tasks/{a.task.id}/run")
    error(response, 409, "RUNTIME_STOPPED")
    assert not mock.calls
    assert client.get(f"/api/v1/tasks/{a.task.id}").json()["state"] == "CREATED"
    assert client.get(f"/api/v1/tasks/{a.task.id}/errors").json()["items"][0]["error_type"] == "WORKFLOW_ERROR"
    assert client.get(f"/api/v1/tasks/{b.task.id}/errors").json()["total_returned"] == 0


def test_api_import_boundary_and_single_use_case_routes():
    root = Path(__file__).resolve().parents[2] / "src/qa_sentinel"
    forbidden = ("qa_sentinel.persistence", "qa_sentinel.orchestration", "qa_sentinel.domain",
        "qa_sentinel.agents", "qa_sentinel.execution", "qa_sentinel.mutation", "qa_sentinel.repository", "sqlalchemy")
    for path in (root / "api").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(forbidden), path
            elif isinstance(node, ast.Import):
                assert all(not alias.name.startswith(forbidden) for alias in node.names), path
        if path.name in {"projects.py", "tasks.py"}:
            for node in tree.body:
                if isinstance(node, ast.FunctionDef):
                    calls = [call for call in ast.walk(node) if isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == "application"]
                    assert len(calls) == 1, node.name
    for path in root.rglob("*.py"):
        # Task 16 adds a composition layer above API; core/application stay independent.
        if path.relative_to(root).parts[0] not in {"api", "host"}:
            assert "qa_sentinel.api" not in path.read_text(), path
