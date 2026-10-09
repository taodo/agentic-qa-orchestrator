"""Offline local-start composition; no real build/server/target/provider work."""
from pathlib import Path
import os
from types import SimpleNamespace
import sqlite3
import subprocess
import pytest
from qa_sentinel.host import cli, composition, database, onboarding, start
from qa_sentinel.host.config import HostError
from test_host import offline, config
from test_onboarding import prepared, write_config


def forbidden(*args, **kwargs):
    raise AssertionError("Startup must not migrate, execute tests or invoke providers")


@pytest.fixture
def no_actions(monkeypatch):
    monkeypatch.setattr(database.command, "upgrade", forbidden)
    monkeypatch.setattr(composition, "bootstrap_database", forbidden)
    monkeypatch.setattr(composition.CommandRunner, "run", forbidden)
    monkeypatch.setattr(composition.PytestRunner, "run", forbidden)
    monkeypatch.setattr(composition.OpenAIModelAdapter, "generate", forbidden)


def test_start_order_and_build_on_every_start(prepared, monkeypatch, no_actions, capsys):
    value, _, _ = prepared
    path = write_config(prepared)
    events = []
    monkeypatch.setenv("OPENAI_API_KEY", "private-synthetic-key")
    original = onboarding.validate_local
    def build(config):
        assert config == value
        events.append("build")
        return 0
    def validate(config):
        assert events[-1] == "build"
        events.append("validate")
        return original(config)
    def serve(config, **kwargs):
        assert config == value and kwargs == {"existing_database": True}
        events.append("serve")
        return 0
    monkeypatch.setattr(start, "build_frontend", build)
    monkeypatch.setattr(onboarding, "validate_local", validate)
    monkeypatch.setattr(cli, "serve_config", serve)
    state, content = value.database.read_bytes(), path.read_bytes()
    for _ in range(2):
        assert cli.main(["local", "start", "--config", str(path)]) == 0
    assert events == ["build", "validate", "serve"] * 2
    output = capsys.readouterr()
    assert "Overall: READY" in output.out and "private-synthetic" not in output.out + output.err
    assert path.read_bytes() == content and value.database.read_bytes() == state


@pytest.mark.parametrize("status", [2, 37, -9, 500])
def test_build_failure_stops_and_retains_exit_status(prepared, monkeypatch, no_actions, capsys, status):
    path = write_config(prepared)
    monkeypatch.setattr(start, "build_frontend", lambda config: status)
    monkeypatch.setattr(onboarding, "validate_local", forbidden)
    monkeypatch.setattr(cli, "serve_config", forbidden)
    assert cli.main(["local", "start", "--config", str(path)]) == (status if 1 <= status <= 255 else 1)
    output = capsys.readouterr()
    assert f"process exit status: {status}" in output.err
    assert "Validation/serve did not run" in output.err


@pytest.mark.parametrize("key", [None, "  "])
def test_missing_key_blocks_without_writes(prepared, monkeypatch, no_actions, capsys, key):
    path = write_config(prepared)
    state = prepared[0].database.read_bytes()
    if key is not None:
        monkeypatch.setenv("OPENAI_API_KEY", key)
    monkeypatch.setattr(start, "build_frontend", lambda config: 0)
    monkeypatch.setattr(cli, "serve_config", forbidden)
    assert cli.main(["local", "start", "--config", str(path)]) == 1
    output = capsys.readouterr()
    assert "OPENAI_API_KEY: MISSING" in output.out and "Overall: NOT READY" in output.out
    assert "current process environment" in output.err
    assert prepared[0].database.read_bytes() == state


