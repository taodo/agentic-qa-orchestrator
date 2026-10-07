"""CLI-only local-real proving. No workflow, model, mutation service or DB writes."""
from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import sqlite3
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from qa_sentinel.domain.project import ProjectKey
from qa_sentinel.domain.enums import TestExecutionStatus, TestOutcome
from qa_sentinel.projects import ProjectWorkspaceBinding
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.repository.config import RepositoryReadConfig
from qa_sentinel.mutation.contracts import MutationConfig
from qa_sentinel.execution.command_policy import ExecutionConfig, CommandRequest, CommandPolicy
from qa_sentinel.execution.command_runner import CommandRunner, ExecutionStatus
from qa_sentinel.execution.pytest_runner import PytestRunner, interpret
from .config import canonical_path, overlaps, relative_test_path
from qa_sentinel.execution.interpreter import target_python
from .database import CURRENT_REVISION


class TargetProfile(BaseModel):
    """Trusted host configuration, never a Task/request or persisted Project field."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["local"]
    project_id: UUID
    workspace_root: Path
    test_cwd: str = "."
    python_executable: Path | None = None

    @field_validator("python_executable")
    @classmethod
    def interpreter(cls, value):
        return target_python(value) if value is not None else None
    pytest_targets: tuple[str, ...] = Field(min_length=1, max_length=16)
    timeout_seconds: float = Field(default=120, gt=0, le=120, allow_inf_nan=False, strict=True)

    @field_validator("workspace_root")
    @classmethod
    def absolute_workspace(cls, value):
        if not value.is_absolute():
            raise ValueError("Workspace must be explicit and absolute")
        return value

    @field_validator("test_cwd")
    @classmethod
    def cwd(cls, value):
        return relative_test_path(value)

    @field_validator("pytest_targets")
    @classmethod
    def targets(cls, values):
        targets = tuple(relative_test_path(value) for value in values)
        if len(set(targets)) != len(targets):
            raise ValueError("Duplicate targets are not supported")
        return targets


class TargetError(StrEnum):
    TARGET_MODE_NOT_LOCAL = "TARGET_MODE_NOT_LOCAL"
    TARGET_PROFILE_INVALID = "TARGET_PROFILE_INVALID"
    TARGET_DATABASE_NOT_READY = "TARGET_DATABASE_NOT_READY"
    TARGET_PROJECT_NOT_FOUND = "TARGET_PROJECT_NOT_FOUND"
    TARGET_PROJECT_MISMATCH = "TARGET_PROJECT_MISMATCH"
    TARGET_WORKSPACE_UNAVAILABLE = "TARGET_WORKSPACE_UNAVAILABLE"
    TARGET_HOST_OVERLAP = "TARGET_HOST_OVERLAP"
    TARGET_TEST_CWD_INVALID = "TARGET_TEST_CWD_INVALID"
    TARGET_TEST_TARGET_INVALID = "TARGET_TEST_TARGET_INVALID"
    TARGET_PYTHON_UNAVAILABLE = "TARGET_PYTHON_UNAVAILABLE"
    TARGET_REPOSITORY_BOUNDARY_INVALID = "TARGET_REPOSITORY_BOUNDARY_INVALID"
    TARGET_MUTATION_BOUNDARY_INVALID = "TARGET_MUTATION_BOUNDARY_INVALID"
    TARGET_COMMAND_REJECTED = "TARGET_COMMAND_REJECTED"
    TARGET_EXECUTION_FAILED = "TARGET_EXECUTION_FAILED"


class TargetFailure(Exception):
    def __init__(self, code: TargetError):
        self.code = code
        super().__init__(code.value)


class TargetCheckView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["TARGET_READY", "TARGET_NOT_READY"]
    project_id: UUID | None = None
    checks: tuple[Literal["PROJECT_FOUND", "WORKSPACE_READY", "REPOSITORY_BOUNDARY_READY",
        "MUTATION_CONFIG_READY", "TEST_CWD_READY", "PYTEST_TARGETS_READY", "PYTHON_READY", "COMMAND_POLICY_READY"], ...] = ()
    safe_error_code: TargetError | None = None

    def render(self):
        lines = [f"Project ID: {self.project_id}"] if self.project_id is not None else []
        lines.extend(self.checks)
        lines.append(f"Target status: {self.status}")
        if self.safe_error_code: lines.append(f"Safe error: {self.safe_error_code.value}")
        return "\n".join(lines)


class ProvingError(StrEnum):
    EXECUTION_TIMEOUT = "EXECUTION_TIMEOUT"
    PROCESS_START_FAILED = "PROCESS_START_FAILED"
    OUTPUT_CAPTURE_FAILED = "OUTPUT_CAPTURE_FAILED"
    COMMAND_REJECTED = "COMMAND_REJECTED"
    PYTEST_INTERRUPTED = "PYTEST_INTERRUPTED"
    PYTEST_INTERNAL_ERROR = "PYTEST_INTERNAL_ERROR"
    PYTEST_USAGE_ERROR = "PYTEST_USAGE_ERROR"
    NO_TESTS_COLLECTED = "NO_TESTS_COLLECTED"
    PYTEST_UNEXPECTED_EXIT = "PYTEST_UNEXPECTED_EXIT"
    REPORT_COUNTS_UNAVAILABLE = "REPORT_COUNTS_UNAVAILABLE"
    TARGET_EXECUTION_FAILED = "TARGET_EXECUTION_FAILED"


class ProvingResult(BaseModel):
    """Ephemeral operator result, deliberately without Task/TestRun/job identity."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_status: ExecutionStatus | None
    execution_status: TestExecutionStatus
    outcome: TestOutcome
    exit_code: int | None
    duration_ms: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    counts_reliable: bool
    stdout_truncated: bool
    stderr_truncated: bool
    safe_error_code: ProvingError | None

    def render(self):
        return "\n".join(("Proving execution (not a QA workflow TestRun)",
            f"Execution: {self.execution_status.value}", f"Outcome: {self.outcome.value}",
            f"Exit code: {self.exit_code}", f"Duration ms: {self.duration_ms}",
            f"Counts: passed={self.passed_count} failed={self.failed_count} skipped={self.skipped_count}",
            f"Counts reliable: {'YES' if self.counts_reliable else 'NO'}",
            f"Output truncated: stdout={'YES' if self.stdout_truncated else 'NO'} stderr={'YES' if self.stderr_truncated else 'NO'}",
            f"Safe error: {self.safe_error_code.value if self.safe_error_code else 'NONE'}"))


