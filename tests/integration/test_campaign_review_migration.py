"""0007 data preservation, integrity, safe downgrade and schema parity."""
from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import text, inspect
from sqlalchemy.exc import IntegrityError
from test_campaign_review import review, approve_all

NEW = {'campaign_requirement_reviews', 'campaign_test_reviews'}


def test_0007_upgrade_check_downgrade_preserves_all_0006_data(review):
    app, _, engine, config, p, c, req, spec = review
    command.downgrade(config, '0006')
    names = set(inspect(engine).get_table_names()) - {'alembic_version'}
    def snapshot():
        with engine.connect() as connection:
            return {name: connection.execute(text(f'SELECT * FROM "{name}" ORDER BY rowid')).all() for name in names}
    original = snapshot()
    command.upgrade(config, '0007')
    assert snapshot() == original and set(inspect(engine).get_table_names()) == names | NEW | {'alembic_version'}
    command.check(config)
    engine.dispose()
    assert app.get_campaign_requirement(p.id, c.id, req.id).model_dump() == req.model_dump()
    assert app.get_campaign_test_specification(p.id, c.id, spec.id) == spec
    with engine.connect() as connection: assert not connection.exec_driver_sql('PRAGMA foreign_key_check').all()
    command.downgrade(config, '0006')
    assert snapshot() == original and not NEW & set(inspect(engine).get_table_names())
    for table in ('campaign_requirements', 'campaign_test_specifications'):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text(f"UPDATE {table} SET review_status='APPROVED'"))
    command.upgrade(config, 'head');assert snapshot() == original


def test_downgrade_cannot_silently_delete_approval_evidence(review):
    app, _, engine, config, p, c, req, spec = review
    approve_all(review)
    receipt = app.get_campaign_requirement_review(p.id, c.id, req.id)
    with pytest.raises(RuntimeError, match='persisted approval evidence'): command.downgrade(config, '0006')
    assert app.get_campaign_requirement_review(p.id, c.id, req.id) == receipt
    assert app.get_campaign_readiness(p.id, c.id).status == 'READY'
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0007'
        assert not connection.exec_driver_sql('PRAGMA foreign_key_check').all()


@pytest.mark.parametrize('table', ['campaign_requirement_reviews', 'campaign_test_reviews'])
@pytest.mark.parametrize('bad', ['project', 'campaign', 'object', 'duplicate', 'status', 'note'])
def test_review_db_ownership_uniqueness_and_bounds(review, table, bad):
    app, _, engine, _, p, c, req, spec = review
    approve_all(review)
    foreign = app.create_project(key='foreign', name='Foreign');other = app.create_campaign(foreign.id, name='Other')
    object_id = req.id if 'requirement' in table else spec.id
    with pytest.raises(IntegrityError), engine.begin() as connection:
        if bad == 'duplicate': connection.execute(text(f'INSERT INTO {table} SELECT * FROM {table}'))
        else:
            column, value = {'project': ('project_id', str(foreign.id)), 'campaign': ('campaign_id', str(other.id)),
                'object': ('object_id', str(uuid4())), 'status': ('status', 'READY_FOR_REVIEW'), 'note': ('note', 'x'*1001)}[bad]
            connection.execute(text(f'UPDATE {table} SET {column}=:value WHERE object_id=:id'), dict(value=value, id=str(object_id)))
    assert app.get_campaign_readiness(p.id, c.id).status == 'READY'
