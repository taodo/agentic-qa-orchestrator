"""Additive 0003 migration, persistence constraints and safe downgrade."""
from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from qa_sentinel.domain.execution_job import ExecutionJob
from qa_sentinel.persistence.unit_of_work import UnitOfWork


def test_0002_to_0003_preserves_tasks_and_all_existing_evidence(migrated_factory, bundle, store_bundle):
    factory, engine, config = migrated_factory
    command.downgrade(config, "0002")
    with UnitOfWork(factory) as uow:
        store_bundle(uow, bundle); uow.commit()
    names = set(inspect(engine).get_table_names()) - {"alembic_version"}
    with engine.connect() as connection:
        snapshot = {name: connection.execute(text(f'SELECT * FROM "{name}"')).all() for name in names}
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("select version_num from alembic_version")) == "0003"
        assert not connection.exec_driver_sql("PRAGMA foreign_key_check").all()
        assert snapshot == {name: connection.execute(text(f'SELECT * FROM "{name}"')).all() for name in names}
        assert connection.scalar(text("select count(*) from execution_jobs")) == 0
    indexes = {index["name"]: index for index in inspect(engine).get_indexes("execution_jobs")}
    assert indexes["ix_execution_jobs_queue"]["column_names"] == ["status", "sequence"]
    assert indexes["uq_execution_jobs_active_task"]["unique"] and indexes["uq_execution_jobs_running"]["unique"]
    assert {fk["referred_table"] for fk in inspect(engine).get_foreign_keys("execution_jobs")} == {"tasks", "projects"}
    job = ExecutionJob(task_id=bundle["task"].id, project_id=bundle["task"].project_id)
    with UnitOfWork(factory) as uow:
        uow.execution_jobs.add(job); uow.commit()
    engine.dispose()  # Fresh physical connection, same persisted job.
    with UnitOfWork(factory) as uow:
        assert uow.execution_jobs.get(job.id) == job
    command.downgrade(config, "0002")
    assert "execution_jobs" not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert snapshot == {name: connection.execute(text(f'SELECT * FROM "{name}"')).all() for name in names}
    command.upgrade(config, "head")


@pytest.mark.parametrize("change", ["running-without-start", "queued-with-start", "success-without-finish", "failed-without-code", "raw-code", "orphan-task", "orphan-project"])
def test_database_lifecycle_and_fk_constraints(migrated_factory, bundle, store_bundle, change):
    factory, engine, _ = migrated_factory
    with UnitOfWork(factory) as uow:
        store_bundle(uow, bundle); uow.commit()
    values = {"id": str(uuid4()), "task": str(bundle["task"].id), "project": str(bundle["task"].project_id),
        "status": "QUEUED", "time": "2026-10-02T00:00:00+00:00", "start": None, "finish": None, "error": None}
    if change == "running-without-start": values["status"] = "RUNNING"
    elif change == "queued-with-start": values["start"] = values["time"]
    elif change == "success-without-finish": values.update(status="SUCCEEDED", start=values["time"])
    elif change == "failed-without-code": values.update(status="FAILED", start=values["time"], finish=values["time"])
    elif change == "raw-code": values.update(status="STOPPED", start=values["time"], finish=values["time"], error="raw-sensitive-exception")
    elif change == "orphan-task": values["task"] = str(uuid4())
    else: values["project"] = str(uuid4())
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO execution_jobs (id,task_id,project_id,status,created_at,started_at,finished_at,safe_error_code) "
                "VALUES (:id,:task,:project,:status,:time,:start,:finish,:error)"), values)
    with engine.connect() as connection:
        assert connection.scalar(text("select count(*) from execution_jobs")) == 0