@dataclass(frozen=True)
class PreparedTarget:
    binding: ProjectWorkspaceBinding
    execution: ExecutionConfig
    request: CommandRequest


def prepare_target(profile, project, *, mode):
    if mode != "local":
        raise TargetFailure(TargetError.TARGET_MODE_NOT_LOCAL)
    try:
        profile = TargetProfile.model_validate(profile.model_dump())
    except (ValueError, TypeError, AttributeError):
        raise TargetFailure(TargetError.TARGET_PROFILE_INVALID) from None
    if project is None:
        raise TargetFailure(TargetError.TARGET_PROJECT_NOT_FOUND)
    if project.id != profile.project_id:
        raise TargetFailure(TargetError.TARGET_PROJECT_MISMATCH)
    try:
        root = canonical_path(profile.workspace_root, exists=True)
        binding = ProjectWorkspaceBinding(project_id=project.id, workspace_root=root)
    except (ValueError, OSError, RuntimeError):
        raise TargetFailure(TargetError.TARGET_WORKSPACE_UNAVAILABLE) from None
    if overlaps(root, Path(__file__).resolve().parents[3]):
        raise TargetFailure(TargetError.TARGET_HOST_OVERLAP)
    try:
        cwd = canonical_path(root / profile.test_cwd, exists=True)
        if not cwd.is_dir() or not cwd.is_relative_to(root): raise ValueError
    except (ValueError, OSError, RuntimeError):
        raise TargetFailure(TargetError.TARGET_TEST_CWD_INVALID) from None
    try:
        for target in profile.pytest_targets:
            path = canonical_path(cwd / target, exists=True)
            if not path.is_relative_to(cwd) or not path.is_relative_to(root): raise ValueError
    except (ValueError, OSError, RuntimeError):
        raise TargetFailure(TargetError.TARGET_TEST_TARGET_INVALID) from None
    try:
        RepositoryReadConfig(binding.workspace_root)  # Constructors only; no source reads.
    except (ValueError, OSError, RuntimeError):
        raise TargetFailure(TargetError.TARGET_REPOSITORY_BOUNDARY_INVALID) from None
    try:
        MutationConfig(binding.workspace_root)  # No MutationService is constructed or called.
    except (ValueError, OSError, RuntimeError):
        raise TargetFailure(TargetError.TARGET_MUTATION_BOUNDARY_INVALID) from None
    try:
        interpreter = {} if profile.python_executable is None else {"python_executable": profile.python_executable}
        execution = ExecutionConfig(binding.workspace_root, pytest_target_root=cwd, **interpreter)
    except (ValueError, OSError, RuntimeError):
        raise TargetFailure(TargetError.TARGET_PYTHON_UNAVAILABLE) from None
    if not execution.python_executable.is_file() or not os.access(execution.python_executable, os.X_OK):
        raise TargetFailure(TargetError.TARGET_PYTHON_UNAVAILABLE)
    request = CommandRequest(cwd=str(cwd), args=("-m", "pytest", *profile.pytest_targets), timeout_seconds=profile.timeout_seconds)
    if not CommandPolicy(execution).evaluate(request).allowed:
        raise TargetFailure(TargetError.TARGET_COMMAND_REJECTED)
    return PreparedTarget(binding, execution, request)


