"""Protected fake-only preview; all requests are in-process and offline."""
import base64
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from qa_sentinel.host import cli, composition, container, preflight
from qa_sentinel.host.config import HostConfig, HostError, LocalProjectConfig
from qa_sentinel.host.preview import preview_credentials
from qa_sentinel.host.web import create_host_app
from qa_sentinel.agents.fake import FakeAgentRuntime
from qa_sentinel.execution.fake import FakeTestResultProvider
from test_host import offline, config  # Reuse socket/provider/subprocess denial and prepared dist.

USER = 'synthetic-preview-user'
PASSWORD = 'synthetic-preview-password-π'


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv('QA_SENTINEL_PREVIEW_USERNAME', USER)
    monkeypatch.setenv('QA_SENTINEL_PREVIEW_PASSWORD', PASSWORD)


def preview(config, **changes):
    return HostConfig.model_validate({**config.model_dump(), 'mode': 'preview-demo', 'host': '0.0.0.0', **changes})


def header(user=USER, password=PASSWORD):
    return {'Authorization': 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()}


@pytest.mark.parametrize('mode', ['demo', 'local'])
def test_external_bind_cannot_be_used_by_ordinary_modes(config, tmp_path, mode):
    projects = () if mode == 'demo' else (LocalProjectConfig(key='a', workspace_root=tmp_path, pytest_targets=('tests',)),)
    with pytest.raises(ValidationError): HostConfig(mode=mode, database=config.database, frontend_dist=config.frontend_dist, projects=projects, host='0.0.0.0')
    mode_args = ['--demo'] if mode == 'demo' else ['--config', 'unused.json']
    with pytest.raises(SystemExit): cli.main(['serve', *mode_args, '--host', '0.0.0.0'])


def test_preview_requires_explicit_mode_and_rejects_runtime_config(config, tmp_path):
    assert preview(config).host == '0.0.0.0'
    project = LocalProjectConfig(key='a', workspace_root=tmp_path, pytest_targets=('tests',))
    with pytest.raises(ValidationError): preview(config, projects=(project,))
    for args in [['serve', '--preview-demo', '--demo'], ['serve', '--preview-demo', '--config', 'x.json']]:
        with pytest.raises(SystemExit): cli.main(args)


@pytest.mark.parametrize('field,value', [('QA_SENTINEL_PREVIEW_USERNAME', None), ('QA_SENTINEL_PREVIEW_PASSWORD', None),
    ('QA_SENTINEL_PREVIEW_USERNAME', ' '), ('QA_SENTINEL_PREVIEW_PASSWORD', ''), ('QA_SENTINEL_PREVIEW_USERNAME', 'x:y'),
    ('QA_SENTINEL_PREVIEW_PASSWORD', 'bad\nvalue')])
def test_missing_or_invalid_credentials_abort_before_io(config, monkeypatch, field, value, capsys, caplog):
    if value is None: monkeypatch.delenv(field)
    else: monkeypatch.setenv(field, value)
    with pytest.raises(HostError, match='HOST_PREVIEW_CREDENTIALS_REQUIRED'): create_host_app(preview(config))
    with pytest.raises(HostError, match='HOST_PREVIEW_CREDENTIALS_REQUIRED'): composition.compose(preview(config))
    assert not config.database.exists()
    assert USER not in caplog.text and PASSWORD not in capsys.readouterr().out


@pytest.mark.parametrize('key', ['', 'synthetic-forbidden-provider-key'])
def test_any_provider_key_is_forbidden_in_preview(config, monkeypatch, key):
    monkeypatch.setenv('OPENAI_API_KEY', key)
    with pytest.raises(HostError, match='HOST_PREVIEW_MODEL_KEY_FORBIDDEN'): create_host_app(preview(config))
    assert not config.database.exists()


