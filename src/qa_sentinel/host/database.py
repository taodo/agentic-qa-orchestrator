"""File-backed SQLite with the accepted Alembic migrations, not create_all."""
from pathlib import Path
import sysconfig
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL
from qa_sentinel.persistence.database import create_engine, create_session_factory
from .config import HostError, canonical_path

CURRENT_REVISION = "0009"


def migration_directory() -> Path:
    checkout = Path(__file__).resolve().parents[3] / "alembic"
    installed = Path(sysconfig.get_path("data")) / "share" / "qa-sentinel" / "alembic"
    for path in (checkout, installed):
        if (path / "env.py").is_file() and (path / "versions" / "0009_qa_run_lifecycle.py").is_file():
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
