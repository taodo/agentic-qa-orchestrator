"""Narrow Python/pytest argv policy. Test code is executable code, not sandboxed here."""
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import sys
from types import MappingProxyType
from typing import Mapping
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .interpreter import target_python


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    executable: str = "python"
    args: tuple[str, ...] = ("-m", "pytest")
    cwd: str
    timeout_seconds: float = Field(default=120, gt=0, allow_inf_nan=False)
    environment: Mapping[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def freeze_environment(self):
        object.__setattr__(self, "environment", MappingProxyType(dict(self.environment)))
        return self


class CommandPolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    allowed: bool
    reason_code: str
    reason: str


@dataclass(frozen=True)
class ExecutionConfig:
    workspace_root: Path
    python_executable: Path = Path(sys.executable).resolve()
    max_timeout_seconds: float = 120
    max_output_bytes: int = 256 * 1024
    max_report_bytes: int = 1024 * 1024
    max_target_entries: int = 10000
    python_path: tuple[Path, ...] = ()
    allowed_environment_names: tuple[str, ...] = ()
    pytest_target_root: Path | None = None

    def __post_init__(self):
        root = Path(self.workspace_root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("workspace_root must be an existing directory")
        if isinstance(self.max_timeout_seconds, bool) or not math.isfinite(self.max_timeout_seconds) or self.max_timeout_seconds <= 0:
            raise ValueError("A positive finite maximum timeout is required")
        for limit in (self.max_output_bytes, self.max_report_bytes, self.max_target_entries):
            if type(limit) is not int or limit < 1:
                raise ValueError("Capture/report limits must be positive integers")
        names = tuple(self.allowed_environment_names)
        if any(not safe_environment_name(name) for name in names):
            raise ValueError("Configured environment name is sensitive or reserved")
        paths = tuple(Path(p).resolve(strict=True) for p in self.python_path)
        if any(not p.is_dir() for p in paths):
            raise ValueError("Explicit Python import paths must be directories")
        object.__setattr__(self, "workspace_root", root)
        object.__setattr__(self, "python_executable", target_python(self.python_executable))
        object.__setattr__(self, "python_path", paths)
        object.__setattr__(self, "allowed_environment_names", names)
        scope = root if self.pytest_target_root is None else Path(self.pytest_target_root).resolve(strict=True)
        if not scope.is_dir() or not within(scope, root):
            raise ValueError("Pytest target scope must be a directory within workspace")
        object.__setattr__(self, "pytest_target_root", scope)


def safe_environment_name(name: str) -> bool:
    upper = name.upper()
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)) and not (
        any(word in upper for word in ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL"))
        or upper.startswith(("PYTHON", "PYTEST", "LD_", "DYLD_", "SSH", "GIT_"))
        or upper in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "HOME", "USERPROFILE", "TMP", "TEMP", "TMPDIR"})


def within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


