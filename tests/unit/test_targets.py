"""External-target proving uses the accepted runner, without workflow or source access."""
from pathlib import Path
import subprocess
from uuid import uuid4
import pytest
from pydantic import ValidationError
from qa_sentinel.domain.project import Project
from qa_sentinel.host import targets, cli
from qa_sentinel.host.targets import TargetProfile, check_target, prepare_target, prove_target
from qa_sentinel.execution.command_policy import ExecutionConfig
from qa_sentinel.execution import command_runner
from test_execution import _Process, _Tree, result


@pytest.fixture
def external(tmp_path):
    root = tmp_path / "external repo"
    tests = root / "backend" / "tests"
    tests.mkdir(parents=True)
    (root / "frontend").mkdir()
    (tests / "test_ok.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    project = Project(key="external", name="External")
    profile = TargetProfile(mode="local", project_id=project.id, workspace_root=root,
        test_cwd="backend", pytest_targets=("tests",))
    return profile, project


@pytest.fixture(autouse=True)
def no_proving_side_effects(monkeypatch):
    from qa_sentinel.mutation.service import MutationService
    from qa_sentinel.orchestration.implementation_execution import ControlledImplementationExecution
    from qa_sentinel.agents.real import RealAgentRuntime
    from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
    from qa_sentinel.orchestration.runner import WorkflowRunner
    from qa_sentinel.orchestration.workflow_engine import WorkflowEngine
    from qa_sentinel.execution.service import TestExecutionService
    from qa_sentinel.repository.service import RepositoryReadService
    def forbidden(*args, **kwargs):
        pytest.fail("Proving crossed a forbidden workflow/provider/mutation/source boundary")
    for cls, names in ((MutationService, ("__init__", "apply")),
        (ControlledImplementationExecution, ("__init__", "apply")),
        (RealAgentRuntime, ("__init__", "run")), (OpenAIModelAdapter, ("generate",)),
        (WorkflowRunner, ("run",)), (WorkflowEngine, ("transition",)),
        (TestExecutionService, ("execute",)), (RepositoryReadService, ("execute",))):
        for name in names:
            monkeypatch.setattr(cls, name, forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


def test_check_is_deterministic_metadata_only_and_root_binding(external, monkeypatch):
    profile, project = external
    def forbidden(*args, **kwargs): pytest.fail("Dry check read/wrote content")
    # Validation may read a bounded native interpreter header, never target source.
    original_open = Path.open
    import sys
    def interpreter_only(path, *args, **kwargs):
        if path != Path(sys.executable).resolve() or args != ("rb",): forbidden()
        return original_open(path, *args, **kwargs)
    for name in ("read_text", "read_bytes", "write_text", "write_bytes"):
        monkeypatch.setattr(Path, name, forbidden)
    monkeypatch.setattr(Path, "open", interpreter_only)
    prepared = prepare_target(profile, project, mode="local")
    assert prepared.binding.workspace_root == profile.workspace_root
    assert prepared.execution.workspace_root == profile.workspace_root
    assert prepared.execution.pytest_target_root == profile.workspace_root / "backend"
    assert Path(prepared.request.cwd) == profile.workspace_root / "backend"
    assert prepared.request.args == ("-m", "pytest", "tests")
    assert not prepared.request.environment
    first = check_target(profile, project, mode="local")
    assert first.status == "TARGET_READY" and len(first.checks) == 8
    assert first == check_target(profile, project, mode="local")
    assert str(profile.workspace_root) not in first.render()
    assert len(first.render()) < 512


@pytest.mark.parametrize("mode", ["demo", "preview-demo", "hosted-demo"])
def test_nonlocal_rejected_before_metadata(external, monkeypatch, mode):
    profile, project = external
    monkeypatch.setattr(targets, "canonical_path", lambda *a, **k: pytest.fail("Nonlocal IO"))
    assert check_target(profile, project, mode=mode).safe_error_code == "TARGET_MODE_NOT_LOCAL"
    with pytest.raises(targets.TargetFailure, match="TARGET_MODE_NOT_LOCAL"):
        prove_target(profile, project, mode=mode)
    with pytest.raises(ValidationError):
        TargetProfile(**{**profile.model_dump(), "mode": mode})


@pytest.mark.parametrize("root_kind", ["same", "parent", "child"])
def test_host_overlap_is_symmetric(external, root_kind):
    profile, project = external
    host = Path(targets.__file__).resolve().parents[3]
    root = {"same": host, "parent": host.parent, "child": host / "src"}[root_kind]
    altered = profile.model_copy(update={"workspace_root": root})
    assert check_target(altered, project, mode="local").safe_error_code == "TARGET_HOST_OVERLAP"


@pytest.mark.parametrize("change,code", [
    ({"project_id": uuid4()}, "TARGET_PROJECT_MISMATCH"),
    ({"test_cwd": "missing"}, "TARGET_TEST_CWD_INVALID"),
    ({"test_cwd": "backend/tests/test_ok.py"}, "TARGET_TEST_CWD_INVALID"),
    ({"pytest_targets": ("missing",)}, "TARGET_TEST_TARGET_INVALID"),
    ({"pytest_targets": ("test.txt",)}, "TARGET_TEST_TARGET_INVALID"),
])
def test_unready_profiles_never_spawn(external, change, code):
    profile, project = external
    assert check_target(profile.model_copy(update=change), project, mode="local").safe_error_code == code


def test_missing_root_project_and_nonpython_target(external):
    profile, project = external
    altered = profile.model_copy(update={"workspace_root": profile.workspace_root / "missing"})
    assert check_target(altered, project, mode="local").safe_error_code == "TARGET_WORKSPACE_UNAVAILABLE"
    assert check_target(profile, None, mode="local").safe_error_code == "TARGET_PROJECT_NOT_FOUND"
    (profile.workspace_root / "backend" / "not_python.txt").write_text("not a target")
    assert check_target(profile.model_copy(update={"pytest_targets": ("not_python.txt",)}), project,
        mode="local").safe_error_code == "TARGET_COMMAND_REJECTED"


@pytest.mark.parametrize("field", ["test_cwd", "pytest_targets"])
@pytest.mark.parametrize("value", ["../outside", "backend/../tests", "/tmp/tests", "C:\\tests",
    "C:tests", "\\\\server\\share\\tests", "\\tests", "tests:stream", "tests::test_ok", "-m",
    "--help", "tests;echo", "tests|echo", "tests&echo", "$(echo)", "`echo`", "tests\n", " tests", "tests\x00"])
def test_portable_relative_paths_reject_escapes_and_command_syntax(external, field, value):
    profile, project = external
    changes = {field: (value,) if field == "pytest_targets" else value}
    with pytest.raises(ValidationError):
        TargetProfile(**{**profile.model_dump(), **changes})
    # Revalidation at use also rejects deliberately bypassed frozen constructors.
    assert check_target(profile.model_copy(update=changes), project, mode="local").safe_error_code == "TARGET_PROFILE_INVALID"


def test_windows_relative_separator_normalizes_without_host_assumptions(external):
    profile, project = external
    updated = TargetProfile(**{**profile.model_dump(), "test_cwd": ".\\backend",
        "pytest_targets": ("tests\\test_ok.py",)})
    assert updated.test_cwd == "backend" and updated.pytest_targets == ("tests/test_ok.py",)
    assert check_target(updated, project, mode="local").status == "TARGET_READY"


@pytest.mark.parametrize("change", [{"timeout_seconds": 0}, {"timeout_seconds": 121},
    {"timeout_seconds": float("nan")}, {"timeout_seconds": True}, {"environment": {}},
    {"args": ("-m", "pip")}, {"python_executable": "npm"}, {"pytest_targets": ()},
    {"pytest_targets": ("tests",) * 17}, {"pytest_targets": ("tests", "tests")},
    {"test_cwd": "a" * 513}])
def test_profile_is_narrow_bounded_and_frozen(external, change):
    profile, _ = external
    with pytest.raises(ValidationError): TargetProfile(**{**profile.model_dump(), **change})
    with pytest.raises(ValidationError): profile.test_cwd = "."


@pytest.mark.parametrize("location,code", [("root", "TARGET_WORKSPACE_UNAVAILABLE"),
    ("cwd", "TARGET_TEST_CWD_INVALID"), ("target", "TARGET_TEST_TARGET_INVALID")])
def test_junction_component_rejected_without_following(external, monkeypatch, location, code):
    profile, project = external
    selected = {"root": profile.workspace_root, "cwd": profile.workspace_root / "backend",
        "target": profile.workspace_root / "backend" / "tests"}[location]
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda path: path == selected or original(path))
    assert check_target(profile, project, mode="local").safe_error_code == code


@pytest.mark.parametrize("location", ["root", "cwd", "target", "descendant"])
def test_symlink_escape(external, tmp_path, location):
    profile, project = external
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "test_external.py").write_text("def test_external(): pass")
    link = {"root": tmp_path / "linked-root", "cwd": profile.workspace_root / "linked-cwd",
        "target": profile.workspace_root / "backend" / "linked-tests",
        "descendant": profile.workspace_root / "backend" / "tests" / "linked"}[location]
    try: link.symlink_to(outside, target_is_directory=True)
    except OSError: pytest.skip("Directory symlinks require unavailable OS privileges")
    change = {"root": {"workspace_root": link}, "cwd": {"test_cwd": "linked-cwd"},
        "target": {"pytest_targets": ("linked-tests",)}, "descendant": {}}[location]
    assert check_target(profile.model_copy(update=change), project, mode="local").status == "TARGET_NOT_READY"