@pytest.mark.parametrize("revision", ["0009", "0003", "secret-not-a-revision\x1b[31m"])
def test_stale_database_blocks_and_safe_current_required(prepared, monkeypatch, no_actions, capsys, revision):
    path = write_config(prepared)
    with sqlite3.connect(prepared[0].database) as connection:
        connection.execute("update alembic_version set version_num=?", (revision,))
    state = prepared[0].database.read_bytes()
    monkeypatch.setenv("OPENAI_API_KEY", "private-key")
    monkeypatch.setattr(start, "build_frontend", lambda config: 0)
    monkeypatch.setattr(cli, "serve_config", forbidden)
    assert cli.main(["local", "start", "--config", str(path)]) == 1
    output = capsys.readouterr()
    current = revision if revision.isdigit() else "UNAVAILABLE"
    assert f"Current: {current}" in output.err and "Required: 0011" in output.err
    assert "No migration was run automatically" in output.err
    assert "secret-not-a-revision" not in output.err and "private-key" not in output.err
    assert prepared[0].database.read_bytes() == state


@pytest.mark.parametrize("problem,code", [("project", "HOST_PROJECT_NOT_FOUND"), ("database", "HOST_LOCAL_DATABASE_NOT_READY"), ("targets", "HOST_TEST_POLICY_REJECTED")])
def test_authoritative_validation_blockers(prepared, monkeypatch, no_actions, capsys, problem, code):
    value, _, _ = prepared
    overrides = {}
    if problem == "project":
        overrides["projects"] = [{**value.projects[0].model_dump(mode="json"), "key": "absent"}]
    elif problem == "database":
        value.database.unlink()
    else:
        (value.projects[0].workspace_root / "tests" / "test_example.py").unlink()
        (value.projects[0].workspace_root / "tests").rmdir()
    path = write_config(prepared, **overrides)
    monkeypatch.setattr(start, "build_frontend", lambda config: 0)
    monkeypatch.setattr(cli, "serve_config", forbidden)
    assert cli.main(["local", "start", "--config", str(path)]) == 1
    assert code in capsys.readouterr().err
    if problem == "database":
        assert not value.database.exists()


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_start_actual_serve_composition_no_alembic(prepared, monkeypatch, no_actions, capsys, host):
    import uvicorn
    path = write_config(prepared, host=host, port=8765)
    monkeypatch.setenv("OPENAI_API_KEY", "private-synthetic-key")
    monkeypatch.setattr(start, "build_frontend", lambda config: 0)
    calls = []
    original = cli.create_host_app
    def create(config, **kwargs):
        assert kwargs == {"existing_database": True}
        app = original(config, **kwargs)
        original_close = app.state.host_composition.close
        def close():
            calls.append("closed")
            original_close()
        # Frozen composition: wrap lifetime through a simple proxy on app state.
        app.state.host_composition = SimpleNamespace(close=close)
        return app
    def run(app, **kwargs):
        calls.append(kwargs)
    monkeypatch.setattr(cli, "create_host_app", create)
    monkeypatch.setattr(uvicorn, "run", run)
    assert cli.main(["local", "start", "--config", str(path)]) == 0
    assert calls == [dict(host=host, port=8765, workers=1, reload=False, access_log=False,
        log_level="warning", proxy_headers=False, ws="none", loop="asyncio", http="h11"), "closed"]
    output = capsys.readouterr()
    label = f"[{host}]" if ":" in host else host
    assert f"http://{label}:8765" in output.out and "Press Ctrl+C" in output.out
    assert "private-synthetic-key" not in output.out + output.err
    with sqlite3.connect(prepared[0].database) as connection:
        assert connection.execute("select count(*) from tasks").fetchone()[0] == 0
        assert connection.execute("select count(*) from execution_jobs").fetchone()[0] == 0


def test_server_interrupt_still_closes(prepared, monkeypatch, no_actions):
    import uvicorn
    path = write_config(prepared)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    monkeypatch.setattr(start, "build_frontend", lambda config: 0)
    closed = []
    monkeypatch.setattr(cli, "create_host_app", lambda *args, **kwargs: SimpleNamespace(state=SimpleNamespace(host_composition=SimpleNamespace(close=lambda: closed.append(True)))))
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(uvicorn, "run", interrupt)
    assert cli.main(["local", "start", "--config", str(path)]) == 130
    assert closed == [True]


