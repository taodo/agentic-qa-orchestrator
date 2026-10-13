"""Runtime admission and populated 0011 -> 0012 API regressions, entirely offline."""
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import base64

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from qa_sentinel.api import create_api_app
from qa_sentinel.application import QASentinelApplication, ProjectExecutionResolver
from qa_sentinel.host import database, onboarding
from qa_sentinel.projects import ProjectRuntimeRegistry
from test_campaign_review import review, approve_all
from test_host import offline, config
from test_onboarding import prepared


def docx_bytes():
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Booking dates are bounded.</w:t></w:r></w:p></w:body></w:document>')
    return output.getvalue()


def migration_config():
    config = Config()
    config.set_main_option('script_location', str(database.migration_directory()))
    return config


def test_host_required_revision_matches_available_migration_head():
    assert ScriptDirectory.from_config(migration_config()).get_current_head() == database.CURRENT_REVISION


def test_preflight_and_existing_open_reject_actual_0011_without_migrating(prepared, monkeypatch):
    value, _, _ = prepared
    migration = migration_config()
    engine, _ = database.open_existing_database(value.database)
    try:
        with engine.connect() as connection:
            migration.attributes['connection'] = connection
            command.downgrade(migration, '0011')
    finally:
        engine.dispose()
    before = value.database.read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('Preflight/open must never migrate or call a provider')
    monkeypatch.setattr(database.command, 'upgrade', forbidden)
    monkeypatch.setattr(onboarding, 'model_key_present', forbidden)
    with pytest.raises(database.SchemaNotReady) as error:
        onboarding.validate_local(value)
    assert (error.value.current, error.value.required) == ('0011', '0018')
    with pytest.raises(database.SchemaNotReady) as error:
        database.open_existing_database(value.database)
    assert (error.value.current, error.value.required) == ('0011', '0018')
    assert value.database.read_bytes() == before


def test_populated_0011_upgrade_reopen_supports_fresh_v2_campaign_and_legacy_evidence(review):
    app, _, engine, migration, project, old_campaign, requirement, test = review
    approve_all(review)
    old_run = app.create_qa_run(project.id, old_campaign.id, idempotency_key='legacy')
    app.start_qa_run(project.id, old_campaign.id, old_run.id)
    old_results = app.get_qa_run_results(project.id, old_campaign.id, old_run.id)
    old_requirement = app.get_campaign_requirement(project.id, old_campaign.id, requirement.id)
    old_test = app.get_campaign_test_specification(project.id, old_campaign.id, test.id)
    command.downgrade(migration, '0011')

    # API-only composition intentionally bypasses the host guard to reproduce the
    # exact old-runtime symptom. Fresh creation needs only qa_campaigns, but even
    # empty V2 reads reference the new schema at SQLite statement preparation.
    with TestClient(create_api_app(app)) as client:
        created = client.post(f'/api/v1/projects/{project.id}/campaigns', json={'name':'Fresh runtime workspace'})
        assert created.status_code == 201
        fresh_id = created.json()['id']
        prefix = f'/api/v1/projects/{project.id}/campaigns/{fresh_id}'
        body = {'name':'spec.docx', 'content_base64':base64.b64encode(docx_bytes()).decode('ascii')}
        for suffix in ['/readiness', '/sources', '/execution-candidates']:
            failed = client.get(prefix + suffix)
            assert failed.status_code == 500
            assert failed.json() == {'error':{'code':'PERSISTENCE_ERROR','message':'Persistence operation failed'}}
        failed = client.post(prefix + '/documents', json=body)
        assert failed.status_code == 500
        assert failed.json() == {'error':{'code':'PERSISTENCE_ERROR','message':'Persistence operation failed'}}

    command.upgrade(migration, 'head')
    command.check(migration)
    # Exercise the actual non-migrating local-runtime opening path, not the
    # migration fixture factory that previously bypassed CURRENT_REVISION.
    reopened, factory = database.open_existing_database(Path(engine.url.database))
    restarted = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]), []))
    try:
        with TestClient(create_api_app(restarted)) as client:
            readiness = client.get(prefix + '/readiness')
            assert readiness.status_code == 200 and readiness.json()['status'] == 'NOT_READY'
            for suffix in ['/sources', '/test-specifications', '/execution-candidates']:
                read = client.get(prefix + suffix)
                assert read.status_code == 200 and read.json()['items'] == []
            uploaded = client.post(prefix + '/documents', json=body)
            assert uploaded.status_code == 201
            assert uploaded.json()['source_type'] == 'DOCX'
            source_id = uploaded.json()['id']
            source = client.get(prefix + '/sources/' + source_id)
            assert source.status_code == 200
            assert source.json()['normalized_text'] == 'Booking dates are bounded.'
            assert source.json()['document']['coordinates'][0]['start_line'] == 1
            assert client.get(prefix + '/sources').json()['items'][0]['id'] == source_id
            assert client.post(prefix + '/documents', json=body).json()['id'] == source_id
            assert client.get(prefix + '/execution-candidates').json()['items'] == []
        assert restarted.get_campaign_requirement(project.id, old_campaign.id, requirement.id) == old_requirement
        assert restarted.get_campaign_test_specification(project.id, old_campaign.id, test.id) == old_test
        assert restarted.get_qa_run_results(project.id, old_campaign.id, old_run.id) == old_results
        with reopened.connect() as connection:
            assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0018'
            assert not connection.exec_driver_sql('PRAGMA foreign_key_check').all()
            assert connection.scalar(text('SELECT count(*) FROM campaign_sources WHERE campaign_id=:id'), {'id':fresh_id}) == 1
            assert connection.scalar(text('SELECT count(*) FROM tasks')) == 0
            assert connection.scalar(text('SELECT count(*) FROM execution_jobs')) == 0
    finally:
        reopened.dispose()


def test_migration_discovery_rejects_pre_v2_bundle(tmp_path, monkeypatch):
    checkout = tmp_path / 'checkout'
    installed = tmp_path / 'installed'
    for root in [checkout / 'alembic', installed / 'share' / 'qa-sentinel' / 'alembic']:
        (root / 'versions').mkdir(parents=True)
        (root / 'env.py').write_text('# inert fixture', encoding='utf-8')
        (root / 'versions' / '0011_qa_run_evidence.py').write_text('# old bundle', encoding='utf-8')
    monkeypatch.setattr(database, '__file__', str(checkout / 'src' / 'qa_sentinel' / 'host' / 'database.py'))
    monkeypatch.setattr(database.sysconfig, 'get_path', lambda name:str(installed))
    with pytest.raises(database.HostError, match='HOST_MIGRATIONS_MISSING'):
        database.migration_directory()