def test_nested_target_link_cannot_escape_cwd_even_inside_full_repository(external):
    profile, project = external
    link = profile.workspace_root / "backend" / "tests" / "frontend-link"
    try: link.symlink_to(profile.workspace_root / "frontend", target_is_directory=True)
    except OSError: pytest.skip("Directory symlinks require unavailable OS privileges")
    assert check_target(profile, project, mode="local").safe_error_code == "TARGET_COMMAND_REJECTED"


def test_target_inspection_is_bounded_and_python_must_exist(external, monkeypatch):
    profile, project = external
    real = targets.ExecutionConfig
    for i in range(3): (profile.workspace_root / "backend" / "tests" / f"file{i}.py").touch()
    monkeypatch.setattr(targets, "ExecutionConfig", lambda root, **kw: real(root, max_target_entries=2, **kw))
    assert check_target(profile, project, mode="local").safe_error_code == "TARGET_COMMAND_REJECTED"
    monkeypatch.setattr(targets, "ExecutionConfig", lambda root, **kw: real(root, python_executable=root / "missing-python", **kw))
    assert check_target(profile, project, mode="local").safe_error_code == "TARGET_PYTHON_UNAVAILABLE"


@pytest.mark.parametrize("report", [None, "malformed", "<testsuite/>", "<!DOCTYPE test><testsuite/>"])
def test_missing_malformed_reports_are_not_parsed_from_prose(external, monkeypatch, report):
    profile, project = external
    def popen(argv, **kw):
        if report is not None: Path(argv[argv.index("--junitxml") + 1]).write_text(report)
        return _Process()
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(command_runner, "ProcessTree", _Tree)
    value = prove_target(profile, project, mode="local")
    assert value.outcome.value == "PASS" and not value.counts_reliable
    assert value.passed_count == value.failed_count == value.skipped_count == 0
    assert value.safe_error_code == "REPORT_COUNTS_UNAVAILABLE"


