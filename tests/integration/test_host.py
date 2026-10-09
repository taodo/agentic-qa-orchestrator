"""Offline, socket-free host/CLI proof using migrated temporary state and ASGI."""
import asyncio
import ast
import json
import socket
import subprocess
import sys
from pathlib import Path
from uuid import UUID
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from qa_sentinel.host import cli, composition, database
from qa_sentinel.host.config import HostConfig, HostError, LocalProjectConfig, load_local_config
from qa_sentinel.host.web import create_host_app
from qa_sentinel.host.admission import ExecutionAdmission
from qa_sentinel.application import ApplicationError
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from qa_sentinel.agents.real import RealAgentRuntime
from qa_sentinel.models.config import RoleModelConfig
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.domain.project import Project


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    original = socket.socket.connect
    def forbidden(*args, **kwargs):
        raise AssertionError("Host tests must not use network, real models or subprocesses")
    def connect(sock, address):
        fallback = getattr(socket, "_fallback_socketpair", None)
        if fallback is not None and sys._getframe(1).f_code is fallback.__code__:
            return original(sock, address)  # Windows asyncio private wakeup only.
        return forbidden(sock, address)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(OpenAIModelAdapter, "generate", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


@pytest.fixture
def config(tmp_path):
    dist = tmp_path / "frontend-dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<!doctype html><div id="root">Built frontend</div>', encoding="utf-8")
    (dist / "assets" / "app.js").write_text('console.log("built fixture")', encoding="utf-8")
    return HostConfig(mode="demo", database=tmp_path / "state" / "host.sqlite3", frontend_dist=dist)


def local(config, tmp_path, *, key="real-project"):
    root = tmp_path / key
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "test_example.py").write_text("def test_example(): assert True", encoding="utf-8")
    project = LocalProjectConfig(key=key, workspace_root=root, pytest_targets=("tests",))
    return HostConfig(mode="local", database=config.database, frontend_dist=config.frontend_dist, projects=(project,))


def seed(config, key):
    engine, factory = database.bootstrap_database(config.database)
    try:
        with UnitOfWork(factory) as uow:
            project = Project(key=key, name="Real project")
            uow.projects.add(project); uow.commit()
            return project.id
    finally:
        engine.dispose()


def test_cli_help(capsys):
    with pytest.raises(SystemExit) as exit:
        cli.main(["serve", "--help"])
    assert exit.value.code == 0
    output = capsys.readouterr().out
    assert "--demo" in output and "--config" in output and "loopback" in output


@pytest.mark.parametrize("args", [[], ["serve"], ["serve", "--demo", "--config", "x.json"],
    ["serve", "--demo", "--host", "0.0.0.0"], ["serve", "--demo", "--host", "localhost"], ["serve", "--demo", "--workers", "2"]])
def test_invalid_cli_combinations(args):
    with pytest.raises(SystemExit) as exit:
        cli.main(args)
    assert exit.value.code != 0


def test_cli_defaults_and_single_process(config, monkeypatch, capsys):
    monkeypatch.setenv("WEB_CONCURRENCY", "8")
    monkeypatch.setenv("UVICORN_HOST", "0.0.0.0")
    monkeypatch.setenv("OPENAI_API_KEY", "SYNTHETIC_SECRET_DO_NOT_OUTPUT")
    import uvicorn
    calls = []
    def run(app, **kwargs):
        calls.append(kwargs)
        with TestClient(app) as client:
            assert client.get("/health").json() == {"status": "ok"}
    monkeypatch.setattr(uvicorn, "run", run)
    assert cli.main(["serve", "--demo", "--database", str(config.database), "--frontend-dist", str(config.frontend_dist)]) == 0
    assert calls == [dict(host="127.0.0.1", port=8000, workers=1, reload=False, access_log=False,
        log_level="warning", proxy_headers=False, ws="none", loop="asyncio", http="h11")]
    output = capsys.readouterr()
    assert "demo mode" in output.out and "SYNTHETIC_SECRET" not in output.out + output.err
    assert b"SYNTHETIC_SECRET" not in config.database.read_bytes()


def test_safe_cli_startup_failure(config, capsys):
    assert cli.main(["serve", "--demo", "--frontend-dist", str(config.frontend_dist / "missing")]) == 1
    assert "HOST_FRONTEND_BUILD_MISSING" in capsys.readouterr().err