def test_schema_rechecked_in_non_migrating_composition(prepared, monkeypatch, no_actions):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    with sqlite3.connect(prepared[0].database) as connection:
        connection.execute("update alembic_version set version_num='0009'")
    with pytest.raises(database.SchemaNotReady):
        composition.compose(prepared[0], existing_database=True)


def test_existing_database_open_never_creates(tmp_path):
    path = tmp_path / "missing" / "state.db"
    with pytest.raises(HostError, match="HOST_LOCAL_DATABASE_NOT_READY"):
        database.open_existing_database(path)
    assert not path.parent.exists()


@pytest.mark.parametrize("arguments", [["--migrate"], ["--host", "0.0.0.0"], ["--command", "pytest"], ["--demo"]])
def test_start_has_no_escape_flags(arguments):
    with pytest.raises(SystemExit) as exc:
        cli.main(["local", "start", "--config", "local.json", *arguments])
    assert exc.value.code == 2


def test_expected_config_error_is_safe(tmp_path, capsys):
    path = tmp_path / "local.json"
    path.write_text('{"OPENAI_API_KEY":"sensitive-private-value"}')
    assert cli.main(["local", "start", "--config", str(path)]) == 1
    output = capsys.readouterr()
    assert "HOST_CONFIG_INVALID" in output.err and "Traceback" not in output.err
    assert "sensitive-private-value" not in output.out + output.err


@pytest.mark.parametrize("failure", [None, "timeout", "start", "interrupt"])
def test_fixed_build_boundary_cleanup_and_secrets(prepared, monkeypatch, failure):
    root = prepared[0].frontend_dist.parent
    monkeypatch.setattr(start, "frontend_directory", lambda config: root)
    monkeypatch.setattr(start, "build_argv", lambda: ["node", "npm-cli.js", "run", "build"])
    monkeypatch.setenv("OPENAI_API_KEY", "private-provider-key")
    monkeypatch.setenv("QA_SENTINEL_SESSION_SECRET", "private-session-secret")
    monkeypatch.setenv("NODE_OPTIONS", "malicious-option")
    monkeypatch.setenv("npm_config_script_shell", "malicious-shell")
    events = []
    class Process:
        returncode = None
        def wait(self, timeout):
            events.append(("wait", timeout))
            if timeout == start.BUILD_TIMEOUT_SECONDS:
                if failure == "timeout": raise subprocess.TimeoutExpired("private", timeout)
                if failure == "interrupt": raise KeyboardInterrupt()
                self.returncode = 23
            else:
                self.returncode = -9
            return self.returncode
        def poll(self): return self.returncode
        def kill(self): events.append("kill")
    def spawn(argv, **kwargs):
        assert argv == ["node", "npm-cli.js", "run", "build"]
        assert kwargs["cwd"] == root and kwargs["shell"] is False
        assert kwargs["stdin"] == kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        assert all(k not in kwargs["env"] for k in ("OPENAI_API_KEY", "QA_SENTINEL_SESSION_SECRET", "NODE_OPTIONS", "npm_config_script_shell"))
        if failure == "start": raise OSError("private-path-and-secret")
        events.append("spawn")
        return Process()
    monkeypatch.setattr(start.subprocess, "Popen", spawn)
    monkeypatch.setattr(start, "ProcessTree", lambda process: SimpleNamespace(close=lambda: events.append("tree closed")))
    if failure == "interrupt":
        with pytest.raises(KeyboardInterrupt): start.build_frontend(prepared[0])
    elif failure:
        with pytest.raises(HostError, match="HOST_LOCAL_BUILD_") as exc: start.build_frontend(prepared[0])
        assert "private" not in str(exc.value)
    else:
        assert start.build_frontend(prepared[0]) == 23
    if failure != "start":
        assert "tree closed" in events
        assert events[-1] == ("wait", 5)
        if failure: assert "kill" in events


