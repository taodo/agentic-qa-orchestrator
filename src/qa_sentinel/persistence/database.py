"""Explicit SQLite engine/session construction without global instances."""
import json
from sqlalchemy import Engine, event, create_engine as sqlalchemy_create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


def create_engine(url: str = "sqlite+pysqlite:///:memory:") -> Engine:
    if make_url(url).get_backend_name() != "sqlite":
        raise ValueError("Phase 1 supports SQLite only")
    engine = sqlalchemy_create_engine(
        url, echo=False, hide_parameters=True,
        json_serializer=lambda value: json.dumps(value, allow_nan=False),
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, record):
        # SQLAlchemy owns BEGIN, including DDL/savepoints, on Python 3.12 SQLite.
        connection.isolation_level = None
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @event.listens_for(engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
