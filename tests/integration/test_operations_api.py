"""In-process operational HTTP contracts with inherited host access."""
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from test_api import api, create_project, create_task, counts, error
from test_host import config, offline, local, seed
from qa_sentinel.host.config import HostConfig
from qa_sentinel.host.web import create_host_app

PATHS = ['/api/v1/operations/' + path for path in ('summary', 'projects', 'tasks', 'activity')]


def test_safe_read_endpoints_and_no_mutations(api, monkeypatch):
    client, app, factory = api
    p = create_project(client); t = create_task(client, p)
    def forbidden(*args, **kwargs): raise AssertionError('Operational read must not resolve runtime or assess workspace')
    monkeypatch.setattr(app._resolver, 'resolve', forbidden)
    monkeypatch.setattr(app, 'assess_task_reconciliation', forbidden)
    before = counts(factory)
    for path in PATHS:
        result = client.get(path)
        assert result.status_code == 200, result.text
        assert result.headers['cache-control'] == 'no-store'
        for method in (client.post, client.put, client.delete): assert method(path).status_code == 405
    assert counts(factory) == before
    assert client.get(PATHS[0]).json()['task_count'] == 1
    row = client.get(PATHS[2]).json()['items'][0]
    assert row['task_id'] == t['id'] and row['task_state'] == 'CREATED'
    assert not {'requirement', 'workspace_root', 'message', 'payload', 'sequence', 'source'} & row.keys()
    assert client.get(PATHS[2], params={'project_id': p['id'], 'task_state': 'CREATED', 'active_only': 'false', 'attention_only': 'false'}).json()['total_returned'] == 1
    assert client.get(PATHS[2], params={'attention_only': 'true'}).json()['items'] == []
    for path in PATHS[2:]: error(client.get(path, params={'project_id': str(uuid4())}), 404, 'PROJECT_NOT_FOUND')


@pytest.mark.parametrize('query', ['limit=0', 'limit=101', 'limit=1.0', 'limit=+2', 'limit=1&limit=2',
    'project_id=not-uuid', 'task_state=unsafe', 'execution_status=unsafe', 'attention=unsafe',
    'reconciliation_attention=1', 'active_only=TRUE', 'attention_only=1', 'sort=unsafe', 'search=unsafe'])
def test_strict_400_safe_validation(api, query):
    client, _, _ = api
    response = client.get(PATHS[2] + '?' + query)
    error(response, 400, 'REQUEST_VALIDATION_ERROR')
    assert 'unsafe' not in response.text


def test_summary_accepts_no_query(api):
    error(api[0].get(PATHS[0] + '?limit=1'), 400, 'REQUEST_VALIDATION_ERROR')
    assert api[0].get('/api/v1/projects?limit=0').status_code == 422  # Accepted API unchanged.


@pytest.mark.parametrize('mode', ['demo', 'local', 'preview-demo', 'hosted-demo'])
def test_host_routes_inherit_access_and_stay_offline(config, monkeypatch, mode):
    from test_hosted import login
    import base64
    user, password = 'synthetic-operator', 'synthetic-password'
    monkeypatch.setenv('QA_SENTINEL_PREVIEW_USERNAME', user)
    monkeypatch.setenv('QA_SENTINEL_PREVIEW_PASSWORD', password)
    monkeypatch.setenv('QA_SENTINEL_OPERATOR_USERNAME', user)
    monkeypatch.setenv('QA_SENTINEL_OPERATOR_PASSWORD', password)
    monkeypatch.setenv('QA_SENTINEL_SESSION_SECRET', 'synthetic-independent-session-secret-32')
    monkeypatch.setattr('qa_sentinel.host.hosted.tempfile.gettempdir', lambda: str(config.database.parent.parent))
    values = {**config.model_dump(), 'mode': mode}
    if mode == 'local':
        config = local(config, config.database.parent.parent)
        seed(config, 'real-project')
        values = config.model_dump()
        monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-unused-local-key')
    if mode == 'hosted-demo':
        values.update(data_dir=config.database.parent.parent / 'hosted', database=config.database.parent.parent / 'hosted/state.sqlite3')
    if mode in {'preview-demo', 'hosted-demo'}: values['host'] = '0.0.0.0'
    with TestClient(create_host_app(HostConfig.model_validate(values)), base_url='https://testserver') as client:
        for path in [*PATHS, '/operations']:
            if mode in {'preview-demo', 'hosted-demo'}:
                assert client.get(path, follow_redirects=False).status_code in {401, 303}
        if mode == 'hosted-demo':
            assert login(client, user=user, password=password).status_code == 303
        if mode == 'preview-demo':
            client.headers['Authorization'] = 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()
        for path in [*PATHS, '/operations']:
            result = client.get(path)
            assert result.status_code == 200, result.text
            assert user not in result.text and password not in result.text
        assert client.get('/operations/unknown').status_code == 404
        assert client.get('/health').status_code == 200