def test_demo_full_stack_without_key(config, monkeypatch):
    # This smoke test exercises synchronous Run, not queue polling. Keep the idle
    # worker parked so its empty claim cannot transiently own workflow admission.
    monkeypatch.setattr(composition.ExecutionWorker, "_loop", lambda worker: worker._stop.wait())
    app = create_host_app(config)
    with TestClient(app) as client:
        assert client.get("/").text.startswith("<!doctype html>")
        projects = client.get("/api/v1/projects").json()["items"]
        assert len(projects) == 1 and projects[0]["key"] == "demo-calculator"
        assert "workspace_root" not in projects[0]
        project_id = projects[0]["id"]
        bundle = app.state.host_composition.resolver.resolve(UUID(project_id))
        assert bundle.binding.workspace_root == config.database.parent / "demo-workspace"
        assert bundle.repository_service is None and bundle.mutation_service is None
        task = client.post(f"/api/v1/projects/{project_id}/tasks", json={"title": "Division", "requirement": "Add division support and reject division by zero."}).json()
        response = client.post(f"/api/v1/tasks/{task['id']}/run")
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "DONE"
        assert client.get(f"/api/v1/tasks/{task['id']}").json()["state"] == "DONE"
        for section in ("timeline", "artifacts", "invocations", "test-runs", "gates", "decisions"):
            assert client.get(f"/api/v1/tasks/{task['id']}/{section}").json()["total_returned"] > 0
        assert client.get(f"/api/v1/tasks/{task['id']}/test-runs").json()["items"][0]["environment"] == "fake"
        # Other Projects remain inspectable but receive no implicit demo runtime.
        other = client.post("/api/v1/projects", json={"key": "operator-project", "name": "Operator"}).json()
        foreign = client.post(f"/api/v1/projects/{other['id']}/tasks", json={"title": "Other", "requirement": "Other"}).json()
        assert client.post(f"/api/v1/tasks/{foreign['id']}/run").json()["error"]["code"] == "PROJECT_RUNTIME_NOT_CONFIGURED"


def test_restart_migrates_to_head_preserves_operator_data_and_demo_identity(config):
    with TestClient(create_host_app(config)) as client:
        project = client.get("/api/v1/projects").json()["items"][0]
        client.post("/api/v1/projects", json={"key": "operator", "name": "Keep me"})
        created = client.post(f"/api/v1/projects/{project['id']}/tasks", json={"title": "Keep task", "requirement": "Division"}).json()
    app = create_host_app(config)
    with TestClient(app) as client:
        projects = client.get("/api/v1/projects").json()["items"]
        assert len(projects) == 2 and [p for p in projects if p["key"] == "demo-calculator"][0]["id"] == project["id"]
        assert client.get(f"/api/v1/tasks/{created['id']}").json()["title"] == "Keep task"
        with app.state.host_composition.engine.connect() as connection:
            assert connection.execute(text("select version_num from alembic_version")).scalar_one() == "0011"


@pytest.mark.parametrize("path", ["/", "/projects", "/projects/project-a", "/tasks/task-a?view=artifacts", "/index.html"])
def test_spa_routes(config, path):
    with TestClient(create_host_app(config)) as client:
        assert client.get(path).text == (config.frontend_dist / "index.html").read_text()


@pytest.mark.parametrize("path", ["/api/v1/missing", "/api/missing", "/health/missing", "/openapi.json/missing", "/docs/missing", "/redoc/missing", "/assets/missing.js", "/missing.js", "/unknown", "/.env", "/assets/.secret.js", "/assets/config.json", "/assets/../../host.sqlite3", "/assets/%2e%2e/%2e%2e/secret.txt", "/assets/%252e%252e/secret.js", "/assets/%5c..%5csecret.js"])
def test_fallback_never_masks_api_assets_or_traversal(config, path):
    (config.database.parent).mkdir(parents=True, exist_ok=True)
    (config.database.parent / "secret.txt").write_text("OUTSIDE_SECRET")
    with TestClient(create_host_app(config)) as client:
        response = client.get(path)
        assert response.status_code == 404, (path, response.text)
        assert "Built frontend" not in response.text and "OUTSIDE_SECRET" not in response.text


@pytest.mark.parametrize("suffix", ["", "/requirements?requirement_id=revised-v2", "/test-specifications?test_spec_id=test-a", "/traceability", "/readiness", "/runs", "/runs/run-a", "/requirements/"])
@pytest.mark.parametrize("mode", ["demo", "local"])
def test_campaign_spa_deep_links(config, tmp_path, monkeypatch, suffix, mode):
    value = config
    if mode == "local":
        value = local(config, tmp_path)
        seed(config, "real-project")
        monkeypatch.setenv("OPENAI_API_KEY", "SYNTHETIC_LOCAL_KEY")
    with TestClient(create_host_app(value)) as client:
        path = "/projects/project-a/campaigns/campaign-a" + suffix
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.text == (config.frontend_dist / "index.html").read_text()
        assert client.head(path).status_code == 200