def test_build_directory_rejects_configured_arbitrary_project(prepared):
    with pytest.raises(HostError, match="HOST_LOCAL_BUILD_CHECKOUT_REQUIRED"):
        start.frontend_directory(prepared[0])


def test_windows_uses_node_npm_cli_not_batch(monkeypatch, tmp_path):
    node = tmp_path / "Node with spaces" / "node.exe"
    node.parent.mkdir()
    node.write_text("")
    npm_cli = node.parent / "node_modules/npm/bin/npm-cli.js"
    npm_cli.parent.mkdir(parents=True)
    npm_cli.write_text("")
    # Avoid changing global os.name (Path/pytest platform handling).
    monkeypatch.setattr(start, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(start.shutil, "which", lambda name: str(node) if name == "node.exe" else None)
    assert start.build_argv() == [str(node), str(npm_cli), "run", "build"]
    npm_cli.unlink()
    with pytest.raises(HostError, match="HOST_LOCAL_BUILD_TOOLING_MISSING"):
        start.build_argv()


def test_posix_uses_fixed_npm_argv(monkeypatch):
    monkeypatch.setattr(start, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(start.shutil, "which", lambda name: "/trusted/npm" if name == "npm" else None)
    assert start.build_argv() == ["/trusted/npm", "run", "build"]


@pytest.mark.parametrize("name", ["state with spaces.sqlite3", "state%#?.sqlite3" if os.name != "nt" else "state%#-unicode-ü.sqlite3"])
def test_existing_database_uses_accepted_factory_and_safe_uri(prepared, tmp_path, name):
    from qa_sentinel.domain.project import Project
    from qa_sentinel.persistence.unit_of_work import UnitOfWork
    path = tmp_path / name
    path.write_bytes(prepared[0].database.read_bytes())
    engine, factory = database.open_existing_database(path)
    try:
        with UnitOfWork(factory) as uow:
            assert uow.projects.get_by_key("real-project") is not None
            uow.projects.add(Project(key="second-project", name="Second"))
            uow.commit()
        with UnitOfWork(factory) as uow:
            assert uow.projects.get_by_key("second-project") is not None
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        engine.dispose()


def test_database_disappearing_after_preflight_is_not_created(prepared, monkeypatch):
    path = prepared[0].database
    original = database.create_engine
    def race(url):
        path.unlink()
        return original(url)
    monkeypatch.setattr(database, "create_engine", race)
    with pytest.raises(HostError, match="HOST_LOCAL_DATABASE_NOT_READY"):
        database.open_existing_database(path)
    assert not path.exists()


def test_checkout_frontend_selected_without_config_directory_discovery():
    expected = Path(start.__file__).resolve().parents[3] / "frontend"
    assert start.frontend_directory(SimpleNamespace(frontend_dist=expected / "dist")) == expected


@pytest.mark.parametrize("code", ["HOST_LOCAL_BUILD_TIMEOUT", "HOST_LOCAL_BUILD_TOOLING_MISSING", "HOST_LOCAL_BUILD_START_FAILED"])
def test_build_expected_error_is_actionable_and_stops(prepared, monkeypatch, capsys, code):
    path = write_config(prepared)
    def fail(config): raise HostError(code)
    monkeypatch.setattr(start, "build_frontend", fail)
    monkeypatch.setattr(onboarding, "validate_local", forbidden)
    monkeypatch.setattr(cli, "serve_config", forbidden)
    assert cli.main(["local", "start", "--config", str(path)]) == 1
    output = capsys.readouterr()
    assert code in output.err and "Traceback" not in output.err


def test_start_help(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["local", "start", "--help"])
    assert exc.value.code == 0
    assert "--config" in capsys.readouterr().out
