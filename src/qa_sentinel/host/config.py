"""Frozen trusted-host JSON configuration, never request/model configuration."""
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from qa_sentinel.domain.project import ProjectKey


class HostError(RuntimeError):
    """A fixed safe startup code. Never include exception/config/environment values."""


def canonical_path(value: Path, *, exists=False) -> Path:
    try:
        path = Path(value).absolute()
        # Reject existing symlinks and Windows junctions before resolving any component.
        for part in (path, *path.parents):
            if part.is_symlink() or part.is_junction():
                raise ValueError("Linked host paths are not supported")
        return path.resolve(strict=exists)
    except (OSError, RuntimeError):
        raise ValueError("Host path is unavailable") from None


def overlaps(a: Path, b: Path) -> bool:
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


class LocalProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: ProjectKey
    workspace_root: Path
    pytest_targets: tuple[str, ...] = Field(min_length=1)

    @field_validator("workspace_root")
    @classmethod
    def workspace(cls, value):
        if not value.is_absolute():
            raise ValueError("Workspace must be explicit and absolute")
        root = canonical_path(value, exists=True)
        if not root.is_dir():
            raise ValueError("Workspace must be a directory")
        return root

    @field_validator("pytest_targets")
    @classmethod
    def targets(cls, values):
        if any(not v.strip() or v.startswith("-") or Path(v.split("::", 1)[0]).is_absolute() for v in values):
            raise ValueError("Targets must be relative paths, not options")
        return values


class HostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["demo", "local"]
    host: Literal["127.0.0.1", "::1"] = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535, strict=True)
    database: Path
    frontend_dist: Path
    projects: tuple[LocalProjectConfig, ...] = ()

    @field_validator("database", "frontend_dist")
    @classmethod
    def path(cls, value):
        return canonical_path(value)

    @model_validator(mode="after")
    def boundaries(self):
        if self.database.is_dir() or (self.database.exists() and not self.database.is_file()):
            raise ValueError("Database must be a regular file")
        if any(p.exists() and not p.is_dir() for p in self.database.parents):
            raise ValueError("Invalid database parent")
        if self.database.is_relative_to(self.frontend_dist):
            raise ValueError("Database must be outside frontend assets")
        if self.database.is_relative_to(Path(__file__).resolve().parents[1]):
            raise ValueError("Database must be outside package source")
        if (self.mode == "demo" and self.projects) or (self.mode == "local" and not self.projects):
            raise ValueError("Mode requires explicit matching configuration")
        if len({p.key for p in self.projects}) != len(self.projects):
            raise ValueError("Duplicate project keys")
        for index, project in enumerate(self.projects):
            if overlaps(project.workspace_root, self.frontend_dist) or self.database.is_relative_to(project.workspace_root):
                raise ValueError("Host files must be outside target workspaces")
            if any(overlaps(project.workspace_root, other.workspace_root) for other in self.projects[:index]):
                raise ValueError("Overlapping workspaces")
        return self


def load_local_config(path: Path) -> HostConfig:
    try:
        path = canonical_path(path, exists=True)
        if path.stat().st_size > 64 * 1024:
            raise ValueError("Oversized configuration")
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate JSON key")
                result[key] = value
            return result
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        if not isinstance(data, dict):
            raise ValueError("Configuration must be an object")
        data = {"mode": "local", **data}
        if data["mode"] != "local":
            raise ValueError("Config mode must be local")
        for name in ("database", "frontend_dist"):
            if name in data:
                data[name] = path.parent / data[name]
        config = HostConfig.model_validate(data)
        if path.is_relative_to(config.frontend_dist):
            raise ValueError("Configuration must be outside frontend assets")
        return config
    except (OSError, ValueError, TypeError, RuntimeError):
        raise HostError("HOST_CONFIG_INVALID") from None