def check_target(profile, project, *, mode):
    try:
        prepared = prepare_target(profile, project, mode=mode)
        return TargetCheckView(status="TARGET_READY", project_id=prepared.binding.project_id,
            checks=("PROJECT_FOUND", "WORKSPACE_READY", "REPOSITORY_BOUNDARY_READY", "MUTATION_CONFIG_READY",
                "TEST_CWD_READY", "PYTEST_TARGETS_READY", "PYTHON_READY", "COMMAND_POLICY_READY"))
    except TargetFailure as failure:
        return TargetCheckView(status="TARGET_NOT_READY", safe_error_code=failure.code)
    except Exception:
        return TargetCheckView(status="TARGET_NOT_READY", safe_error_code=TargetError.TARGET_PROFILE_INVALID)


def prove_target(profile, project, *, mode):
    prepared = prepare_target(profile, project, mode=mode)  # Recheck at every explicit use.
    try:
        result = PytestRunner(CommandRunner(prepared.execution)).run(prepared.request)
        conclusion = interpret(result)  # Reuse accepted exit interpretation, not TestRun conversion.
        reliable = result.counts.reliable and conclusion.execution_status == TestExecutionStatus.COMPLETED
        code = None
        if conclusion.error_type is not None:
            try: code = ProvingError(conclusion.reason_code)
            except ValueError: code = ProvingError.COMMAND_REJECTED if result.execution_status == ExecutionStatus.REJECTED else ProvingError.TARGET_EXECUTION_FAILED
        elif not reliable:
            code = ProvingError.REPORT_COUNTS_UNAVAILABLE
        return ProvingResult(command_status=result.execution_status, execution_status=conclusion.execution_status,
            outcome=conclusion.outcome, exit_code=result.exit_code, duration_ms=result.duration_ms,
            passed_count=result.counts.passed if reliable else 0, failed_count=result.counts.failed if reliable else 0,
            skipped_count=result.counts.skipped if reliable else 0, counts_reliable=reliable,
            stdout_truncated=result.stdout_truncated, stderr_truncated=result.stderr_truncated, safe_error_code=code)
    except Exception:
        return ProvingResult(command_status=None, execution_status="FAILED", outcome="UNKNOWN",
            exit_code=None, duration_ms=0, passed_count=0, failed_count=0, skipped_count=0,
            counts_reliable=False, stdout_truncated=False, stderr_truncated=False, safe_error_code="TARGET_EXECUTION_FAILED")


def lookup_project(database, *, key=None, project_id=None):
    """Existing repository lookup in mode=ro. No migrations, creation or live session across tests."""
    engine = None
    try:
        if not database.is_absolute(): raise ValueError
        path = canonical_path(database, exists=True)
        if not path.is_file(): raise ValueError
        if key is not None: key = TypeAdapter(ProjectKey).validate_python(key)
        engine = create_engine("sqlite+pysqlite://", creator=lambda: sqlite3.connect(path.as_uri() + "?mode=ro", uri=True))
        with engine.connect() as connection:
            if connection.execute(text("select version_num from alembic_version")).scalars().all() != [CURRENT_REVISION]: raise ValueError
        with UnitOfWork(sessionmaker(engine)) as uow:
            project = uow.projects.get_by_key(key) if key is not None else uow.projects.get(project_id)
        if project is None: raise TargetFailure(TargetError.TARGET_PROJECT_NOT_FOUND)
        return project
    except TargetFailure:
        raise
    except Exception:
        raise TargetFailure(TargetError.TARGET_DATABASE_NOT_READY) from None
    finally:
        if engine is not None: engine.dispose()


def target_command(args):
    try:
        project = lookup_project(args.database, key=args.project_key, project_id=args.project_id)
        profile = TargetProfile(mode="local", project_id=project.id, workspace_root=args.workspace,
            test_cwd=args.test_cwd, pytest_targets=args.pytest_target, timeout_seconds=args.timeout_seconds,
            python_executable=getattr(args, "target_python", None))
        # Host-owned persistence must stay outside the trusted executable target.
        if canonical_path(args.database).is_relative_to(canonical_path(profile.workspace_root)):
            raise TargetFailure(TargetError.TARGET_PROFILE_INVALID)
        if args.local_command == "target-check":
            report = check_target(profile, project, mode="local")
            print(report.render())
            return 0 if report.status == "TARGET_READY" else 1
        result = prove_target(profile, project, mode="local")
        print(result.render())
        return 0 if result.outcome == TestOutcome.PASS and result.counts_reliable else 1
    except Exception as failure:
        code = failure.code if isinstance(failure, TargetFailure) else TargetError.TARGET_PROFILE_INVALID
        print(TargetCheckView(status="TARGET_NOT_READY", safe_error_code=code).render())
        return 1
