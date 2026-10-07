"""0006 upgrade/downgrade durability and DB-enforced traceability ownership."""
from uuid import uuid4
import pytest
from sqlalchemy import inspect,text
from sqlalchemy.exc import IntegrityError
from alembic import command
from qa_sentinel.application import QASentinelApplication,ProjectExecutionResolver
from qa_sentinel.projects import ProjectRuntimeRegistry
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.domain.campaign import QACampaign
from test_campaign_test_specifications import seed_requirement,case,csv_text,harness,put

NEW={'campaign_test_imports','campaign_test_generations','campaign_test_specifications','campaign_test_requirement_links'}


def test_0006_upgrade_reopen_and_downgrade_preserves_all_0005_records(migrated_factory,bundle,store_bundle):
    factory,engine,config=migrated_factory;command.downgrade(config,'0005')
    campaign=QACampaign(project_id=bundle['task'].project_id,name='Existing QA')
    with UnitOfWork(factory) as uow:store_bundle(uow,bundle);uow.campaigns.add(campaign);uow.commit()
    from qa_sentinel.domain.project import Project
    project=Project(id=campaign.project_id,key='fixture',name='Fixture')
    requirement=seed_requirement(factory,project,campaign)
    names=set(inspect(engine).get_table_names())-{'alembic_version'}
    def snapshot():
        with engine.connect() as connection:return {name:connection.execute(text(f'SELECT * FROM "{name}"')).all() for name in names}
    existing=snapshot();command.upgrade(config,'0006')
    assert set(inspect(engine).get_table_names())==names|NEW|{'alembic_version'} and snapshot()==existing
    app=QASentinelApplication(factory,ProjectExecutionResolver(ProjectRuntimeRegistry([]),[]))
    record=app.import_campaign_tests(project.id,campaign.id,name='Existing',format='CSV',content=csv_text([case(refs=[str(requirement.id)])]))
    specs=app.list_campaign_test_specifications(project.id,campaign.id).items
    engine.dispose()
    assert app.get_campaign_test_import(project.id,campaign.id,record.id).content_hash==record.content_hash
    assert app.list_campaign_test_specifications(project.id,campaign.id).items==specs
    with engine.connect() as connection:assert not connection.exec_driver_sql('PRAGMA foreign_key_check').all()
    command.downgrade(config,'0005')
    assert not NEW&set(inspect(engine).get_table_names()) and snapshot()==existing
    assert 'uq_campaign_requirements_owner' not in {index['name'] for index in inspect(engine).get_indexes('campaign_requirements')}
    command.upgrade(config,'head');assert snapshot()==existing

@pytest.mark.parametrize('kind',['import-owner','spec-owner','link-project','link-campaign','unknown-link','duplicate-import','duplicate-generation','duplicate-spec-import','duplicate-spec-generation'])
def test_0006_database_ownership_and_unique_identity_enforced(harness,kind):
    app,factory,engine,project,campaign,requirements,_=harness;record=put(harness)
    spec=app.list_campaign_test_specifications(project.id,campaign.id).items[0]
    foreign=app.create_project(key='foreign',name='Foreign');other=app.create_campaign(foreign.id,name='Other')
    app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[requirements[0].id])
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            if kind=='import-owner':connection.execute(text('UPDATE campaign_test_imports SET project_id=:value WHERE id=:id'),dict(value=str(foreign.id),id=str(record.id)))
            elif kind=='spec-owner':connection.execute(text('UPDATE campaign_test_specifications SET campaign_id=:value WHERE id=:id'),dict(value=str(other.id),id=str(spec.id)))
            elif kind.startswith('link-'):
                column='project_id' if kind=='link-project' else 'campaign_id';value=foreign.id if column=='project_id' else other.id
                connection.execute(text(f'UPDATE campaign_test_requirement_links SET {column}=:value WHERE test_spec_id=:id'),dict(value=str(value),id=str(spec.id)))
            elif kind=='unknown-link':connection.execute(text('UPDATE campaign_test_requirement_links SET requirement_id=:value WHERE test_spec_id=:id'),dict(value=str(uuid4()),id=str(spec.id)))
            elif kind.startswith('duplicate-spec'):
                table='campaign_test_specifications';columns=[column['name'] for column in inspect(connection).get_columns(table)]
                names=','.join('"'+name+'"' for name in columns)
                values=','.join(':new_id' if name=='id' else ':new_key' if name=='logical_key' else '"'+name+'"' for name in columns)
                selector='import_id' if kind=='duplicate-spec-import' else 'generation_id'
                connection.execute(text(f'INSERT INTO {table} ({names}) SELECT {values} FROM {table} WHERE {selector} IS NOT NULL'),dict(new_id=str(uuid4()),new_key='DIFFERENT-LOGICAL'))
            else:
                table='campaign_test_imports' if kind=='duplicate-import' else 'campaign_test_generations'
                columns=[column['name'] for column in inspect(connection).get_columns(table)]
                names=','.join('"'+name+'"' for name in columns);values=','.join(':new_id' if name=='id' else '"'+name+'"' for name in columns)
                connection.execute(text(f'INSERT INTO {table} ({names}) SELECT {values} FROM {table}'),dict(new_id=str(uuid4())))
    assert app.get_campaign_test_specification(project.id,campaign.id,spec.id)==spec
