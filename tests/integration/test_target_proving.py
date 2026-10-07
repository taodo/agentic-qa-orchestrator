"""Offline proving against prepared temporary repositories, never an operator checkout."""
import json
from pathlib import Path
import sqlite3
import subprocess
import pytest
from pydantic import ValidationError
from qa_sentinel.domain.project import Project
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.artifact import Artifact
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.host import cli, targets, preflight
from qa_sentinel.host.config import HostConfig, LocalProjectConfig, load_local_config
from qa_sentinel.execution.command_policy import ExecutionConfig
from qa_sentinel.execution.command_runner import CommandRunner
from qa_sentinel.execution.pytest_runner import PytestRunner
from qa_sentinel.execution.service import TestExecutionService as WorkflowTests
from qa_sentinel.projects import ProjectWorkspaceBinding


@pytest.fixture
def prepared_target(migrated_factory, tmp_path, monkeypatch):
    factory, engine, _ = migrated_factory
    database = Path(engine.url.database)
    root = tmp_path / "external repository"
    tests = root / "backend" / "tests"
    tests.mkdir(parents=True)
    (root / "frontend").mkdir()
    (root / "backend" / "app.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
    (tests / "test_app.py").write_text("import pytest\nfrom app import add\n"
        "def test_add(): assert add(2, 3) == 5\n"
        "def test_skip(): pytest.skip('synthetic skip')\n", encoding="utf-8")
    # A target's pytest config/ambient environment cannot inject unapproved options.
    (root / "backend" / "pytest.ini").write_text("[pytest]\naddopts = --unapproved-option\n")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--unapproved-option")
    project = Project(key="external", name="Temporary target")
    task = Task(project_id=project.id, title="Unrelated Task", requirement="Do not change workflow evidence")
    with UnitOfWork(factory) as uow:
        uow.projects.add(project)
        uow.tasks.add(task)
        uow.commit()
    # Test-only trusted dependency injection for the bundled Python test environment.
    # Product CLI exposes only a trusted native target interpreter, not import paths or environment overrides.
    original = targets.ExecutionConfig
    monkeypatch.setattr(targets, "ExecutionConfig", lambda root, **kw: original(root,
        python_path=(Path(pytest.__file__).resolve().parents[1],), **kw))
    return factory, database, root, project, task


@pytest.fixture
def no_workflow(monkeypatch):
    from qa_sentinel.mutation.service import MutationService
    from qa_sentinel.orchestration.implementation_execution import ControlledImplementationExecution
    from qa_sentinel.agents.real import RealAgentRuntime
    from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
    from qa_sentinel.orchestration.runner import WorkflowRunner
    from qa_sentinel.orchestration.workflow_engine import WorkflowEngine
    from qa_sentinel.repository.service import RepositoryReadService
    def forbidden(*args, **kwargs): pytest.fail("Proving used a workflow/model/mutation/source service")
    for cls, names in ((MutationService, ("__init__", "apply")),
        (ControlledImplementationExecution, ("__init__", "apply")), (RealAgentRuntime, ("__init__", "run")),
        (OpenAIModelAdapter, ("__init__", "generate")), (WorkflowRunner, ("run",)),
        (WorkflowEngine, ("transition",)), (WorkflowTests, ("execute",)),
        (RepositoryReadService, ("execute",))):
        for name in names: monkeypatch.setattr(cls, name, forbidden)


def arguments(prepared, command="target-check", **changes):
    _, database, root, project, _ = prepared
    values = {"database": database, "project-key": project.key, "workspace": root,
        "test-cwd": "backend", "pytest-target": "tests", **changes}
    return ["local", command, *(item for key, value in values.items() for item in ("--" + key, str(value)))]


def snapshot(database, root):
    with sqlite3.connect(database) as connection: database_dump = "\n".join(connection.iterdump())
    files = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    return database_dump, files


def test_cli_check_zero_execution_and_no_persistence(prepared_target, no_workflow, monkeypatch, capsys):
    _, database, root, _, _ = prepared_target
    before = snapshot(database, root)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("Dry check executed a process"))
    assert cli.main(arguments(prepared_target)) == 0
    output = capsys.readouterr()
    assert "TARGET_READY" in output.out and not output.err
    assert str(root) not in output.out and str(database) not in output.out
    assert snapshot(database, root) == before


