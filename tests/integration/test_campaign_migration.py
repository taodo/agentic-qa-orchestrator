"""Task 2.1 additive migration, rollback and FK/schema constraints."""
from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from qa_sentinel.domain.campaign import QACampaign
from qa_sentinel.persistence.unit_of_work import UnitOfWork


def test_0003_to_0004_preserves_existing_data_and_downgrade_is_scoped(migrated_factory, bundle, store_bundle):
    factory, engine, config = migrated_factory
    command.downgrade(config, "0003")
    with UnitOfWork(factory) as uow:
        store_bundle(uow, bundle); uow.commit()
    names = set(inspect(engine).get_table_names()) - {"alembic_version"}
    def snapshot():
        with engine.connect() as connection:
            return {name: connection.execute(text(f'SELECT * FROM "{name}"')).all() for name in names}
    original = snapshot()
    command.upgrade(config, "0004")
    assert set(inspect(engine).get_table_names()) == names | {"alembic_version", "qa_campaigns"}
    assert snapshot() == original
    with engine.connect() as connection:
        assert connection.scalar(text("select version_num from alembic_version")) == "0004"
        assert not connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    fk = inspect(engine).get_foreign_keys("qa_campaigns")
    assert len(fk) == 1 and fk[0]["referred_table"] == "projects" and fk[0]["constrained_columns"] == ["project_id"]
    index = inspect(engine).get_indexes("qa_campaigns")
    assert index[0]["column_names"] == ["project_id", "created_at", "id"]
    campaign = QACampaign(project_id=bundle["task"].project_id, name="Persist", objective="Independent")
    with UnitOfWork(factory) as uow:
        uow.campaigns.add(campaign); uow.commit()
    engine.dispose()
    with UnitOfWork(factory) as uow:
        assert uow.campaigns.get(campaign.id) == campaign
    command.downgrade(config, "0003")
    assert "qa_campaigns" not in inspect(engine).get_table_names() and snapshot() == original
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("select count(*) from qa_campaigns")) == 0
        assert not connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    assert snapshot() == original


@pytest.mark.parametrize("changes", [{"project":str(uuid4())}, {"status":"FAIL"}, {"name":""},
    {"name":" "}, {"name":"x"*201}, {"objective":"x"*4001}])
def test_campaign_database_constraints(migrated_factory, bundle, store_bundle, changes):
    factory, engine, _ = migrated_factory
    with UnitOfWork(factory) as uow:
        store_bundle(uow, bundle); uow.commit()
    values = dict(id=str(uuid4()), project=str(bundle["task"].project_id), name="Campaign",
        objective=None, status="DRAFT", time="2026-10-07T00:00:00+00:00")
    values.update(changes)
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO qa_campaigns (id,project_id,name,objective,status,created_at,updated_at) "
                "VALUES (:id,:project,:name,:objective,:status,:time,:time)"), values)
    with engine.connect() as connection:
        assert connection.scalar(text("select count(*) from qa_campaigns")) == 0
