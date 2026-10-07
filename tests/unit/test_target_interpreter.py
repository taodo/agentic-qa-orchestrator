"""Trusted interpreter selection with fake processes; no probes/install/network."""
from pathlib import Path
import os
import subprocess
import sys
import pytest
from pydantic import ValidationError
from qa_sentinel.execution.interpreter import target_python
from qa_sentinel.execution.command_policy import CommandRequest, CommandPolicy, ExecutionConfig
from qa_sentinel.execution.command_runner import CommandRunner
from qa_sentinel.host.config import HostConfig, LocalProjectConfig
from qa_sentinel.host.targets import TargetProfile, check_target, prepare_target, prove_target
from qa_sentinel.host.preflight import real_components
from qa_sentinel.execution import command_runner
from test_targets import external
from test_execution import _Process, _Tree


@pytest.mark.parametrize("case", ["relative", "missing", "directory", "wrapper", "script", "disguised",
    "traversal", "ads", "control", "shell", "unc"])
def test_invalid_interpreter_rejected_in_all_trusted_configs(external, native_target_python, case):
    profile, project = external
    parent = native_target_python.parent
    bad = parent / "python.exe"
    if case == "relative": bad = Path("python.exe")
    elif case == "missing": bad = parent / "missing" / "python.exe"
    elif case == "directory": bad = parent
    elif case == "wrapper": bad = parent / "python.cmd"; bad.write_bytes(b"@echo off")
    elif case == "script": bad = parent / "python.py"; bad.write_bytes(b"print(1)")
    elif case == "disguised": bad = parent / "other" / "python.exe"; bad.parent.mkdir(); bad.write_bytes(b"#!/bin/sh\necho unsafe\n"); bad.chmod(0o755)
    elif case == "traversal": bad = parent / ".." / parent.name / native_target_python.name
    elif case == "ads": bad = Path(str(native_target_python) + ":stream")
    elif case == "control": bad = Path(str(native_target_python) + "\n")
    elif case == "shell": bad = parent / "pipe|dir" / "python.exe"
    elif case == "unc": bad = Path(r"\\server\share\python.exe")
    for construct in (lambda: target_python(bad),
        lambda: ExecutionConfig(profile.workspace_root, python_executable=bad),
        lambda: LocalProjectConfig(key=project.key, workspace_root=profile.workspace_root, pytest_targets=("tests",), python_executable=bad),
        lambda: TargetProfile(**{**profile.model_dump(), "python_executable": bad})):
        with pytest.raises(ValueError): construct()


@pytest.mark.parametrize("linked", ["file", "parent", "junction"])
def test_linked_components_rejected_before_resolution(native_target_python, monkeypatch, linked):
    original = Path.is_symlink
    if linked == "junction": monkeypatch.setattr(Path, "is_junction", lambda p: p == native_target_python.parent)
    else:
        forbidden = native_target_python if linked == "file" else native_target_python.parent
        monkeypatch.setattr(Path, "is_symlink", lambda p: p == forbidden or original(p))
    with pytest.raises(ValueError, match="Target Python interpreter is invalid"):
        target_python(native_target_python)


def test_proving_and_workflow_use_identical_operator_interpreter(external, native_target_python, monkeypatch):
    profile, project = external
    configured = TargetProfile(**{**profile.model_dump(), "python_executable": native_target_python})
    local = LocalProjectConfig(key=project.key, workspace_root=profile.workspace_root,
        test_cwd="backend", pytest_targets=("tests",), python_executable=native_target_python)
    prepared = prepare_target(configured, project, mode="local")
    _, _, execution, request = real_components(local)
    assert execution == prepared.execution and request == prepared.request
    assert execution.python_executable == native_target_python != Path(sys.executable).resolve()
    calls = []
    def popen(argv, **kw):
        calls.append((argv, kw))
        Path(argv[argv.index("--junitxml") + 1]).write_text('<testsuite><testcase/></testsuite>')
        return _Process()
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(command_runner, "ProcessTree", _Tree)
    proving = prove_target(configured, project, mode="local")
    assert proving.counts_reliable and proving.passed_count == 1
    assert CommandRunner(execution).run(request).counts.reliable
    assert len(calls) == 2
    for argv, kw in calls:
        assert argv[:6] == [str(native_target_python), "-P", "-s", "-m", "pytest", "tests"]
        assert argv[argv.index("--rootdir")+1] == str(profile.workspace_root)
        assert argv[argv.index("--confcutdir")+1] == str(profile.workspace_root)
        assert kw["cwd"] == str(profile.workspace_root / "backend") and kw["shell"] is False
        assert kw["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1" and "PYTHONPATH" not in kw["env"]
        assert "OPENAI_API_KEY" not in kw["env"]
    assert str(native_target_python) not in proving.render()


def test_target_check_no_process_and_request_cannot_override(external, native_target_python, monkeypatch):
    profile, project = external
    configured = TargetProfile(**{**profile.model_dump(), "python_executable": native_target_python})
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("Validation launched a process"))
    assert check_target(configured, project, mode="local").status == "TARGET_READY"
    config = prepare_target(configured, project, mode="local").execution
    for executable in (str(native_target_python), sys.executable, "cmd", "python3"):
        assert CommandRunner(config).run(CommandRequest(cwd="backend", executable=executable)).reason_code == "COMMAND_NOT_ALLOWED"
    native_target_python.write_bytes(b"#!/bin/sh\n")
    assert CommandPolicy(config).evaluate(CommandRequest(cwd="backend")).reason_code == "PYTHON_INTERPRETER_INVALID"
    assert check_target(configured, project, mode="local").status == "TARGET_NOT_READY"


@pytest.mark.parametrize("mode", ["demo", "preview-demo", "hosted-demo"])
def test_public_modes_cannot_configure_or_prove(external, native_target_python, mode, monkeypatch, tmp_path):
    profile, project = external
    local = LocalProjectConfig(key=project.key, workspace_root=profile.workspace_root,
        pytest_targets=("tests",), python_executable=native_target_python)
    with pytest.raises(ValidationError):
        HostConfig(mode=mode, projects=(local,), database=tmp_path / "state.db", frontend_dist=tmp_path / "ui")
    with pytest.raises(ValidationError):
        HostConfig(mode=mode, python_executable=native_target_python, database=tmp_path / "state.db", frontend_dist=tmp_path / "ui")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("Public mode executed"))
    assert check_target(profile, project, mode=mode).safe_error_code == "TARGET_MODE_NOT_LOCAL"


def test_default_remains_host_interpreter(external):
    profile, project = external
    assert prepare_target(profile, project, mode="local").execution.python_executable == Path(sys.executable).resolve()