@pytest.mark.parametrize("path", [
    "/projects/project-a/campaigns", "/projects/project-a/campaigns/campaign-a/unknown",
    "/projects/project-a/campaigns/campaign-a/requirements/extra",
    "/projects/project-a/campaigns/campaign-a/runs/run-a/extra",
    "/projects/project-a/campaigns/campaign-a/api/v1/missing",
    "/api/projects/project-a/campaigns/campaign-a/requirements",
    "/api/v1/projects/project-a/campaigns/campaign-a/unknown",
])
def test_campaign_fallback_remains_narrow(config, path):
    with TestClient(create_host_app(config)) as client:
        response = client.get(path)
        assert response.status_code == 404
        assert response.json() == {"error": {"code": "HTTP_ERROR", "message": "Route not found"}}
        assert "Built frontend" not in response.text


def test_assets_api_health_schema_and_no_cors(config):
    with TestClient(create_host_app(config)) as client:
        assert client.get("/assets/app.js").status_code == 200
        assert client.head("/assets/app.js").status_code == 200
        assert client.get("/health").json() == {"status": "ok"}
        assert "/api/v1/tasks/{task_id}/run" in client.get("/openapi.json").json()["paths"]
        assert client.get("/docs").status_code == 200 and client.get("/redoc").status_code == 200
        assert client.post("/projects").status_code == 405
        assert client.get("/api/v1/tasks/not-uuid").status_code == 422
        assert not client.app.debug
        assert "access-control-allow-origin" not in client.options("/api/v1/projects", headers={"Origin": "https://untrusted.example"}).headers


def test_missing_frontend_fails_before_database_or_seed(config, monkeypatch):
    (config.frontend_dist / "index.html").unlink()
    with pytest.raises(HostError, match="HOST_FRONTEND_BUILD_MISSING"):
        create_host_app(config)
    assert not config.database.exists() and not (config.database.parent / "demo-workspace").exists()


def test_migration_failure_aborts_composition(config, monkeypatch):
    def fail(*args): raise RuntimeError("SECRET_MIGRATION_DETAILS")
    monkeypatch.setattr(database.command, "upgrade", fail)
    with pytest.raises(HostError, match="HOST_DATABASE_STARTUP_FAILED") as error:
        create_host_app(config)
    assert "SECRET" not in str(error.value)
    assert not (config.database.parent / "demo-workspace").exists()


def test_real_local_binding_and_services(config, tmp_path, monkeypatch):
    value = local(config, tmp_path)
    owner = seed(config, "real-project")
    monkeypatch.setenv("OPENAI_API_KEY", "SYNTHETIC_LOCAL_KEY")
    composed = composition.compose(value)
    try:
        from qa_sentinel.agents.requirement_extraction import RequirementExtractor
        assert isinstance(composed.application._requirement_extractor, RequirementExtractor)
        assert isinstance(composed.application._test_generator, composition.TestSpecificationGenerator)
        bundle = composed.resolver.resolve(owner)
        root = value.projects[0].workspace_root
        assert bundle.binding.project_id == owner and bundle.binding.workspace_root == root
        assert bundle.repository_service.config.repository_root == root
        assert bundle.mutation_service.config.workspace_root == root
        assert not bundle.mutation_service.config.allow_host_workspace
        provider = bundle.test_provider
        assert provider.workspace_root == root and provider.workspace_binding == bundle.binding
        assert provider.request.args == ("-m", "pytest", "tests")
        assert provider.request.cwd == str(root) and not provider.request.environment
        assert isinstance(bundle.runtime, RealAgentRuntime) and isinstance(bundle.runtime.adapter, OpenAIModelAdapter)
        assert bundle.runtime.repository_tools and bundle.runtime.config == RoleModelConfig()
    finally: composed.close()


def test_local_missing_key_and_project_fail_closed(config, tmp_path, monkeypatch):
    value = local(config, tmp_path)
    with pytest.raises(HostError, match="HOST_MODEL_KEY_REQUIRED"): composition.compose(value)
    assert not config.database.exists()
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    with pytest.raises(HostError, match="HOST_PROJECT_NOT_FOUND"): composition.compose(value)


