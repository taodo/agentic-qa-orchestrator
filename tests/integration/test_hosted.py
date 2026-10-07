"""Hosted durability/auth proof with synthetic secrets, no live sockets or tools."""
import base64
import hmac
import json
import re
import time
from pathlib import Path
from uuid import UUID
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from qa_sentinel.host import cli, composition, preflight, hosted_container
from qa_sentinel.host.access import COOKIE, LOGIN_COOKIE, SessionSigner, hosted_credentials
from qa_sentinel.host.config import HostConfig, HostError
from qa_sentinel.host.hosted import hosted_data_dir
from qa_sentinel.host.web import create_host_app
from qa_sentinel.agents.fake import FakeAgentRuntime
from qa_sentinel.execution.fake import FakeTestResultProvider
from test_host import offline, config

USER, PASSWORD, SECRET = 'synthetic-operator', 'synthetic-password-π', 'synthetic-independent-signing-secret-32'


@pytest.fixture(autouse=True)
def credentials(monkeypatch, tmp_path):
    monkeypatch.setattr('qa_sentinel.host.hosted.tempfile.gettempdir', lambda: str(tmp_path))
    for key, value in [('QA_SENTINEL_OPERATOR_USERNAME', USER), ('QA_SENTINEL_OPERATOR_PASSWORD', PASSWORD), ('QA_SENTINEL_SESSION_SECRET', SECRET)]:
        monkeypatch.setenv(key, value)


def hosted(config):
    root = config.database.parent.parent / 'hosted'
    return HostConfig(mode='hosted-demo', host='0.0.0.0', database=root / 'state.sqlite3', data_dir=root, frontend_dist=config.frontend_dist)


def login(client, user=USER, password=PASSWORD, **kwargs):
    page = client.get('/login')
    csrf = re.search('name="csrf" value="([a-f0-9]+)"', page.text)[1]
    return client.post('/auth/login', data={'username': user, 'password': password, 'csrf': csrf}, follow_redirects=False, **kwargs)


def csrf(client):
    return {'X-QA-Sentinel-CSRF': client.get('/auth/session').json()['csrf']}


@pytest.mark.parametrize('field,value,code', [
    ('QA_SENTINEL_OPERATOR_USERNAME', None, 'HOST_OPERATOR_CREDENTIALS_REQUIRED'),
    ('QA_SENTINEL_OPERATOR_PASSWORD', '', 'HOST_OPERATOR_CREDENTIALS_REQUIRED'),
    ('QA_SENTINEL_OPERATOR_USERNAME', 'x:y', 'HOST_OPERATOR_CREDENTIALS_REQUIRED'),
    ('QA_SENTINEL_OPERATOR_USERNAME', 'x;y', 'HOST_OPERATOR_CREDENTIALS_REQUIRED'),
    ('QA_SENTINEL_OPERATOR_PASSWORD', 'bad\nvalue', 'HOST_OPERATOR_CREDENTIALS_REQUIRED'),
    ('QA_SENTINEL_OPERATOR_PASSWORD', 'bad\u0085value', 'HOST_OPERATOR_CREDENTIALS_REQUIRED'),
    ('QA_SENTINEL_OPERATOR_USERNAME', 'bad\u202evalue', 'HOST_OPERATOR_CREDENTIALS_REQUIRED'),
    ('QA_SENTINEL_OPERATOR_PASSWORD', 'x' * 1025, 'HOST_OPERATOR_CREDENTIALS_REQUIRED'),
    ('QA_SENTINEL_SESSION_SECRET', None, 'HOST_SESSION_SECRET_REQUIRED'),
    ('QA_SENTINEL_SESSION_SECRET', 'short', 'HOST_SESSION_SECRET_REQUIRED'),
    ('QA_SENTINEL_SESSION_SECRET', SECRET + '\u009f', 'HOST_SESSION_SECRET_REQUIRED'),
    ('QA_SENTINEL_SESSION_SECRET', PASSWORD, 'HOST_SESSION_SECRET_REQUIRED'),
    ('OPENAI_API_KEY', '', 'HOST_HOSTED_MODEL_KEY_FORBIDDEN'),
    ('OPENAI_API_KEY', 'synthetic-key', 'HOST_HOSTED_MODEL_KEY_FORBIDDEN')])