@pytest.mark.parametrize("failing", [False, True])
def test_real_proving_pass_fail_skip_no_evidence_or_source_changes(prepared_target, no_workflow, capsys, failing):
    factory, database, root, _, task = prepared_target
    if failing:
        with (root / "backend" / "tests" / "test_app.py").open("a", encoding="utf-8") as stream:
            stream.write("def test_failure(): assert False, 'synthetic-secret-prose'\n")
    before = snapshot(database, root)
    assert cli.main(arguments(prepared_target, "target-test")) == int(failing)
    output = capsys.readouterr()
    assert f"Outcome: {'FAIL' if failing else 'PASS'}" in output.out
    assert f"Counts: passed=1 failed={int(failing)} skipped=1" in output.out
    assert "Counts reliable: YES" in output.out
    assert "synthetic-secret-prose" not in output.out and str(root) not in output.out
    assert snapshot(database, root) == before
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(task.id) == task
        assert not uow.history.list_events(task.id)
        assert not uow.history.list_test_runs(task.id)
        assert not uow.invocations.list_by_task(task.id)


def test_real_proving_no_secret_inheritance(prepared_target, no_workflow, monkeypatch, capsys):
    _, _, root, _, _ = prepared_target
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-forwarded")
    monkeypatch.setenv("QA_SENTINEL_SESSION_SECRET", "synthetic-not-forwarded")
    (root / "backend" / "tests" / "test_environment.py").write_text(
        "import os\ndef test_environment():\n"
        "    assert 'OPENAI_API_KEY' not in os.environ\n"
        "    assert 'QA_SENTINEL_SESSION_SECRET' not in os.environ\n"
        "    assert 'PYTEST_ADDOPTS' not in os.environ\n")
    assert cli.main(arguments(prepared_target, "target-test")) == 0
    assert "synthetic-not-forwarded" not in capsys.readouterr().out


def test_readonly_lookup_existing_project_by_id_missing_db_and_project(prepared_target, no_workflow, tmp_path):
    _, database, _, project, _ = prepared_target
    assert targets.lookup_project(database, project_id=project.id) == project
    assert targets.lookup_project(database, key=project.key) == project
    with pytest.raises(targets.TargetFailure, match="TARGET_PROJECT_NOT_FOUND"):
        targets.lookup_project(database, key="unknown")
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(targets.TargetFailure, match="TARGET_DATABASE_NOT_READY"):
        targets.lookup_project(missing, key=project.key)
    assert not missing.exists()


@pytest.mark.parametrize("changes,code", [({"project-key": "unknown"}, "TARGET_PROJECT_NOT_FOUND"),
    ({"test-cwd": "../outside"}, "TARGET_PROFILE_INVALID"),
    ({"pytest-target": "-m pip"}, "TARGET_PROFILE_INVALID"),
    ({"test-cwd": "missing"}, "TARGET_TEST_CWD_INVALID")])
def test_cli_invalid_values_are_fixed_and_never_execute(prepared_target, no_workflow, monkeypatch, capsys, changes, code):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("Invalid CLI executed pytest"))
    assert cli.main(arguments(prepared_target, **changes)) == 1
    output = capsys.readouterr()
    assert code in output.out and len(output.out) < 150
    assert str(prepared_target[2]) not in output.out


def test_host_database_must_stay_outside_target(prepared_target, no_workflow, monkeypatch, capsys):
    _, database, _, project, _ = prepared_target
    # Lookup is inert but execution of a target containing host persistence is forbidden.
    monkeypatch.setattr(targets, "lookup_project", lambda *a, **k: project)
    assert cli.main(arguments(prepared_target, workspace=database.parent)) == 1
    assert "TARGET_PROFILE_INVALID" in capsys.readouterr().out


