"""Inert host prerequisites shared by onboarding and serving. No execution."""
from pathlib import Path
from qa_sentinel.repository.config import RepositoryReadConfig
from qa_sentinel.repository.service import RepositoryReadService
from qa_sentinel.mutation.contracts import MutationConfig
from qa_sentinel.mutation.service import MutationService
from qa_sentinel.execution.command_policy import ExecutionConfig, CommandPolicy, CommandRequest
from .config import HostConfig, HostError, canonical_path, overlaps


def real_components(project):
    # Constructors only validate configuration; no snapshots, reads or apply calls.
    reader = RepositoryReadService(RepositoryReadConfig(project.workspace_root))
    mutation = MutationService(MutationConfig(project.workspace_root))
    cwd = canonical_path(project.workspace_root / project.test_cwd, exists=True)
    if not cwd.is_dir() or not cwd.is_relative_to(project.workspace_root):
        raise HostError("HOST_TEST_POLICY_REJECTED")
    interpreter = {} if project.python_executable is None else {"python_executable": project.python_executable}
    execution = ExecutionConfig(project.workspace_root, pytest_target_root=cwd, **interpreter)
    request = CommandRequest(cwd=str(cwd), args=("-m", "pytest", *project.pytest_targets))
    # Bounded inspection of explicitly selected targets, never test discovery/execution.
    if not CommandPolicy(execution).evaluate(request).allowed:
        raise HostError("HOST_TEST_POLICY_REJECTED")
    return reader, mutation, execution, request


def validate_frontend(config: HostConfig) -> Path:
    try:
        root = canonical_path(config.frontend_dist, exists=True)
        index = canonical_path(root / "index.html", exists=True)
        if not root.is_dir() or not index.is_file():
            raise ValueError("Missing frontend")
        if config.mode in {"demo", "preview-demo"} and overlaps(root, canonical_path(config.database.parent / "demo-workspace")):
            raise ValueError("Overlapping host directories")
        return root
    except (ValueError, OSError, RuntimeError):
        raise HostError("HOST_FRONTEND_BUILD_MISSING") from None
