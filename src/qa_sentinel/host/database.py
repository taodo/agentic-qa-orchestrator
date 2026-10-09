"""File-backed SQLite with the accepted Alembic migrations, not create_all."""
from pathlib import Path
import sysconfig
import re
from sqlalchemy import text
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL
from qa_sentinel.persistence.database import create_engine, create_session_factory
from .config import HostError, canonical_path

CURRENT_REVISION = "0011"


def migration_directory() -> Path:
    checkout = Path(__file__).resolve().parents[3] / "alembic"
    installed = Path(sysconfig.get_path("data")) / "share" / "qa-sentinel" / "alembic"
    for path in (checkout, installed):
        if (path / "env.py").is_file() and (path / "versions" / "0011_qa_run_evidence.py").is_file():
            return path
    raise HostError("HOST_MIGRATIONS_MISSING")


def bootstrap_database(path: Path):
    engine = None
    try:
        path = canonical_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        canonical_path(path.parent, exists=True)
        url = URL.create("sqlite+pysqlite", database=str(path))
        engine = create_engine(url.render_as_string(hide_password=False))
        config = Config()
        config.set_main_option("script_location", str(migration_directory()).replace("%", "%%"))
        # Explicit idle connection avoids URL interpolation and owns migration lifetime.
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        return engine, create_session_factory(engine)
    except Exception:
        if engine is not None:
            engine.dispose()
        raise HostError("HOST_DATABASE_STARTUP_FAILED") from None


class SchemaNotReady(HostError):
    """Only bounded revision identifiers are safe to render, never DB contents."""
    def __init__(self, current):
        super().__init__("HOST_LOCAL_DATABASE_NOT_READY")
        self.current = current
        self.required = CURRENT_REVISION


def require_current_schema(connection):
    try:
        revisions = connection.execute(text("select version_num from alembic_version limit 2")).scalars().all()
    except Exception:
        raise SchemaNotReady("UNAVAILABLE") from None
    if revisions != [CURRENT_REVISION]:
        current = revisions[0] if len(revisions) == 1 and isinstance(revisions[0], str) and re.fullmatch(r"[0-9]{4}", revisions[0]) else "UNAVAILABLE"
        raise SchemaNotReady(current)


def open_existing_database(path: Path):
    """No mkdir, create or Alembic; SQLite mode=rw requires an existing file."""
    engine = None
    try:
        path = canonical_path(path, exists=True)
        if not path.is_file():
            raise ValueError("Existing database required")
        url = URL.create("sqlite+pysqlite", database=path.as_uri(), query={"mode": "rw", "uri": "true"})
        engine = create_engine(url.render_as_string(hide_password=False))
        with engine.connect() as connection:
            require_current_schema(connection)  # Recheck after preflight, before runtime composition.
        return engine, create_session_factory(engine)
    except Exception as exc:
        if engine is not None:
            engine.dispose()
        if isinstance(exc, SchemaNotReady):
            raise
        raise HostError("HOST_LOCAL_DATABASE_NOT_READY") from None