def test_secrets_fail_before_io(config, monkeypatch, field, value, code):
    if value is None: monkeypatch.delenv(field)
    else: monkeypatch.setenv(field, value)
    config = hosted(config)
    for build in (create_host_app, composition.compose):
        with pytest.raises(HostError, match=code): build(config)
    assert not config.data_dir.exists()


@pytest.mark.parametrize('path', ['/', '/projects', '/assets/app.js', '/api/v1/projects', '/docs', '/openapi.json', '/host/runtime-status/unknown', '/api/v1/tasks/unknown/reconciliation', '/auth/session', '/health/'])
def test_public_boundary(config, path):
    with TestClient(create_host_app(hosted(config)), base_url='https://testserver') as client:
        assert client.get('/health').json() == {'status': 'ok'}
        assert client.get('/login').status_code == 200
        assert client.get(path).status_code == 401
        assert client.get('/', headers={'Accept': 'text/html'}, follow_redirects=False).headers['location'] == '/login'
        assert client.post('/health').status_code == 401
        assert client.head('/health').status_code == 401


def test_login_cookie_headers_and_logout(config, caplog, capsys):
    config = hosted(config)
    tokens = []
    with TestClient(create_host_app(config), base_url='https://testserver') as client:
        response = login(client)
        assert response.status_code == 303 and response.headers['location'] == '/'
        cookie = response.headers.get_list('set-cookie')[0]
        for flag in ('Secure', 'HttpOnly', 'SameSite=strict', 'Path=/', 'Max-Age=28800'): assert flag in cookie
        tokens.append(client.cookies.get(COOKIE))
        for path in ('/', '/api/v1/projects', '/auth/session', '/assets/app.js'):
            result = client.get(path)
            assert result.status_code == 200
            assert result.headers['x-content-type-options'] == 'nosniff'
            assert result.headers['referrer-policy'] == 'no-referrer'
            assert result.headers['x-frame-options'] == 'DENY'
            assert result.headers['cache-control'] == 'no-store'
            assert "frame-ancestors 'none'" in result.headers['content-security-policy']
            assert 'access-control-allow-origin' not in result.headers
            for value in (USER, PASSWORD, SECRET, tokens[0]): assert value not in result.text
        assert client.post('/auth/logout').status_code == 403
        response = client.post('/auth/logout', headers=csrf(client), follow_redirects=False)
        assert response.status_code == 303 and response.headers['location'] == '/login'
        assert 'Max-Age=0' in response.headers['set-cookie']
        assert client.get('/api/v1/projects').status_code == 401
    for value in (USER, PASSWORD, SECRET, *tokens):
        assert value not in caplog.text + capsys.readouterr().out
        assert value.encode() not in config.database.read_bytes()


def test_generic_invalid_and_cross_site_login(config):
    with TestClient(create_host_app(hosted(config)), base_url='https://testserver') as client:
        failures = [login(client, user='wrong').text, login(client, password='wrong').text,
            login(client, headers={'Origin': 'https://evil.example'}).text,
            login(client, headers={'Sec-Fetch-Site': 'cross-site'}).text,
            client.post('/auth/login', data={'username': USER, 'password': PASSWORD, 'csrf': 'bad'}).text,
            client.post('/auth/login', content=b'x' * 8193, headers={'Content-Type': 'application/x-www-form-urlencoded'}).text]
        assert len(set(failures)) == 1
        for secret in (USER, PASSWORD, SECRET): assert secret not in failures[0]
        assert client.cookies.get(COOKIE) is None


def test_login_throttle_is_bounded(config):
    with TestClient(create_host_app(hosted(config)), base_url='https://testserver') as client:
        for _ in range(10): assert login(client, password='wrong').status_code == 401
        assert login(client).status_code == 401