@pytest.mark.parametrize("targets", [("tests; rm",), ("-q",), ("--rootdir=/",), ("missing.py",), ("../outside.py",), ("tests|echo",)])
def test_target_policy_not_weakened(config, tmp_path, monkeypatch, targets):
    value = local(config, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    try:
        project = LocalProjectConfig(key="real-project", workspace_root=value.projects[0].workspace_root, pytest_targets=targets)
    except ValidationError:
        return
    with pytest.raises(HostError, match="HOST_TEST_POLICY_REJECTED"):
        composition.compose(HostConfig(mode="local", database=value.database, frontend_dist=value.frontend_dist, projects=(project,)))
    assert not value.database.exists()


def test_config_validation_and_json_relative_host_paths(config, tmp_path):
    value = local(config, tmp_path)
    path = tmp_path / "qa-sentinel.local.json"
    data = {"database": "state/host.sqlite3", "frontend_dist": "frontend-dist", "projects": [value.projects[0].model_dump(mode="json")]}
    path.write_text(json.dumps(data))
    loaded = load_local_config(path)
    assert loaded.database == config.database and loaded.projects == value.projects
    for invalid in ({**data, "api_key": "secret"}, {**data, "port": 0}, {**data, "host": "0.0.0.0"}, {**data, "projects": [data["projects"][0]] * 2}, {**data, "mode": "demo"}):
        path.write_text(json.dumps(invalid))
        with pytest.raises(HostError, match="HOST_CONFIG_INVALID"): load_local_config(path)
    path.write_text('{"database":"x","database":"y"}')
    with pytest.raises(HostError): load_local_config(path)


def test_unknown_project_options_and_bad_paths(config, tmp_path):
    for root in (tmp_path / "missing", Path("relative")):
        with pytest.raises(ValidationError): LocalProjectConfig(key="a", workspace_root=root, pytest_targets=("tests",))
    with pytest.raises(ValidationError): LocalProjectConfig(key="a", workspace_root=tmp_path, pytest_targets=())
    with pytest.raises(ValidationError): LocalProjectConfig(key="a", workspace_root=tmp_path, pytest_targets=("tests",), command="echo")
    file = tmp_path / "file"; file.write_text("file")
    with pytest.raises(ValidationError): HostConfig(mode="demo", database=file / "state.db", frontend_dist=config.frontend_dist)
    with pytest.raises(ValidationError): HostConfig(mode="demo", database=config.frontend_dist / "state.db", frontend_dist=config.frontend_dist)
    with pytest.raises(ValidationError): HostConfig(mode="demo", database=config.database, frontend_dist=config.frontend_dist, port=True)
    with pytest.raises(ValidationError): config.port = 9999


def test_overlapping_targets_and_host_override_rejected(config, tmp_path, monkeypatch):
    value = local(config, tmp_path)
    nested = value.projects[0].workspace_root / "nested"; nested.mkdir()
    second = LocalProjectConfig(key="b", workspace_root=nested, pytest_targets=(".",))
    with pytest.raises(ValidationError): HostConfig(mode="local", database=value.database, frontend_dist=value.frontend_dist, projects=(*value.projects, second))
    host_root = Path(__file__).resolve().parents[2]
    target = LocalProjectConfig(key="host", workspace_root=host_root, pytest_targets=("tests",))
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    with pytest.raises(HostError, match="HOST_COMPOSITION_FAILED"):
        composition.compose(HostConfig(mode="local", database=config.database, frontend_dist=config.frontend_dist, projects=(target,)))


def test_static_symlink_escape_is_denied(config, tmp_path):
    outside = tmp_path / "outside.js"; outside.write_text("OUTSIDE_SECRET")
    link = config.frontend_dist / "assets" / "linked.js"
    try: link.symlink_to(outside)
    except OSError: pytest.skip("Windows symlink privilege unavailable")
    with TestClient(create_host_app(config)) as client:
        assert client.get("/assets/linked.js").status_code == 404
    with pytest.raises(ValidationError): HostConfig(mode="demo", database=link, frontend_dist=config.frontend_dist)


def test_exclusive_execution_rejects_overlap_without_calling_core():
    import threading
    entered, release = threading.Event(), threading.Event()
    guard = ExecutionAdmission()
    def first():
        with guard.task("task-a"):
            entered.set(); assert release.wait(5)
    thread = threading.Thread(target=first)
    thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(ApplicationError, match="RUNTIME_STOPPED"):
            with guard.task("task-b"):
                pytest.fail("Overlapping workflow entered core")
    finally:
        release.set(); thread.join(5)
    with guard.task("task-b"):
        pass


def test_host_dependency_direction():
    root = Path(__file__).resolve().parents[2] / "src" / "qa_sentinel"
    for path in root.rglob("*.py"):
        if path.relative_to(root).parts[0] == "host":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("qa_sentinel.host"), path
                assert not (node.level and (node.module or "").split(".")[0] == "host"), path
                assert not (node.level and node.module is None and any(alias.name == "host" for alias in node.names)), path
            elif isinstance(node, ast.Import):
                assert all(not alias.name.startswith("qa_sentinel.host") for alias in node.names), path