def test_local_init_validate_subdir_configuration_compatibility(prepared_target, tmp_path, monkeypatch, capsys):
    _, database, root, project, _ = prepared_target
    frontend = tmp_path / "host-frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html>Host UI</html>")
    output = tmp_path / "local.json"
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("Onboarding executed pytest"))
    assert cli.main(["local", "init", "--database", str(database), "--frontend-dist", str(frontend),
        "--project-key", project.key, "--workspace", str(root), "--test-cwd", "backend",
        "--pytest-target", "tests", "--config", str(output)]) == 0
    value = load_local_config(output)
    assert value.projects[0].workspace_root == root and value.projects[0].test_cwd == "backend"
    reader, mutation, execution, request = preflight.real_components(value.projects[0])
    assert reader.config.repository_root == mutation.config.workspace_root == execution.workspace_root == root
    assert Path(request.cwd) == root / "backend"
    assert json.loads(output.read_text())["projects"][0]["test_cwd"] == "backend"
    assert cli.main(["local", "validate", "--config", str(output)]) == 1  # Key absent, no execution.
    assert "OPENAI_API_KEY: MISSING" in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["demo", "preview-demo", "hosted-demo"])
def test_public_and_demo_modes_cannot_accept_target_bindings(prepared_target, tmp_path, mode):
    _, database, root, project, _ = prepared_target
    with pytest.raises(ValidationError):
        HostConfig(mode=mode, database=database, frontend_dist=tmp_path / "ui",
            projects=(LocalProjectConfig(key=project.key, workspace_root=root, test_cwd="backend", pytest_targets=("tests",)),))


def test_existing_workflow_test_service_keeps_real_evidence_with_subdir(prepared_target):
    factory, database, root, project, _ = prepared_target
    task = Task(project_id=project.id, title="Workflow regression", requirement="Keep normal evidence", state="TESTING")
    implementation = Artifact(task_id=task.id, artifact_type="IMPLEMENTATION", schema_version="0.1", content={"synthetic": True})
    with UnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.artifacts.add(implementation)
        uow.commit()
    profile = targets.TargetProfile(mode="local", project_id=project.id, workspace_root=root, test_cwd="backend", pytest_targets=("tests",))
    prepared = targets.prepare_target(profile, project, mode="local")
    service = WorkflowTests(factory, PytestRunner(CommandRunner(prepared.execution)),
        workspace_binding=ProjectWorkspaceBinding(project_id=project.id, workspace_root=root))
    run = service.execute(task_id=task.id, implementation_artifact_id=implementation.id, request=prepared.request)
    assert run.execution_status.value == "COMPLETED" and run.outcome.value == "PASS"
    assert (run.passed_count, run.failed_count, run.skipped_count) == (1, 0, 1)
    with UnitOfWork(factory) as uow:
        assert uow.history.get_test_run(run.id) == run and uow.tasks.get(task.id).state.value == "TESTING"
        assert {event.event_type for event in uow.history.list_events(task.id)} == {
            "PROJECT_WORKSPACE_BOUND", "TEST_EXECUTION_STARTED", "TEST_EXECUTION_COMPLETED"}
    assert str(root) not in database.read_text(errors="ignore")


def test_operator_interpreter_round_trip_matches_proving(prepared_target, tmp_path, native_target_python, monkeypatch, capsys):
    _, database, root, project, _ = prepared_target
    frontend = tmp_path / "operator-ui"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html>UI</html>")
    config_file = tmp_path / "operator-local.json"
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("Inert setup/check executed"))
    assert cli.main(["local", "init", "--database", str(database), "--frontend-dist", str(frontend),
        "--project-key", project.key, "--workspace", str(root), "--test-cwd", "backend", "--pytest-target", "tests",
        "--target-python", str(native_target_python), "--config", str(config_file)]) == 0
    configured = load_local_config(config_file)
    local = configured.projects[0]
    assert local.python_executable == native_target_python
    assert json.loads(config_file.read_text())["projects"][0]["python_executable"] == str(native_target_python)
    _, _, execution, request = preflight.real_components(local)
    profile = targets.TargetProfile(mode="local", project_id=project.id, workspace_root=root,
        test_cwd=local.test_cwd, pytest_targets=local.pytest_targets, python_executable=local.python_executable)
    prepared = targets.prepare_target(profile, project, mode="local")
    assert prepared.execution.python_executable == execution.python_executable == native_target_python
    assert prepared.request == request
    assert cli.main(arguments(prepared_target, **{"target-python": native_target_python})) == 0
    assert str(native_target_python) not in capsys.readouterr().out
    before = snapshot(database, root)
    assert cli.main(arguments(prepared_target, **{"target-python": root / "missing-python.exe"})) == 1
    assert "TARGET_PROFILE_INVALID" in capsys.readouterr().out
    assert snapshot(database, root) == before