def test_preview_can_only_compose_fake_runtime(config, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('Physical/real composition forbidden')
    monkeypatch.setattr(composition, 'real_components', forbidden)
    for cls in (composition.RealAgentRuntime, composition.OpenAIModelAdapter, preflight.RepositoryReadService,
        preflight.MutationService, composition.TestExecutionService, composition.PytestTestResultProvider):
        monkeypatch.setattr(cls, '__init__', forbidden)
    app = create_host_app(preview(config))
    with TestClient(app) as client:
        project = client.get('/api/v1/projects', headers=header()).json()['items'][0]
        from uuid import UUID
        bundle = app.state.host_composition.resolver.resolve(UUID(project['id']))
        assert isinstance(bundle.runtime, FakeAgentRuntime) and isinstance(bundle.test_provider, FakeTestResultProvider)
        assert bundle.repository_service is None and bundle.mutation_service is None
        task = client.post(f"/api/v1/projects/{project['id']}/tasks", headers=header(), json={'title': 'Division', 'requirement': 'Add division support and reject division by zero.'}).json()
        result = client.post(f"/api/v1/tasks/{task['id']}/run", headers=header())
        assert result.status_code == 200 and result.json()['state'] == 'DONE'
        assert client.get(f"/api/v1/tasks/{task['id']}/artifacts", headers=header()).json()['items']
        other = client.post('/api/v1/projects', headers=header(), json={'key': 'other', 'name': 'Other'}).json()
        foreign = client.post(f"/api/v1/projects/{other['id']}/tasks", headers=header(), json={'title': 'Other', 'requirement': 'Other'}).json()
        assert client.post(f"/api/v1/tasks/{foreign['id']}/run", headers=header()).json()['error']['code'] == 'PROJECT_RUNTIME_NOT_CONFIGURED'


@pytest.mark.parametrize('path', ['/', '/projects', '/tasks/task-a', '/api/v1/projects', '/openapi.json', '/docs', '/redoc', '/assets/app.js', '/host-info', '/health/'])
def test_only_exact_health_is_public(config, path):
    with TestClient(create_host_app(preview(config))) as client:
        health = client.get('/health')
        assert health.status_code == 200 and health.json() == {'status': 'ok'}
        result = client.get(path)
        assert result.status_code == 401
        assert result.headers['www-authenticate'].startswith('Basic ')
        assert result.json() == {'error': {'code': 'PREVIEW_AUTH_REQUIRED', 'message': 'Preview access required'}}
        assert client.post('/health').status_code == 401


@pytest.mark.parametrize('authorization', ['Basic !bad!', 'Bearer synthetic-token', 'Basic', 'Basic eA==', 'Basic ' + 'x' * 9000])
def test_malformed_auth_remains_safe(config, authorization):
    with TestClient(create_host_app(preview(config))) as client:
        result = client.get('/', headers={'Authorization': authorization})
        assert result.status_code == 401 and authorization not in result.text
        assert USER not in result.text and PASSWORD not in result.text


def test_invalid_credentials_and_duplicate_headers_are_denied(config):
    with TestClient(create_host_app(preview(config))) as client:
        for headers in [header(password='wrong'), header(user='wrong'), [('Authorization', header()['Authorization'])] * 2]:
            assert client.get('/', headers=headers).status_code == 401


@pytest.mark.parametrize('path', ['/', '/projects', '/projects/project-a', '/tasks/task-a?view=artifacts', '/api/v1/projects', '/assets/app.js'])
def test_auth_allows_spa_api_and_safe_headers(config, path):
    with TestClient(create_host_app(preview(config))) as client:
        result = client.get(path, headers=header())
        assert result.status_code == 200
        assert result.headers['x-content-type-options'] == 'nosniff'
        assert result.headers['referrer-policy'] == 'no-referrer'
        assert result.headers['x-frame-options'] == 'DENY'
        assert result.headers['cache-control'] == 'no-store'
        assert USER not in result.text and PASSWORD not in result.text
        assert 'access-control-allow-origin' not in result.headers


@pytest.mark.parametrize('path', ['/api/v1/missing', '/assets/missing.js', '/.env', '/Dockerfile', '/render.yaml',
    '/state.sqlite3', '/src/qa_sentinel/host/preview.py', '/assets/%2e%2e/%2e%2e/state.sqlite3'])
def test_auth_never_weakens_static_or_api_boundaries(config, path):
    with TestClient(create_host_app(preview(config))) as client:
        result = client.get(path, headers=header())
        assert result.status_code == 404 and 'Built frontend' not in result.text


def test_credentials_are_not_config_state_responses_or_logs(config, monkeypatch, caplog, capsys):
    import uvicorn
    response_text = []
    def run(app, **kwargs):
        assert kwargs['host'] == '0.0.0.0' and kwargs['workers'] == 1 and not kwargs['access_log']
        with TestClient(app) as client:
            response_text.extend([client.get('/').text, client.get('/health').text, client.get('/api/v1/projects', headers=header()).text])
    monkeypatch.setattr(uvicorn, 'run', run)
    assert cli.main(['serve', '--preview-demo', '--host', '0.0.0.0', '--database', str(config.database), '--frontend-dist', str(config.frontend_dist)]) == 0
    output = capsys.readouterr()
    for value in (USER, PASSWORD, header()['Authorization']):
        assert value not in output.out + output.err + caplog.text + ''.join(response_text)
        assert value.encode() not in config.database.read_bytes()
    stored = preview_credentials()
    assert USER not in repr(stored) and PASSWORD not in repr(stored)
    assert all(value.encode() not in part for value in (USER, PASSWORD) for part in (stored.salt, stored.username_digest, stored.password_digest))
    assert 'QA_SENTINEL_PREVIEW_PASSWORD' not in preview(config).model_dump_json()


def test_both_credentials_are_compared_with_constant_time_digest(monkeypatch):
    import hmac
    original = hmac.compare_digest
    calls = []
    def compare(a, b): calls.append((len(a), len(b))); return original(a, b)
    monkeypatch.setattr(hmac, 'compare_digest', compare)
    assert not preview_credentials().matches(b'wrong-user', b'wrong-password')
    assert calls == [(32, 32), (32, 32)]


@pytest.mark.parametrize('port', ['0', '-1', '65536', 'x', '80;evil', '', ' 8000'])
def test_container_port_invalid_fails_closed(monkeypatch, capsys, port):
    monkeypatch.setenv('PORT', port)
    assert container.main() == 1
    assert capsys.readouterr().err.strip() == 'QA Sentinel startup failed: HOST_PREVIEW_PORT_INVALID'


def test_container_command_is_fixed_preview_only(monkeypatch):
    calls = []
    monkeypatch.setenv('PORT', '12345')
    monkeypatch.setattr(container, 'serve', lambda argv: calls.append(argv) or 0)
    assert container.main() == 0
    assert calls == [['serve', '--preview-demo', '--host', '0.0.0.0', '--port', '12345', '--database', '/tmp/qa-sentinel/state.sqlite3', '--frontend-dist', '/app/frontend/dist']]


def test_documented_container_smoke_against_offline_host(config, monkeypatch, capsys):
    """Validate the developer smoke instructions without requiring Docker/network."""
    import http.client
    root = Path(__file__).resolve().parents[2]
    smoke = (root / 'docs/DEPLOYMENT.md').read_text(encoding='utf-8').split('```python\n', 1)[1].split('```', 1)[0]
    with TestClient(create_host_app(preview(config))) as client:
        class Connection:
            def __init__(self, host, port, timeout):
                assert host == '127.0.0.1' and port == 8000
            def request(self, method, path, body, headers):
                self.response = client.request(method, path, content=body, headers=headers, follow_redirects=False)
            def getresponse(self):
                return self
            def read(self):
                return self.response.content
            def getheader(self, name):
                return self.response.headers.get(name)
            @property
            def status(self):
                return self.response.status_code
            def close(self):
                pass
        monkeypatch.setattr(http.client, 'HTTPConnection', Connection)
        exec(compile(smoke, 'documented-container-smoke', 'exec'), {})
    assert capsys.readouterr().out.strip() == 'PASS: protected deterministic container preview'


def test_deployment_manifest_and_image_inputs():
    root = Path(__file__).resolve().parents[2]
    docker = (root / 'Dockerfile').read_text()
    blueprint = (root / 'render.yaml').read_text()
    assert 'branch: feature/develop' in blueprint and 'healthCheckPath: /health' in blueprint
    assert blueprint.count('sync: false') == 2 and 'value:' not in blueprint and 'OPENAI_API_KEY' not in blueprint
    assert 'numInstances: 1' in blueprint and 'runtime: docker' in blueprint
    assert 'COPY . ' not in docker and 'USER 10001:10001' in docker and 'npm ci' in docker
    assert 'CMD ["python", "-m", "qa_sentinel.host.container"]' in docker
    assert 'QA_SENTINEL_PREVIEW_PASSWORD' not in docker and 'OPENAI_API_KEY' not in docker
    assert '!frontend/package-lock.json' in (root / '.dockerignore').read_text()


def test_campaign_routes_keep_preview_basic_access(config):
    with TestClient(create_host_app(preview(config))) as client:
        project = client.get('/api/v1/projects', headers=header()).json()['items'][0]
        base = f"/api/v1/projects/{project['id']}/campaigns"
        assert client.get(base).status_code == 401
        assert client.post(base, json={'name':'Smoke'}).status_code == 401
        created = client.post(base, headers=header(), json={'name':'Smoke'})
        assert created.status_code == 201
        assert client.get(base, headers=header()).json()['items'][0]['status'] == 'DRAFT'
        assert client.get(f"/api/v1/projects/{project['id']}/tasks", headers=header()).json()['items'] == []


def test_preview_content_keeps_basic_access_and_no_real_extractor(config, monkeypatch):
    def forbidden(*args, **kwargs): pytest.fail('Preview cannot construct a real extractor')
    monkeypatch.setattr(composition.RequirementExtractor, '__init__', forbidden)
    web = create_host_app(preview(config))
    app = web.state.host_composition.application
    assert app._requirement_extractor is None
    project = app.list_projects().items[0]
    campaign = app.create_campaign(project.id, name='Synthetic PRD')
    with TestClient(web) as client:
        path = f'/api/v1/projects/{project.id}/campaigns/{campaign.id}'
        body = dict(name='Synthetic spec', source_type='TEXT', content='Synthetic users can sign in.')
        assert client.post(path+'/sources', json=body).status_code == 401
        source = client.post(path+'/sources', json=body, headers=header())
        assert source.status_code == 201
        result = client.post(path+'/sources/'+source.json()['id']+'/extract-requirements', headers=header())
        assert result.status_code == 409 and result.json()['error']['code'] == 'EXTRACTION_NOT_CONFIGURED'
        assert client.get(path+'/requirements', headers=header()).json()['items'] == []
        assert app.get_campaign(project.id, campaign.id) == campaign
