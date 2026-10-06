"""Onboarding is read-only preflight plus explicit config publication, never execution."""
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from qa_sentinel.host import cli, composition, database, onboarding, preflight
from qa_sentinel.host.config import HostError, load_local_config
from qa_sentinel.host.status import RuntimeStatus
from qa_sentinel.host.web import create_host_app
from test_host import offline, config, local, seed


@pytest.fixture
def prepared(config, tmp_path):
    value = local(config, tmp_path)
    project_id = seed(value, "real-project")
    return value, project_id, tmp_path / "local.json"


def arguments(prepared, **overrides):
    config, _, output = prepared
    values = {"database": config.database, "frontend-dist": config.frontend_dist,
        "project-key": config.projects[0].key, "workspace": config.projects[0].workspace_root,
        "pytest-target": "tests", "config": output, **overrides}
    return ["local", "init", *(item for key, value in values.items() for item in ("--" + key, str(value)))]


def write_config(prepared, **overrides):
    config, _, path = prepared
    path.write_text(json.dumps({**config.model_dump(mode="json"), **overrides}), encoding="utf-8")
    return path


@pytest.mark.parametrize("command", ["init", "validate"])
def test_local_help(command, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["local", command, "--help"])
    assert exc.value.code == 0
    assert "--config" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["database", "frontend-dist", "project-key", "workspace", "pytest-target", "config"])
def test_init_requires_explicit_inputs(prepared, flag):
    args = arguments(prepared)
    index = args.index("--" + flag)
    del args[index:index + 2]
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2
    assert not prepared[2].exists()


def test_missing_project_never_created(prepared, capsys):
    assert cli.main(arguments(prepared, **{"project-key": "unknown"})) == 1
    assert "HOST_PROJECT_NOT_FOUND" in capsys.readouterr().err
    assert not prepared[2].exists()
    with sqlite3.connect(prepared[0].database) as connection:
        assert connection.execute("select key from projects").fetchall() == [("real-project",)]