def test_existing_runner_argv_capture_environment_and_counts(external, monkeypatch):
    profile, project = external
    calls = []
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-sensitive-secret")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--unapproved")
    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        Path(argv[argv.index("--junitxml") + 1]).write_text(
            '<testsuite><testcase/><testcase><failure/></testcase><testcase><skipped/></testcase></testsuite>')
        return _Process(code=1)
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(command_runner, "ProcessTree", _Tree)
    original = targets.ExecutionConfig
    monkeypatch.setattr(targets, "ExecutionConfig", lambda root, **kw: original(root, max_output_bytes=16, **kw))
    value = prove_target(profile, project, mode="local")
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[1:5] == ["-P", "-s", "-m", "pytest"] and argv[5] == "tests"
    assert argv[argv.index("--rootdir") + 1] == str(profile.workspace_root)
    assert argv[argv.index("--confcutdir") + 1] == str(profile.workspace_root)
    assert kwargs["cwd"] == str(profile.workspace_root / "backend") and kwargs["shell"] is False
    assert "OPENAI_API_KEY" not in kwargs["env"] and "PYTEST_ADDOPTS" not in kwargs["env"]
    assert (value.passed_count, value.failed_count, value.skipped_count) == (1, 1, 1)
    assert value.outcome.value == "FAIL" and value.counts_reliable
    assert value.stdout_truncated and value.stderr_truncated
    assert "output" not in value.render() and "synthetic-sensitive" not in value.render()
    assert str(profile.workspace_root) not in str(value.model_dump())
    assert not list(profile.workspace_root.glob("qa-pytest-*"))


