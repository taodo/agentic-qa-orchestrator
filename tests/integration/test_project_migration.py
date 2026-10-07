from pathlib import Path
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from qa_sentinel.persistence.database import create_engine

LEGACY_ID = "00000000-0000-4000-8000-000000000011"


@pytest.mark.parametrize("existing", [False, True])
def test_0001_upgrade_backfills_only_existing_tasks_preserves_linked_history(tmp_path, existing):
    config=Config(str(Path(__file__).resolve().parents[2]/"alembic.ini"))
    url="sqlite+pysqlite:///"+(tmp_path/"legacy.sqlite").as_posix()
    config.set_main_option("sqlalchemy.url",url)
    command.upgrade(config,"0001")
    engine=create_engine(url)
    task_id, inv_id, artifact_id = map(str,(uuid4(),uuid4(),uuid4()))
    now="2026-10-01T12:00:00+00:00"
    original=None
    if existing:
        with engine.begin() as c:
            c.execute(text("INSERT INTO tasks VALUES (:id,'Original','Requirement','RESEARCHING',NULL,:now,:now,NULL,:inv,2,3,4,NULL)"),dict(id=task_id,now=now,inv=inv_id))
            c.execute(text("INSERT INTO invocations VALUES (:id,:task,'RESEARCHER','fake','none',1,'STARTED',:now,NULL,'[]',NULL)"),dict(id=inv_id,task=task_id,now=now))
            c.execute(text("INSERT INTO artifacts VALUES (:id,:task,:inv,'RESEARCH','0.1','RESEARCHER','fake','{}',:now,NULL)"),dict(id=artifact_id,task=task_id,inv=inv_id,now=now))
        with engine.connect() as c:
            original=dict(c.execute(text("SELECT * FROM tasks")).mappings().one())
    command.upgrade(config,"head")
    with engine.connect() as c:
        assert c.scalar(text("PRAGMA foreign_keys"))==1
        assert not c.execute(text("PRAGMA foreign_key_check")).all()
        assert c.scalar(text("SELECT version_num FROM alembic_version"))=="0007"
        projects=c.execute(text("SELECT * FROM projects")).mappings().all()
        if existing:
            assert len(projects)==1 and projects[0]["id"]==LEGACY_ID and projects[0]["key"]=="legacy-bootstrap"
            migrated=dict(c.execute(text("SELECT * FROM tasks")).mappings().one())
            assert migrated.pop("project_id")==LEGACY_ID
            assert migrated==original
            assert c.scalar(text("SELECT task_id FROM artifacts WHERE id=:id"),dict(id=artifact_id))==task_id
            assert c.scalar(text("SELECT task_id FROM invocations WHERE id=:id"),dict(id=inv_id))==task_id
        else:
            assert not projects
    assert next(x for x in inspect(engine).get_columns("tasks") if x["name"]=="project_id")["nullable"] is False
    assert any(x["column_names"]==["project_id"] for x in inspect(engine).get_indexes("tasks"))
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            c.execute(text("INSERT INTO tasks (id,title,requirement,state,created_at,updated_at,implementation_attempt,defect_cycle,review_cycle) VALUES (:id,'T','R','CREATED',:now,:now,0,0,0)"),dict(id=str(uuid4()),now=now))
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            c.execute(text("INSERT INTO tasks (id,project_id,title,requirement,state,created_at,updated_at,implementation_attempt,defect_cycle,review_cycle) VALUES (:id,:owner,'T','R','CREATED',:now,:now,0,0,0)"),dict(id=str(uuid4()),owner=str(uuid4()),now=now))
    # Downgrade also recreates the referenced table without losing history.
    command.downgrade(config,"0001")
    with engine.connect() as c:
        assert "project_id" not in {x["name"] for x in inspect(engine).get_columns("tasks")}
        assert not c.execute(text("PRAGMA foreign_key_check")).all()
        assert c.scalar(text("SELECT count(*) FROM tasks"))==int(existing)
    command.upgrade(config,"head")
    engine.dispose()


def test_failed_integrity_check_rolls_back_schema_and_restores_connection_fk(tmp_path):
    config=Config(str(Path(__file__).resolve().parents[2]/"alembic.ini"))
    url="sqlite+pysqlite:///"+(tmp_path/"invalid-legacy.sqlite").as_posix()
    config.set_main_option("sqlalchemy.url",url)
    command.upgrade(config,"0001")
    engine=create_engine(url)
    try:
        with engine.connect() as connection:
            raw=connection.connection.driver_connection
            raw.execute("PRAGMA foreign_keys=OFF")
            # Deliberately corrupt legacy input outside application repositories.
            raw.execute("INSERT INTO artifacts VALUES (?, ?, NULL, 'RESEARCH', '0.1', NULL, NULL, '{}', '2026-10-01T00:00:00+00:00', NULL)",
                (str(uuid4()),str(uuid4())))
            raw.execute("PRAGMA foreign_keys=ON")
            config.attributes["connection"]=connection
            with pytest.raises(RuntimeError,match="foreign-key integrity"):
                command.upgrade(config,"head")
            assert not connection.in_transaction()
            assert connection.scalar(text("PRAGMA foreign_keys"))==1
            assert connection.scalar(text("SELECT version_num FROM alembic_version"))=="0001"
            assert "projects" not in inspect(connection).get_table_names()
            assert "project_id" not in {x["name"] for x in inspect(connection).get_columns("tasks")}
    finally:
        engine.dispose()
