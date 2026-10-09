"""0008/0009 upgrade/downgrade, preservation, schema parity and durable ownership."""
from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from test_qa_runs import ready, create, review

NEW = {"qa_runs", "qa_run_requirements", "qa_run_tests"}


def test_0008_roundtrip_preserves_all_preparation_and_legacy_data(ready, bundle, store_bundle):
    _, factory, engine, config, _, _, _, _ = ready
    command.downgrade(config, "0007")
    with UnitOfWork(factory) as uow:
        store_bundle(uow, bundle)
        uow.commit()
    names = set(inspect(engine).get_table_names()) - {"alembic_version"}
    # Compare all columns present at this historical checkpoint after upgrades.
    columns = {name: ','.join('"' + c['name'] + '"' for c in inspect(engine).get_columns(name)) for name in names}
    def snapshot():
        with engine.connect() as connection:
            return {name: connection.execute(text(f'SELECT {columns[name]} FROM "{name}" ORDER BY rowid')).all() for name in names}
    before = snapshot()
    command.upgrade(config, "0008")
    assert snapshot() == before
    assert set(inspect(engine).get_table_names()) == names | NEW | {"alembic_version"}
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0011"
        assert not connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    command.downgrade(config, "0007")
    assert snapshot() == before and not NEW & set(inspect(engine).get_table_names())
    command.upgrade(config, "head")
    assert snapshot() == before
    engine.dispose()
    assert create(ready).run_number == 1


def test_downgrade_refuses_to_erase_historical_run(ready):
    app, _, engine, config, p, c, _, _ = ready
    run = create(ready)
    tests = app.list_qa_run_tests(p.id, c.id, run.id)
    with pytest.raises(RuntimeError, match="no persisted QA Runs"):
        command.downgrade(config, "0007")
    assert app.get_qa_run(p.id, c.id, run.id) == run
    assert app.list_qa_run_tests(p.id, c.id, run.id) == tests
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0011"
        assert not connection.exec_driver_sql("PRAGMA foreign_key_check").all()


@pytest.mark.parametrize("kind", ["number", "key", "requirement_order", "test_order", "requirement_original", "test_original", "requirement_scope", "test_scope"])
def test_unique_scoped_identities_are_enforced_by_database(ready, kind):
    app, _, engine, _, p, c, _, _ = ready
    first = create(ready)
    second = create(ready, "second")
    other = app.create_campaign(p.id, name="Other Campaign")
    with pytest.raises(IntegrityError), engine.begin() as connection:
        if kind in ("number", "key"):
            column, value = ("run_number", first.run_number) if kind == "number" else ("idempotency_key", first.idempotency_key)
            connection.execute(text(f"UPDATE qa_runs SET {column}=:value WHERE id=:id"), {"value": value, "id": str(second.id)})
        elif kind.endswith("scope"):
            table = "qa_run_requirements" if kind.startswith("requirement") else "qa_run_tests"
            connection.execute(text(f"UPDATE {table} SET campaign_id=:id"), {"id": str(other.id)})
        else:
            table = "qa_run_requirements" if kind.startswith("requirement") else "qa_run_tests"
            original = "original_requirement_id" if kind.startswith("requirement") else "original_test_specification_id"
            columns = [column["name"] for column in inspect(connection).get_columns(table)]
            names = ",".join('"' + name + '"' for name in columns)
            # Isolate the relevant uniqueness constraint with a different identity/order/original.
            replacements = {"id": ":new_id", original if kind.endswith("order") else "position": ":different"}
            values = ",".join(replacements.get(name, '"' + name + '"') for name in columns)
            different = str(uuid4()) if kind.endswith("order") else 2
            connection.execute(text(f"INSERT INTO {table} ({names}) SELECT {values} FROM {table} WHERE run_id=:run"),
                {"new_id": str(uuid4()), "different": different, "run": str(first.id)})
    assert app.get_qa_run(p.id, c.id, first.id) == first and app.get_qa_run(p.id, c.id, second.id) == second


def test_0009_created_snapshot_roundtrip_and_null_backfill(ready):
    app, _, engine, config, p, c, _, _ = ready
    run = create(ready)
    def facts():
        with engine.connect() as connection:
            return {
                table: connection.execute(text(f'SELECT * FROM "{table}" ORDER BY rowid')).mappings().all()
                for table in ("qa_runs", "qa_run_requirements", "qa_run_tests")
            }
    before = facts()
    command.downgrade(config, "0008")
    old = facts()
    assert "execution_error_code" not in old["qa_runs"][0]
    command.upgrade(config, "head")
    assert facts() == before
    assert app.get_qa_run(p.id, c.id, run.id) == run
    assert before["qa_runs"][0]["execution_error_code"] is None
    command.check(config)
    with engine.connect() as connection:
        assert not connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("UPDATE qa_runs SET execution_error_code='raw exception'"))


def test_0009_downgrade_preserves_execution_evidence_by_refusing(ready):
    app, _, engine, config, p, c, _, _ = ready
    run = create(ready)
    finished = app.start_qa_run(p.id, c.id, run.id)
    tests = app.list_qa_run_tests(p.id, c.id, run.id)
    with pytest.raises(RuntimeError, match="cannot erase .*evidence"):
        command.downgrade(config, "0008")
    assert app.get_qa_run(p.id, c.id, run.id) == finished
    assert app.list_qa_run_tests(p.id, c.id, run.id) == tests
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0011"