class CommandPolicy:
    SAFE_FLAGS = frozenset({"-q", "-s", "--tb=short", "--disable-warnings"})
    SHELL_MARKERS = (";", "|", "&", "`", "$(", "<", ">", "\n", "\r", "\x00")

    def __init__(self, config: ExecutionConfig):
        self.config = config

    def cwd(self, request: CommandRequest) -> Path:
        path = Path(request.cwd)
        return (path if path.is_absolute() else self.config.workspace_root / path).resolve(strict=True)

    def _directory_targets_safe(self, target: Path) -> bool:
        count = 0
        pending, visited = [target], set()
        while pending:
            directory = pending.pop()
            if directory in visited:
                continue
            visited.add(directory)
            with os.scandir(directory) as entries:
                for entry in entries:
                    count += 1
                    if count > self.config.max_target_entries:
                        return False
                    resolved = Path(entry.path).resolve(strict=True)
                    if not within(resolved, self.config.pytest_target_root):
                        return False
                    if resolved.is_dir():
                        pending.append(resolved)
        return True

    def evaluate(self, request: CommandRequest) -> CommandPolicyDecision:
        def decision(code, reason):
            return CommandPolicyDecision(allowed=code == "COMMAND_ALLOWED", reason_code=code, reason=reason)
        if request.executable != "python" or request.args[:2] != ("-m", "pytest"):
            return decision("COMMAND_NOT_ALLOWED", "Only the configured Python interpreter running pytest is allowed.")
        tokens = (request.executable, *request.args, request.cwd)
        if len(request.args) > 64 or any(len(t) > 2048 or any(m in t for m in self.SHELL_MARKERS) for t in tokens):
            return decision("COMMAND_NOT_ALLOWED", "Shell-like syntax or oversized command arguments are forbidden.")
        try:
            if target_python(self.config.python_executable) != self.config.python_executable:
                raise ValueError
        except ValueError:
            return decision("PYTHON_INTERPRETER_INVALID", "Configured interpreter is unavailable or unsafe.")
        if request.timeout_seconds > self.config.max_timeout_seconds:
            return decision("TIMEOUT_NOT_ALLOWED", "Requested timeout exceeds the configured maximum.")
        try:
            cwd = self.cwd(request)
        except (OSError, ValueError, RuntimeError):
            return decision("INVALID_CWD", "Working directory does not resolve to an existing directory.")
        if not within(cwd, self.config.workspace_root):
            return decision("WORKSPACE_ESCAPE", "Working directory is outside the approved workspace.")
        if not cwd.is_dir():
            return decision("INVALID_CWD", "Working directory must be a directory.")
        targets = [token for token in request.args[2:] if token not in self.SAFE_FLAGS] or ["."]
        for token in targets:
            if token in self.SAFE_FLAGS:
                continue
            if token.startswith("-"):
                return decision("PYTEST_OPTION_NOT_ALLOWED", "Pytest option is not in the explicit allowlist.")
            file_part = token.split("::", 1)[0]
            try:
                target = (cwd / file_part).resolve(strict=True)
            except (OSError, ValueError, RuntimeError):
                return decision("INVALID_TEST_TARGET", "Test target must exist inside the approved workspace.")
            if not within(target, self.config.pytest_target_root):
                return decision("WORKSPACE_ESCAPE", "Test target is outside the approved workspace.")
            if not target.is_dir() and (not target.is_file() or target.suffix != ".py"):
                return decision("INVALID_TEST_TARGET", "Target must be a test directory or Python file.")
            if "::" in token and not target.is_file():
                return decision("INVALID_TEST_TARGET", "Node IDs require a Python file target.")
            if target.is_dir():
                try:
                    if not self._directory_targets_safe(target):
                        return decision("WORKSPACE_ESCAPE", "Directory target escapes the workspace or exceeds bounded inspection.")
                except (OSError, ValueError, RuntimeError):
                    return decision("INVALID_TEST_TARGET", "Directory target cannot be inspected safely.")
        for name, value in request.environment.items():
            if not safe_environment_name(name) or name not in self.config.allowed_environment_names or "\x00" in value or len(value) > 4096:
                return decision("ENVIRONMENT_NOT_ALLOWED", "Environment addition is sensitive, reserved, or not explicitly approved.")
        return decision("COMMAND_ALLOWED", "Approved Python/pytest invocation within workspace policy.")

    def environment(self, request: CommandRequest, scratch: Path) -> dict[str, str]:
        env = {"PATH": str(self.config.python_executable.parent) + os.pathsep + os.defpath,
               "TMP": str(scratch), "TEMP": str(scratch), "TMPDIR": str(scratch),
               "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
               "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
        for name in ("SYSTEMROOT", "WINDIR"):
            if name in os.environ:
                env[name] = os.environ[name]
        if self.config.python_path:
            env["PYTHONPATH"] = os.pathsep.join(str(p) for p in self.config.python_path)
        env.update(request.environment)
        return env