def test_csrf_bound_to_session_and_origin(config):
    with TestClient(create_host_app(hosted(config)), base_url='https://testserver') as client:
        assert login(client, headers={'Origin': 'https://testserver'}).status_code == 303
        first = csrf(client)
        assert login(client).status_code == 303
        payload = {'key': 'other', 'name': 'Other'}
        for headers in ({}, first, {**csrf(client), 'Origin': 'https://evil.example'},
            {**csrf(client), 'Origin': 'null'}, {**csrf(client), 'Sec-Fetch-Site': 'cross-site'},
            [('X-QA-Sentinel-CSRF', csrf(client)['X-QA-Sentinel-CSRF'])] * 2):
            assert client.post('/api/v1/projects', headers=headers, json=payload).status_code == 403
        assert client.post('/api/v1/projects', headers=csrf(client), json=payload).status_code == 201
        assert len(client.get('/api/v1/projects').json()['items']) == 2


@pytest.mark.parametrize('kind', ['bad-mac', 'expired', 'future', 'duplicate', 'wrong-purpose', 'oversized'])
def test_invalid_sessions_rejected(config, kind):
    signer = SessionSigner(SECRET.encode())
    token, _ = signer.issue(now=time.time() - 28801 if kind == 'expired' else time.time() + 60 if kind == 'future' else None,
        purpose='login' if kind == 'wrong-purpose' else 'session')
    if kind == 'bad-mac': token = token[:-1] + ('0' if token[-1] != '0' else '1')
    if kind == 'oversized': token = 'x' * 9000
    cookie = f'{COOKIE}={token}'
    if kind == 'duplicate': cookie += ';' + cookie
    with TestClient(create_host_app(hosted(config)), base_url='https://testserver') as client:
        assert client.get('/api/v1/projects', headers={'Cookie': cookie}).status_code == 401