def test_init_valid_deterministic_secret_free_and_loadable(prepared, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret-key-not-output")
    monkeypatch.setenv("QA_SENTINEL_PREVIEW_PASSWORD", "synthetic-preview-not-output")
    assert cli.main(arguments(prepared)) == 0
    raw = prepared[2].read_bytes()
    assert raw.endswith(b"\n") and b"\r" not in raw
    data = json.loads(raw)
    assert set(data) == {"database", "frontend_dist", "projects", "host", "port"}
    assert set(data["projects"][0]) == {"key", "workspace_root", "pytest_targets"}
    assert load_local_config(prepared[2]) == prepared[0]
    assert data["host"] == "127.0.0.1"
    output = capsys.readouterr()
    assert "PRESENT" in output.out and "Overall: READY" in output.out
    assert b"synthetic-secret" not in raw and b"synthetic-preview" not in raw
    assert "synthetic-secret" not in output.out + output.err
    assert b"synthetic-secret" not in prepared[0].database.read_bytes()
    assert cli.main([*arguments(prepared), "--overwrite"]) == 0
    assert prepared[2].read_bytes() == raw


def test_init_missing_key_is_allowed_but_validate_not_ready(prepared, capsys):
    assert cli.main(arguments(prepared)) == 0
    assert "OPENAI_API_KEY: MISSING" in capsys.readouterr().out
    assert cli.main(["local", "validate", "--config", str(prepared[2])]) == 1
    assert "Overall: NOT READY" in capsys.readouterr().out


def test_existing_config_requires_overwrite(prepared, capsys):
    path = write_config(prepared)
    before = path.read_bytes()
    assert cli.main(arguments(prepared)) == 1
    assert "HOST_CONFIG_EXISTS" in capsys.readouterr().err
    assert path.read_bytes() == before
    assert cli.main([*arguments(prepared), "--overwrite"]) == 0
    assert load_local_config(path) == prepared[0]


def test_overwrite_does_not_replace_unrelated_json(prepared):
    prepared[2].write_text('{"unrelated": true}')
    assert cli.main([*arguments(prepared), "--overwrite"]) == 1
    assert json.loads(prepared[2].read_text()) == {"unrelated": True}


def test_parent_creation_is_explicit(prepared):
    target = prepared[2].parent / "chosen" / "local.json"
    assert cli.main(arguments(prepared, config=target)) == 1
    assert not target.parent.exists()
    assert cli.main([*arguments(prepared, config=target), "--create-parent"]) == 0
    assert load_local_config(target) == prepared[0]


@pytest.mark.parametrize("target", ["missing", "../outside", "tests;echo", "tests|echo", "--collect-only", "tests::case"])
def test_invalid_targets_rejected_without_execution(prepared, target):
    args = arguments(prepared, **{"pytest-target": target})
    index = args.index("--pytest-target")
    args[index:index + 2] = [f"--pytest-target={target}"]
    assert cli.main(args) == 1
    assert not prepared[2].exists()


def test_multiple_explicit_targets(prepared):
    assert cli.main([*arguments(prepared), "--pytest-target", "tests/test_example.py::test_example"]) == 0
    assert load_local_config(prepared[2]).projects[0].pytest_targets == ("tests", "tests/test_example.py::test_example")


@pytest.mark.parametrize("workspace", ["missing", "relative", "frontend", "host-source"])
def test_workspace_boundaries(prepared, workspace):
    config, _, output = prepared
    roots = {"missing": output.parent / "missing", "relative": Path("tests"),
        "frontend": config.frontend_dist, "host-source": Path(__file__).resolve().parents[2]}
    assert cli.main(arguments(prepared, workspace=roots[workspace])) == 1
    assert not output.exists()


@pytest.mark.parametrize("change", ["external", "duplicate", "overlap", "env", "command", "preview", "unknown"])
def test_validate_reuses_host_contract_and_identity(prepared, change, capsys):
    config, _, _ = prepared
    project = config.projects[0].model_dump(mode="json")
    values = {"external": {"host": "0.0.0.0"}, "duplicate": {"projects": [project, project]},
        "overlap": {"projects": [project, {**project, "key": "other", "workspace_root": str(config.projects[0].workspace_root / "tests")}]},
        "env": {"environment": {"OPENAI_API_KEY": "secret-input-never-output"}},
        "command": {"command": "shell"}, "preview": {"mode": "preview-demo"},
        "unknown": {"projects": [{**project, "key": "unknown"}]}}
    path = write_config(prepared, **values[change])
    assert cli.main(["local", "validate", "--config", str(path)]) == 1
    output = capsys.readouterr()
    assert "NOT READY" in output.err and "secret-input" not in output.err + output.out


@pytest.mark.parametrize("what", ["database", "frontend", "workspace", "targets"])
def test_validate_missing_prerequisites(prepared, what):
    config, _, _ = prepared
    if what == "database": config.database.unlink()
    elif what == "frontend": (config.frontend_dist / "index.html").unlink()
    elif what == "workspace":
        root = config.projects[0].workspace_root
        (root / "tests" / "test_example.py").unlink(); (root / "tests").rmdir(); root.rmdir()
    else: (config.projects[0].workspace_root / "tests" / "test_example.py").unlink(); (config.projects[0].workspace_root / "tests").rmdir()
    path = write_config(prepared)
    assert cli.main(["local", "validate", "--config", str(path)]) == 1
    if what == "database": assert not config.database.exists()


@pytest.mark.parametrize("key,present", [(None, False), (" \t", False), ("synthetic-private-key", True)])
def test_key_presence_and_no_actions_during_validation(prepared, monkeypatch, capsys, key, present):
    config, _, _ = prepared
    path = write_config(prepared)
    root = config.projects[0].workspace_root
    source = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    state = config.database.read_bytes()
    if key is not None: monkeypatch.setenv("OPENAI_API_KEY", key)
    def forbidden(*args, **kwargs): raise AssertionError("Validation must not execute or write")
    for obj, method in [(composition.OpenAIModelAdapter, "__init__"), (composition.RealAgentRuntime, "__init__"),
        (composition.TestExecutionService, "__init__"), (composition.CommandRunner, "__init__"),
        (composition.PytestRunner, "__init__"), (preflight.MutationService, "apply"),
        (preflight.MutationService, "build_snapshots"), (preflight.RepositoryReadService, "execute"),
        (database, "bootstrap_database"), (cli, "create_host_app"),
        (Path, "write_text"), (Path, "write_bytes"), (onboarding.os, "replace"), (onboarding.os, "link")]:
        monkeypatch.setattr(obj, method, forbidden)
    assert cli.main(["local", "validate", "--config", str(path)]) == (0 if present else 1)
    report = capsys.readouterr()
    for label in ("Project identity: FOUND", "Workspace: VALID", "Repository read boundary: VALID",
        "Mutation boundary: VALID", "Pytest targets: VALID", "Frontend build: FOUND", "Database: READY"):
        assert label in report.out
    assert f"OPENAI_API_KEY: {'PRESENT' if present else 'MISSING'}" in report.out
    assert "synthetic-private-key" not in report.out + report.err
    assert config.database.read_bytes() == state
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == source


def test_validation_database_connection_is_enforced_read_only(prepared, monkeypatch):
    config, _, _ = prepared
    from qa_sentinel.persistence.repositories import ProjectRepository
    original = ProjectRepository.get_by_key
    def checked(repository, key):
        with pytest.raises(Exception, match="readonly"):
            repository.session.execute(onboarding.text("update projects set name='changed'"))
        return original(repository, key)
    monkeypatch.setattr(ProjectRepository, "get_by_key", checked)
    assert onboarding.validate_local(config).project_keys == ("real-project",)


def test_atomic_publish_failure_keeps_original_and_cleans_temporary(prepared, monkeypatch):
    path = write_config(prepared)
    original = path.read_bytes()
    def fail(*args): raise OSError("private-path-must-not-output")
    monkeypatch.setattr(onboarding.os, "replace", fail)
    assert cli.main([*arguments(prepared), "--overwrite"]) == 1
    assert path.read_bytes() == original
    assert not list(path.parent.glob(".qa-sentinel-config-*"))


def test_exclusive_publication_never_overwrites_racing_creator(prepared, monkeypatch):
    path = prepared[2]
    original = onboarding.os.link
    def race(source, target):
        path.write_text("racing creator")
        return original(source, target)
    monkeypatch.setattr(onboarding.os, "link", race)
    assert cli.main(arguments(prepared)) == 1
    assert path.read_text() == "racing creator"
    assert not list(path.parent.glob(".qa-sentinel-config-*"))


@pytest.mark.parametrize("destination", ["workspace", "frontend", "database", "git", "credentials"])
def test_output_cannot_mutate_sources_or_sensitive_host_files(prepared, destination):
    config, _, path = prepared
    paths = {"workspace": config.projects[0].workspace_root / "config.json", "frontend": config.frontend_dist / "config.json",
        "database": config.database, "git": path.parent / ".git" / "config.json", "credentials": path.parent / "credentials.json"}
    target = paths[destination]
    assert cli.main([*arguments(prepared, config=target), "--create-parent", "--overwrite"]) == 1
    if destination != "database": assert not target.exists()


def test_linked_config_path_rejected(prepared):
    target = prepared[2].parent / "other.json"
    target.write_text("keep")
    try: prepared[2].symlink_to(target)
    except OSError: pytest.skip("Symlink creation unavailable")
    assert cli.main([*arguments(prepared), "--overwrite"]) == 1
    assert target.read_text() == "keep"


def test_runtime_status_safe_typed_and_no_api_v1_change(prepared, monkeypatch):
    config, project_id, _ = prepared
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key-not-returned")
    with TestClient(create_host_app(config)) as client:
        response = client.get(f"/host/runtime-status/{project_id}")
        result = RuntimeStatus.model_validate(response.json())
        assert result.runtime_configured and result.model_ready and result.test_targets_configured
        assert result.project_key == "real-project" and result.project_id == project_id
        assert set(response.json()) == set(RuntimeStatus.model_fields)
        for hidden in (str(config.database), str(config.frontend_dist), str(config.projects[0].workspace_root), "synthetic-key-not-returned"):
            assert hidden not in response.text
        other = client.post("/api/v1/projects", json={"key": "other", "name": "Other"}).json()
        assert not client.get(f"/host/runtime-status/{other['id']}").json()["runtime_configured"]
        monkeypatch.delenv("OPENAI_API_KEY")
        assert not client.get(f"/host/runtime-status/{project_id}").json()["model_ready"]
        assert client.get(f"/host/runtime-status/{uuid4()}").status_code == 404
        assert client.get("/host/runtime-status/not-a-uuid").status_code == 422
        assert client.get("/host/missing").status_code == 404
        assert client.post(f"/host/runtime-status/{project_id}").status_code == 404
        from qa_sentinel.api import create_api_app
        original = create_api_app(client.app.state.host_composition.application).openapi()["paths"]
        current = client.get("/openapi.json").json()["paths"]
        assert {k: v for k, v in current.items() if k.startswith("/api/v1")} == {k: v for k, v in original.items() if k.startswith("/api/v1")}


@pytest.mark.parametrize("mode", ["demo", "preview-demo"])
def test_fake_status_only_seeded_project_and_preview_protected(config, monkeypatch, mode):
    from test_preview import preview, header, USER, PASSWORD
    if mode == "preview-demo":
        monkeypatch.setenv("QA_SENTINEL_PREVIEW_USERNAME", USER)
        monkeypatch.setenv("QA_SENTINEL_PREVIEW_PASSWORD", PASSWORD)
        config = preview(config)
    def forbidden(*args, **kwargs): raise AssertionError("Status cannot inspect real environment readiness or execute")
    import qa_sentinel.host.status as status
    monkeypatch.setattr(status, "model_key_present", forbidden)
    monkeypatch.setattr(composition, "real_components", forbidden)
    with TestClient(create_host_app(config)) as client:
        headers = header() if mode == "preview-demo" else {}
        project = client.get("/api/v1/projects", headers=headers).json()["items"][0]
        path = f"/host/runtime-status/{project['id']}"
        if mode == "preview-demo": assert client.get(path).status_code == 401
        result = client.get(path, headers=headers)
        assert result.json() == {"mode": mode, "project_id": project["id"], "project_key": "demo-calculator",
            "runtime_configured": True, "model_ready": None, "test_targets_configured": False}
        assert USER not in result.text and PASSWORD not in result.text
        other = client.post("/api/v1/projects", headers=headers, json={"key": "other", "name": "Other"}).json()
        assert not client.get(f"/host/runtime-status/{other['id']}", headers=headers).json()["runtime_configured"]
