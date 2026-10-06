"""Explicit local configuration generation and read-only readiness checks."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.mutation.policy import PROTECTED
from .config import HostConfig, HostError, canonical_path, load_local_config
from .preflight import real_components, validate_frontend
from .database import CURRENT_REVISION


def model_key_present() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


@dataclass(frozen=True)
class Readiness:
    project_keys: tuple[str, ...]
    model_ready: bool

    def render(self) -> str:
        lines = []
        for key in self.project_keys:
            lines.extend((f"Project: {key}", "Project identity: FOUND", "Workspace: VALID",
                "Repository read boundary: VALID", "Mutation boundary: VALID", "Pytest targets: VALID"))
        lines.extend(("Frontend build: FOUND", "Database: READY",
            f"OPENAI_API_KEY: {'PRESENT' if self.model_ready else 'MISSING'}",
            f"Overall: {'READY' if self.model_ready else 'NOT READY'}"))
        return "\n".join(lines)


def validate_local(config: HostConfig) -> Readiness:
    """No migrations, model construction, test runner, source reads/writes or Tasks."""
    if config.mode != "local":
        raise HostError("HOST_CONFIG_INVALID")
    validate_frontend(config)
    try:
        for project in config.projects:
            real_components(project)
    except HostError:
        raise
    except (ValueError, OSError, RuntimeError):
        raise HostError("HOST_RUNTIME_POLICY_REJECTED") from None
    engine = None
    try:
        path = canonical_path(config.database, exists=True)
        if not path.is_file():
            raise ValueError("Missing database")
        # SQLite enforces read-only even if persistence code accidentally tries to write.
        engine = create_engine("sqlite+pysqlite://", creator=lambda: sqlite3.connect(
            path.as_uri() + "?mode=ro", uri=True))
        with engine.connect() as connection:
            if connection.execute(text("select version_num from alembic_version")).scalars().all() != [CURRENT_REVISION]:
                raise ValueError("Database must already be at the accepted schema")
        with UnitOfWork(sessionmaker(engine)) as uow:
            for project in config.projects:
                if uow.projects.get_by_key(project.key) is None:
                    raise HostError("HOST_PROJECT_NOT_FOUND")
    except HostError:
        raise
    except Exception:
        raise HostError("HOST_LOCAL_DATABASE_NOT_READY") from None
    finally:
        if engine is not None:
            engine.dispose()
    return Readiness(tuple(p.key for p in config.projects), model_key_present())


def config_target(path: Path, config: HostConfig) -> Path:
    """Configuration output is separate from target sources and served assets."""
    target = canonical_path(path)
    source = Path(__file__).resolve().parents[3]
    source_roots = tuple(source / name for name in ("src", "frontend", "tests", "alembic"))
    if (target.suffix.casefold() != ".json" or target == config.database or
        target.is_relative_to(config.frontend_dist) or
        any(target.is_relative_to(p.workspace_root) for p in config.projects) or
        any(target.is_relative_to(root) for root in source_roots) or
        any(part.casefold() in PROTECTED or part.casefold().startswith(".env.") or
            "credential" in part.casefold() or "secret" in part.casefold() for part in target.parts) or
        (target.exists() and (not target.is_file() or target.stat().st_nlink != 1))):
        raise HostError("HOST_CONFIG_OUTPUT_UNSAFE")
    return target


def initialize(args) -> Readiness:
    try:
        # Explicit absolute trust-bearing inputs; output path may be explicitly relative.
        if not args.database.is_absolute() or not args.frontend_dist.is_absolute():
            raise HostError("HOST_LOCAL_PATHS_MUST_BE_ABSOLUTE")
        try:
            config = HostConfig(mode="local", database=args.database, frontend_dist=args.frontend_dist,
                host=args.host, port=args.port, projects=({"key": args.project_key,
                    "workspace_root": args.workspace, "pytest_targets": args.pytest_target, "test_cwd": args.test_cwd},))
        except (ValueError, TypeError, OSError, RuntimeError):
            raise HostError("HOST_CONFIG_INVALID") from None
        target = config_target(args.config, config)
        if target.exists():
            if not args.overwrite:
                raise HostError("HOST_CONFIG_EXISTS")
            # Explicit replacement only of an existing valid local host config.
            # Never replace unrelated JSON or a config living in its old target workspace.
            config_target(target, load_local_config(target))
        report = validate_local(config)
        if not target.parent.is_dir():
            if not args.create_parent:
                raise HostError("HOST_CONFIG_PARENT_MISSING")
            target.parent.mkdir(parents=True, exist_ok=True)
        # Nonsecret allowlist only; no serialization of environment/provider objects.
        data = {"database": str(config.database), "frontend_dist": str(config.frontend_dist),
            "projects": [{"key": p.key, "workspace_root": str(p.workspace_root),
                "pytest_targets": list(p.pytest_targets), **({"test_cwd": p.test_cwd} if p.test_cwd != "." else {})} for p in config.projects],
            "host": config.host, "port": config.port}
        payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(payload) > 64 * 1024:
            raise HostError("HOST_CONFIG_INVALID")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".qa-sentinel-config-", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            config_target(target, config)  # Recheck linked/protected destination before commit.
            if args.overwrite:
                os.replace(temporary, target)
            else:
                # Exclusive publication: a racing creator cannot be overwritten.
                os.link(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return report
    except HostError:
        raise
    except (ValueError, TypeError, OSError, RuntimeError):
        raise HostError("HOST_LOCAL_INIT_FAILED") from None


def local_command(args) -> int:
    import sys
    try:
        if args.local_command == "init":
            report = initialize(args)
            print("Local configuration written. Existing Project identity unchanged.")
            print(report.render())
            return 0  # Config generation needs no model key; validate readiness separately.
        report = validate_local(load_local_config(args.config))
        print(report.render())
        return 0 if report.model_ready else 1
    except Exception as exc:
        code = str(exc) if isinstance(exc, HostError) else "HOST_LOCAL_VALIDATION_FAILED"
        print(f"Overall: NOT READY ({code})", file=sys.stderr)
        return 1