def test_fake_only_and_restart_durability(config, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('Hosted physical construction forbidden')
    monkeypatch.setattr(composition, 'real_components', forbidden)
    for cls in (composition.RealAgentRuntime, composition.OpenAIModelAdapter, preflight.RepositoryReadService,
        preflight.MutationService, composition.TestExecutionService, composition.PytestTestResultProvider):
        monkeypatch.setattr(cls, '__init__', forbidden)
    config = hosted(config)
    app = create_host_app(config)
    with TestClient(app, base_url='https://testserver') as client:
        login(client); headers = csrf(client)
        project = client.get('/api/v1/projects').json()['items'][0]
        bundle = app.state.host_composition.resolver.resolve(UUID(project['id']))
        assert isinstance(bundle.runtime, FakeAgentRuntime) and isinstance(bundle.test_provider, FakeTestResultProvider)
        assert bundle.repository_service is None and bundle.mutation_service is None
        assert not bundle.binding.workspace_root.is_relative_to(config.data_dir)
        assert not (config.data_dir / 'demo-workspace').exists()
        task = client.post(f"/api/v1/projects/{project['id']}/tasks", headers=headers, json={'title': 'Division', 'requirement': 'Division'}).json()
        job = client.post(f"/api/v1/tasks/{task['id']}/executions", headers=headers).json()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            result = client.get(f"/api/v1/executions/{job['id']}").json()
            if result['status'] not in {'QUEUED', 'RUNNING'}: break
            time.sleep(.02)
        assert result['status'] == 'SUCCEEDED'
        assert client.get(f"/api/v1/tasks/{task['id']}").json()['state'] == 'DONE'
        evidence = client.get(f"/api/v1/tasks/{task['id']}/artifacts").json()
        cookie = client.cookies.get(COOKIE)
        other = client.post('/api/v1/projects', headers=headers, json={'key': 'other', 'name': 'Other'}).json()
        foreign = client.post(f"/api/v1/projects/{other['id']}/tasks", headers=headers, json={'title': 'Other', 'requirement': 'Other'}).json()
        assert client.post(f"/api/v1/tasks/{foreign['id']}/run", headers=headers).json()['error']['code'] == 'PROJECT_RUNTIME_NOT_CONFIGURED'
    with TestClient(create_host_app(config), base_url='https://testserver') as client:
        client.cookies.set(COOKIE, cookie)
        assert client.get('/').status_code == 200  # Restart-valid signed session.
        projects = client.get('/api/v1/projects').json()['items']
        assert len(projects) == 2 and next(p for p in projects if p['key'] == 'demo-calculator')['id'] == project['id']
        assert client.get(f"/api/v1/tasks/{task['id']}/artifacts").json() == evidence
        assert client.get(f"/api/v1/executions/{job['id']}").json()['status'] == 'SUCCEEDED'
        assert client.get(f"/api/v1/tasks/{task['id']}/reconciliation").json()['status'] == 'CLEAR'
        assert set(p.name for p in config.data_dir.iterdir()) <= {'state.sqlite3', 'state.sqlite3-wal', 'state.sqlite3-shm', 'state.sqlite3-journal'}


def test_data_root_and_config_boundaries(config, tmp_path):
    for root in ('', 'relative', str(config.frontend_dist), str(config.frontend_dist.parent), str(Path(__file__).resolve().parents[2])):
        with pytest.raises(HostError, match='HOST_HOSTED_DATA_INVALID'): hosted_data_dir(root, config.frontend_dist)
    with pytest.raises(HostError): hosted_data_dir(str(tmp_path / 'unprovisioned' / 'root'), config.frontend_dist)
    good = hosted(config)
    for changes in ({'database': good.data_dir / 'other.sqlite3'}, {'data_dir': Path('relative')},
        {'data_dir': good.frontend_dist, 'database': good.frontend_dist / 'state.sqlite3'}):
        with pytest.raises(ValidationError): HostConfig.model_validate({**good.model_dump(), **changes})
    for args in (['serve', '--hosted-demo', '--config', 'x'], ['serve', '--hosted-demo', '--demo']):
        with pytest.raises(SystemExit): cli.main(args)


def test_linked_root_rejected(config, tmp_path):
    link = tmp_path / 'linked'
    try: link.symlink_to(config.frontend_dist, target_is_directory=True)
    except OSError: pytest.skip('Symlink privilege unavailable')
    with pytest.raises(HostError): hosted_data_dir(str(link), config.frontend_dist)


def test_hosted_cli_single_process(config, monkeypatch, capsys):
    import uvicorn
    root = hosted(config).data_dir
    monkeypatch.setenv('QA_SENTINEL_DATA_DIR', str(root))
    monkeypatch.setenv('WEB_CONCURRENCY', '9')
    calls = []
    def run(app, **kwargs):
        calls.append(kwargs)
        with TestClient(app, base_url='https://testserver') as client: assert client.get('/health').status_code == 200
    monkeypatch.setattr(uvicorn, 'run', run)
    assert cli.main(['serve', '--hosted-demo', '--host', '0.0.0.0', '--frontend-dist', str(config.frontend_dist)]) == 0
    assert calls[0]['workers'] == 1 and not calls[0]['access_log'] and not calls[0]['proxy_headers'] and not calls[0]['reload']
    assert root.joinpath('state.sqlite3').is_file()
    for value in (USER, PASSWORD, SECRET): assert value not in capsys.readouterr().out
    assert cli.main(['serve', '--hosted-demo', '--database', str(config.database)]) == 1


def test_container_fixed_args(monkeypatch):
    calls = []
    monkeypatch.setenv('QA_SENTINEL_DATA_DIR', str(Path(Path.cwd().anchor) / 'var/data/qa-sentinel'))
    monkeypatch.setenv('PORT', '12345')
    monkeypatch.setattr(hosted_container, 'serve', lambda args: calls.append(args) or 0)
    assert hosted_container.main() == 0
    assert calls == [['serve', '--hosted-demo', '--host', '0.0.0.0', '--port', '12345', '--frontend-dist', '/app/frontend/dist']]
    monkeypatch.setenv('PORT', '0')
    assert hosted_container.main() == 1


@pytest.mark.parametrize('change', [
    {'v': 2}, {'v': True}, {'p': 'login'}, {'i': 'now'}, {'e': 2**60},
    {'n': 'bad'}, {'c': []}, {'unknown': 'value'}])
def test_signed_payload_shape_and_fixed_lifetime(change):
    signer = SessionSigner(SECRET.encode())
    token, _ = signer.issue()
    encoded = token.split('.')[0]
    data = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    data.update(change)
    encoded = base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b'=')
    malformed = (encoded + b'.' + hmac.digest(SECRET.encode(), encoded, 'sha256').hex().encode()).decode()
    assert signer.verify(malformed) is None


