"""0005 owns only Campaign content and related composite identity support."""
from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from qa_sentinel.domain.campaign import QACampaign
from qa_sentinel.domain.project import Project
from qa_sentinel.domain.campaign_content import RequirementExtraction
from qa_sentinel.agents.requirement_extraction import ingest
from qa_sentinel.persistence.unit_of_work import UnitOfWork


def test_0004_upgrade_reopen_and_downgrade_preserve_every_existing_row(migrated_factory,bundle,store_bundle):
    factory,engine,config=migrated_factory
    command.downgrade(config,'0004')
    campaign=QACampaign(project_id=bundle['task'].project_id,name='Existing Campaign')
    with UnitOfWork(factory) as uow:
        store_bundle(uow,bundle);uow.campaigns.add(campaign);uow.commit()
    names=set(inspect(engine).get_table_names())-{'alembic_version'}
    def snapshot():
        with engine.connect() as connection:
            return {name:connection.execute(text(f'SELECT * FROM "{name}"')).all() for name in names}
    original=snapshot()
    command.upgrade(config,'0005')
    assert set(inspect(engine).get_table_names()) == names|{'alembic_version','campaign_sources','campaign_requirements','campaign_requirement_extractions'}
    assert snapshot()==original
    source=ingest(campaign.project_id,campaign.id,name='PRD',source_type='TEXT',content='Login required.\n')
    attempt=RequirementExtraction(project_id=source.project_id,campaign_id=source.campaign_id,source_id=source.id,source_hash=source.content_hash,model='test-model')
    with UnitOfWork(factory) as uow:
        uow.campaign_content.add_source(source);uow.campaign_content.reserve(attempt);uow.commit()
    engine.dispose()
    with UnitOfWork(factory) as uow:
        assert uow.campaign_content.source(source.id)==source
        assert uow.campaign_content.extraction_for_source(source.id)==attempt
    with engine.connect() as connection:
        assert not connection.exec_driver_sql('PRAGMA foreign_key_check').all()
        assert connection.scalar(text('select version_num from alembic_version'))=='0005'
    command.downgrade(config,'0004')
    assert set(inspect(engine).get_table_names())==names|{'alembic_version'} and snapshot()==original
    assert 'uq_qa_campaigns_id_project' not in {r['name'] for r in inspect(engine).get_indexes('qa_campaigns')}
    command.upgrade(config,'head')
    assert snapshot()==original


@pytest.mark.parametrize('kind',['foreign-project','foreign-campaign','duplicate-extraction','duplicate-content'])
def test_composite_ownership_and_unique_reservations_enforced(migrated_factory,kind):
    factory,engine,_=migrated_factory
    p=Project(key='p',name='P');other=Project(key='other',name='Other')
    c=QACampaign(project_id=p.id,name='C');foreign=QACampaign(project_id=other.id,name='Foreign')
    source=ingest(p.id,c.id,name='PRD',source_type='TEXT',content='Login required.')
    attempt=RequirementExtraction(project_id=p.id,campaign_id=c.id,source_id=source.id,source_hash=source.content_hash,model='test-model')
    with UnitOfWork(factory) as uow:
        uow.projects.add(p);uow.projects.add(other);uow.campaigns.add(c);uow.campaigns.add(foreign)
        uow.campaign_content.add_source(source);uow.campaign_content.reserve(attempt);uow.commit()
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            if kind in {'foreign-project','foreign-campaign'}:
                column='project_id' if kind=='foreign-project' else 'campaign_id'
                value=str(other.id if column=='project_id' else foreign.id)
                connection.execute(text(f'UPDATE campaign_sources SET {column}=:value WHERE id=:id'),dict(value=value,id=str(source.id)))
            elif kind=='duplicate-content':
                connection.execute(text('INSERT INTO campaign_sources SELECT :id,project_id,campaign_id,source_type,name,content_hash,raw_hash,normalization_version,original_bytes,normalized_chars,line_count,status,normalized_text,error_code,created_at FROM campaign_sources'),dict(id=str(uuid4())))
            else:
                connection.execute(text('INSERT INTO campaign_requirement_extractions SELECT :id,project_id,campaign_id,source_id,source_hash,contract_version,agent,model,status,started_at,finished_at,error_code,metadata FROM campaign_requirement_extractions'),dict(id=str(uuid4())))
    with UnitOfWork(factory) as uow:
        assert uow.campaign_content.source(source.id)==source