@pytest.mark.parametrize("kind,code", [("timeout", "EXECUTION_TIMEOUT"), ("start", "PROCESS_START_FAILED")])
def test_safe_timeout_and_process_failure(external, monkeypatch, kind, code):
    profile, project = external
    process = _Process(timeout=True)
    def popen(*args, **kwargs):
        if kind == "start": raise FileNotFoundError("synthetic-sensitive-path-key")
        return process
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(command_runner, "ProcessTree", _Tree)
    value = prove_target(profile, project, mode="local")
    assert value.outcome.value == "UNKNOWN" and value.safe_error_code == code
    assert not value.counts_reliable and value.exit_code is None
    assert "synthetic-sensitive" not in value.render()
    if kind == "timeout": assert process.killed


@pytest.mark.parametrize("exit_code,code", [(2, "PYTEST_INTERRUPTED"), (3, "PYTEST_INTERNAL_ERROR"),
    (4, "PYTEST_USAGE_ERROR"), (5, "NO_TESTS_COLLECTED"), (99, "PYTEST_UNEXPECTED_EXIT")])
def test_proving_reuses_exit_interpretation_and_discards_raw_result(external, monkeypatch, exit_code, code):
    profile, project = external
    monkeypatch.setattr(targets.PytestRunner, "run", lambda *a: result(exit_code))
    value = prove_target(profile, project, mode="local")
    assert value.outcome.value == "UNKNOWN" and value.safe_error_code == code
    assert not value.counts_reliable and value.passed_count == value.failed_count == value.skipped_count == 0
    assert "prose" not in value.render() and "stdout" not in type(value).model_fields


def test_unexpected_failure_has_no_raw_exception_or_retry(external, monkeypatch):
    profile, project = external
    calls = []
    def fail(*args):
        calls.append(1)
        raise RuntimeError("synthetic-sensitive-exception")
    monkeypatch.setattr(targets.PytestRunner, "run", fail)
    value = prove_target(profile, project, mode="local")
    assert calls == [1] and value.safe_error_code == "TARGET_EXECUTION_FAILED"
    assert value.command_status is None and value.outcome.value == "UNKNOWN"
    assert "synthetic-sensitive" not in value.render()


@pytest.mark.parametrize("command", ["target-check", "target-test"])
def test_cli_help_and_invalid_arguments_are_safe(command, capsys):
    with pytest.raises(SystemExit) as help_exit: cli.main(["local", command, "--help"])
    assert help_exit.value.code == 0 and "--test-cwd" in capsys.readouterr().out
    with pytest.raises(SystemExit) as invalid_exit:
        cli.main(("local", command, "--project-id", "synthetic-sensitive-invalid-value"))
    assert invalid_exit.value.code == 2
    output = capsys.readouterr()
    assert "TARGET_ARGUMENTS_INVALID" in output.err and "synthetic-sensitive" not in output.err