def test_secret_rotation_and_login_purpose_cannot_authenticate():
    signer = SessionSigner(SECRET.encode())
    token, _ = signer.issue()
    assert SessionSigner(b'different-independent-synthetic-secret').verify(token) is None
    login_token, _ = signer.issue('login')
    assert signer.verify(login_token) is None


def test_both_operator_fields_compared_constant_time(monkeypatch):
    original, calls = hmac.compare_digest, []
    def compare(a, b):
        calls.append((len(a), len(b)))
        return original(a, b)
    monkeypatch.setattr(hmac, 'compare_digest', compare)
    verifier = hosted_credentials().verifier
    assert not verifier.matches(b'wrong', b'wrong')
    assert calls == [(32, 32), (32, 32)]


def test_hosted_never_accepts_local_project_binding(config, tmp_path):
    from qa_sentinel.host.config import LocalProjectConfig
    project = LocalProjectConfig(key='other', workspace_root=tmp_path, pytest_targets=('tests',))
    with pytest.raises(ValidationError):
        HostConfig.model_validate({**hosted(config).model_dump(), 'projects': (project,)})


def test_campaign_routes_keep_session_csrf_and_restart_boundaries(config):
    settings = hosted(config)
    with TestClient(create_host_app(settings), base_url='https://testserver') as client:
        assert login(client).status_code == 303
        project = client.get('/api/v1/projects').json()['items'][0]
        base = f"/api/v1/projects/{project['id']}/campaigns"
        assert client.post(base, json={'name':'Smoke'}).status_code == 403
        created = client.post(base, headers=csrf(client), json={'name':'Smoke'})
        assert created.status_code == 201
        path = base + '/' + created.json()['id']
        assert client.patch(path, json={'name':'Unsafe'}).status_code == 403
        assert client.post(path+'/transitions', json={'status':'READY_FOR_REVIEW'}).status_code == 403
        assert client.post(path+'/transitions', headers=csrf(client), json={'status':'READY_FOR_REVIEW'}).status_code == 200
        assert client.get(f"/api/v1/projects/{project['id']}/tasks").json()['items'] == []
    with TestClient(create_host_app(settings), base_url='https://testserver') as client:
        assert client.get(path).status_code == 401
        assert client.patch(path, json={'name':'Unsafe'}).status_code == 401
        assert login(client).status_code == 303
        assert client.get(path).json()['status'] == 'READY_FOR_REVIEW'


def test_hosted_content_remains_deterministic_and_csrf_protected(config, monkeypatch):
    def forbidden(*args, **kwargs): pytest.fail('Public mode cannot construct a real extractor')
    monkeypatch.setattr(composition.RequirementExtractor, '__init__', forbidden)
    web = create_host_app(hosted(config))
    app = web.state.host_composition.application
    assert app._requirement_extractor is None
    project = app.list_projects().items[0]
    campaign = app.create_campaign(project.id, name='Synthetic PRD')
    with TestClient(web, base_url='https://testserver') as client:
        path = f'/api/v1/projects/{project.id}/campaigns/{campaign.id}'
        body = dict(name='Synthetic spec', source_type='TEXT', content='Synthetic users can sign in.')
        assert client.post(path+'/sources', json=body).status_code == 401
        assert login(client).status_code == 303
        assert client.post(path+'/sources', json=body).status_code == 403
        source = client.post(path+'/sources', json=body, headers=csrf(client))
        assert source.status_code == 201 and source.json()['status'] == 'INGESTED'
        extract_path = path+'/sources/'+source.json()['id']+'/extract-requirements'
        assert client.post(extract_path).status_code == 403
        result = client.post(extract_path, headers=csrf(client))
        assert result.status_code == 409 and result.json()['error']['code'] == 'EXTRACTION_NOT_CONFIGURED'
        assert client.get(path+'/requirements').json()['items'] == []
        assert client.get(path+'/model-usage').json()['invocations'] == []
        assert app.get_campaign(project.id, campaign.id) == campaign
