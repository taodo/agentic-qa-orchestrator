"""Source-free local HTTP UX: explicit generation/accept/start with offline provider."""
from types import SimpleNamespace
from uuid import uuid4
import json
import socket
import subprocess
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from qa_sentinel.api import create_api_app
from qa_sentinel.host.browser_http import add_browser_http
from qa_sentinel.host.config import HostConfig,LocalProjectConfig
from qa_sentinel.host import composition,onboarding,browser
from qa_sentinel.domain.campaign_review import content_hash
from test_browser_plan_generation import planning,FACTS,OUTPUT,rows
from test_host import config,local,seed

@pytest.fixture
def http(planning,monkeypatch):
    app,_,_,_,p,c,*_=planning
    api=create_api_app(app)
    add_browser_http(api,SimpleNamespace(host='127.0.0.1',port=8000,projects=[SimpleNamespace(key=p.key)]))
    monkeypatch.setenv('OPENAI_API_KEY','SYNTHETIC_DO_NOT_RETURN')
    with TestClient(api,base_url='http://127.0.0.1:8000',client=('127.0.0.1',1234),headers={'origin':'http://127.0.0.1:8000'}) as client:
        yield client,f'/api/v1/projects/{p.id}/campaigns/{c.id}/browser'

def test_three_explicit_gates_no_secret_no_target_before_start(planning,http,monkeypatch):
    app,_,engine,_,p,c,spec,mock,executor,_=planning;client,base=http
    def forbidden(*a,**k):pytest.fail('No Target/provider/browser/source side effect from reads or acceptance')
    monkeypatch.setattr(socket,'getaddrinfo',forbidden)
    monkeypatch.setattr(subprocess,'Popen',forbidden)
    assert client.get(base+'/capability').json()=={'planning':'AVAILABLE','execution':'AVAILABLE'}
    assert client.get(base+f'/tests/{spec.id}/readiness').json()['status']=='AVAILABLE'
    assert len(mock.calls)==0 and executor.calls==[]
    generated=client.post(base+f'/tests/{spec.id}/generate',json={})
    assert generated.status_code==200,generated.text
    candidate=generated.json();gid=candidate['id']
    assert candidate['status']=='SUCCEEDED' and len(mock.calls)==1 and executor.calls==[] and rows(engine)==(0,0,0,0)
    assert 'SYNTHETIC_DO_NOT_RETURN' not in generated.text
    assert 'provider_response_id' not in generated.text and 'settings' not in candidate and 'metadata' not in candidate
    assert client.get(base+'/generations/'+gid).json()==candidate
    assert 'output' not in client.get(base+'/generations').json()['items'][0]
    assert len(mock.calls)==1 and executor.calls==[]
    accepted=client.post(base+'/generations/'+gid+'/accept',json={'idempotency_key':'review'})
    assert accepted.status_code==201,accepted.text
    run=accepted.json();assert run['executor_kind']=='WEB_BROWSER' and run['execution_status']=='CREATED'
    assert len(mock.calls)==1 and executor.calls==[]
    assert client.get(base+'/generations/'+gid).json()['accepted_run_id']==run['id']
    assert client.post(base+'/generations/'+gid+'/accept',json={'idempotency_key':'review'}).json()==run
    monkeypatch.delenv('OPENAI_API_KEY');app._browser_plan_generator=None
    assert client.get(base+'/capability').json()=={'planning':'UNAVAILABLE','execution':'AVAILABLE'}
    final=client.post(base+'/runs/'+run['id']+'/start',json={})
    assert final.status_code==200 and final.json()['execution_status']=='COMPLETED' and final.json()['qa_outcome']=='PASS'
    assert len(mock.calls)==1 and len(executor.calls)==1 and executor.calls[0].plan.model_dump(mode='json')==candidate['output']['plan']
    assert client.post(base+'/runs/'+run['id']+'/start',json={}).status_code==409
    assert len(executor.calls)==1

@pytest.mark.parametrize('change',['invalid-locator','path','actions','navigation','large','secret-confirmation','extra'])
def test_invalid_facts_rejected_without_edit_or_provider(planning,http,change):
    app,_,engine,_,p,c,spec,mock,executor,_=planning;client,base=http
    facts=json.loads(json.dumps(FACTS));body={'facts':facts,'non_secret':True,'previous_hash':content_hash(app.get_campaign_test_specification(p.id,c.id,spec.id)),'reviewer_label':'operator','note':'Known facts'}
    if change=='invalid-locator':facts['locators'][0]={'strategy':'XPATH','value':'x'}
    if change=='path':facts['paths']=['//private.invalid']
    if change=='actions':facts['required_actions']=[['NAVIGATE'],['CLICK']]
    if change=='navigation':facts['required_actions']=[['CLICK']]
    if change=='large':facts['input_values']=['x'*500]
    if change=='secret-confirmation':body['non_secret']=False
    if change=='extra':facts['script']='page.evaluate(secret)'
    before=app.list_campaign_test_specifications(p.id,c.id)
    response=client.post(base+f'/tests/{spec.id}/facts',json=body)
    assert response.status_code==422,response.text
    assert app.list_campaign_test_specifications(p.id,c.id)==before and len(mock.calls)==0 and executor.calls==[]

def test_facts_edit_uses_successor_and_fresh_approval(planning,http):
    app,_,_,_,p,c,spec,mock,executor,_=planning;client,base=http
    old=app.get_campaign_test_specification(p.id,c.id,spec.id)
    result=client.post(base+f'/tests/{spec.id}/facts',json={'facts':FACTS,'non_secret':True,'previous_hash':content_hash(old),'reviewer_label':'operator','note':'Known approved grounding'})
    assert result.status_code==201,result.text
    new=result.json();assert new['id']!=str(spec.id) and new['review_status']=='READY_FOR_REVIEW' and new['provenance']['origin']=='HUMAN_EDIT'
    assert app.get_campaign_test_specification(p.id,c.id,spec.id)==old
    assert client.get(base+'/tests/'+new['id']+'/readiness').json()['status']=='TEST_NOT_APPROVED'
    assert client.post(base+'/tests/'+new['id']+'/generate',json={}).status_code==409
    app.review_campaign_test_specification(p.id,c.id,new['id'],reviewer_label='operator')
    assert client.get(base+'/tests/'+new['id']+'/readiness').json()['status']=='AVAILABLE'
    assert len(mock.calls)==0 and executor.calls==[]

@pytest.mark.parametrize('kind',['missing','invalid','no-target','not-approved','provider'])
def test_readiness_blockers_never_call_provider(planning,http,kind):
    app,_,_,_,p,c,spec,mock,executor,_=planning;client,base=http
    expected={'missing':'FACTS_MISSING','invalid':'FACTS_INVALID','no-target':'TARGET_NOT_WEB','not-approved':'TEST_NOT_APPROVED','provider':'PROVIDER_UNAVAILABLE'}[kind]
    if kind in {'missing','invalid'}:
        old=app.get_campaign_test_specification(p.id,c.id,spec.id)
        from qa_sentinel.domain.test_specification import TestDesign
        design={key:getattr(old,key) for key in TestDesign.model_fields};design['preconditions']=[] if kind=='missing' else ['{"contract_version":"browser-facts-v1"}']
        spec=app.edit_campaign_test(p.id,c.id,spec.id,design=design,previous_hash=content_hash(old),reviewer_label='qa',note='grounding changed')
        app.review_campaign_test_specification(p.id,c.id,spec.id,reviewer_label='qa')
    if kind=='no-target':app.associate_campaign_target(p.id,c.id,target_id=None)
    if kind=='not-approved':
        # Superseded approval is not current and cannot authorize generation.
        old=app.get_campaign_test_specification(p.id,c.id,spec.id)
        from qa_sentinel.domain.test_specification import TestDesign
        app.edit_campaign_test(p.id,c.id,spec.id,design={key:getattr(old,key) for key in TestDesign.model_fields},previous_hash=content_hash(old),reviewer_label='qa',note='successor')
    if kind=='provider':app._browser_plan_generator=None
    assert client.get(base+f'/tests/{spec.id}/readiness').json()['status']==expected
    assert client.post(base+f'/tests/{spec.id}/generate',json={}).status_code==409
    assert len(mock.calls)==0 and executor.calls==[]

@pytest.mark.parametrize('headers',[{'host':'evil.invalid:8000'},{'origin':'https://evil.invalid'},{'origin':'null'},{'origin':''}])
def test_browser_host_csrf_rebinding_guard(planning,http,headers):
    *_,spec,mock,executor,target=planning;client,base=http
    response=client.post(base+f'/tests/{spec.id}/generate',json={},headers=headers)
    assert response.status_code==403 and response.json()['error']['code']=='HOST_LOCAL_ACCESS_REQUIRED'
    assert len(mock.calls)==0 and executor.calls==[]

def test_nonlocal_peer_and_bare_api_cannot_execute(planning):
    app,_,_,_,p,c,spec,mock,executor,_=planning;api=create_api_app(app)
    base=f'/api/v1/projects/{p.id}/campaigns/{c.id}/browser'
    with TestClient(api) as client:
        assert client.get(base+'/capability').json()=={'planning':'UNAVAILABLE','execution':'UNAVAILABLE'}
        assert client.post(base+f'/tests/{spec.id}/generate',json={}).status_code==404
        assert client.post(base+'/runs/'+str(uuid4())+'/start',json={}).status_code==404
    api=create_api_app(app)
    add_browser_http(api,SimpleNamespace(host='127.0.0.1',port=8000,projects=[SimpleNamespace(key=p.key)]))
    with TestClient(api,base_url='http://127.0.0.1:8000',client=('203.0.113.1',1234),headers={'origin':'http://127.0.0.1:8000'}) as client:
        assert client.get(base+'/capability').status_code==403
    assert len(mock.calls)==0 and executor.calls==[]

def test_browser_only_host_no_workspace_no_key_no_migration(config,monkeypatch):
    p=seed(config,'browser-operator')
    value=HostConfig(mode='local',database=config.database,frontend_dist=config.frontend_dist,projects=[{'key':'browser-operator','browser_only':True}])
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.setattr(composition,'real_components',lambda *a:pytest.fail('No source services'))
    monkeypatch.setattr(onboarding,'real_components',lambda *a:pytest.fail('No source validation'))
    monkeypatch.setattr(composition,'bootstrap_database',lambda *a:pytest.fail('No auto migration'))
    report=onboarding.validate_local(value)
    assert report.ready and not report.model_ready and 'Workspace: VALID' not in report.render()
    composed=composition.compose(value)
    try:
        assert composed.application.get_project(p).key=='browser-operator'
        assert composed.application._browser_plan_generator is not None
        from qa_sentinel.application import ApplicationError
        with pytest.raises(ApplicationError):composed.resolver.resolve(p)
    finally:composed.close()

@pytest.mark.parametrize('data',[{'key':'web'},{'key':'web','browser_only':True,'pytest_targets':['tests']},{'key':'web','browser_only':True,'test_cwd':'backend'}])
def test_browser_only_config_is_explicit_and_strict(data):
    with pytest.raises(ValidationError):LocalProjectConfig.model_validate(data)

@pytest.mark.parametrize('mode',['demo','preview-demo','hosted-demo'])
def test_public_demo_composition_never_configures_browser(config,tmp_path,monkeypatch,mode):
    from qa_sentinel.host.web import create_host_app
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.setattr(browser,'PlaywrightBrowserExecutor',lambda *a,**k:pytest.fail('No real browser composition'))
    monkeypatch.setattr(composition,'OpenAIModelAdapter',lambda *a,**k:pytest.fail('No real provider composition'))
    if mode=='preview-demo':
        monkeypatch.setenv('QA_SENTINEL_PREVIEW_USERNAME','synthetic-preview')
        monkeypatch.setenv('QA_SENTINEL_PREVIEW_PASSWORD','synthetic-password')
        config=HostConfig.model_validate({**config.model_dump(),'mode':mode,'host':'0.0.0.0'})
    elif mode=='hosted-demo':
        monkeypatch.setenv('QA_SENTINEL_OPERATOR_USERNAME','synthetic-operator')
        monkeypatch.setenv('QA_SENTINEL_OPERATOR_PASSWORD','synthetic-password')
        monkeypatch.setenv('QA_SENTINEL_SESSION_SECRET','synthetic-independent-session-secret-32')
        monkeypatch.setattr('qa_sentinel.host.hosted.tempfile.gettempdir',lambda:str(tmp_path))
        root=config.database.parent.parent/'hosted'
        config=HostConfig(mode=mode,host='0.0.0.0',database=root/'state.sqlite3',data_dir=root,frontend_dist=config.frontend_dist)
    host=create_host_app(config)
    try:
        composed=host.state.host_composition
        assert composed.application._browser_executor is None and composed.application._browser_plan_generator is None
        assert not any('/browser/' in route.path and any(op in route.path for op in ('/generate','/accept','/start','/generations')) for route in host.routes if hasattr(route,'path'))
    finally:host.state.host_composition.close()

def test_browser_only_local_start_reuses_build_validation_serve_without_key(config,tmp_path,monkeypatch,capsys):
    from qa_sentinel.host import start,cli
    seed(config,'web-start')
    path=tmp_path/'local.json'
    path.write_text(json.dumps({'database':str(config.database),'frontend_dist':str(config.frontend_dist),'projects':[{'key':'web-start','browser_only':True}]}),encoding='utf-8')
    calls=[]
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.setattr(start,'build_frontend',lambda config:calls.append('build') or 0)
    monkeypatch.setattr(cli,'serve_config',lambda config,**kw:calls.append(('serve',kw)) or 0)
    assert cli.main(['local','start','--config',str(path)])==0
    assert calls==['build',('serve',{'existing_database':True})]
    assert 'Overall: READY' in capsys.readouterr().out

def test_foreign_scope_body_bounds_and_injected_commands_fail_without_effect(planning,http):
    app,_,_,_,p,c,spec,mock,executor,_=planning;client,base=http
    foreign=app.create_project(key='other-http',name='Other');other=app.create_campaign(foreign.id,name='Other')
    wrong=f'/api/v1/projects/{p.id}/campaigns/{other.id}/browser'
    assert client.get(wrong+'/tests/'+str(spec.id)+'/readiness').status_code==409
    assert client.post(base+f'/tests/{spec.id}/generate',json={'script':'arbitrary'}).status_code==422
    assert client.post(base+f'/tests/{spec.id}/generate',content='x'*32769,headers={'content-type':'application/json'}).status_code==413
    assert len(mock.calls)==0 and executor.calls==[]

def test_browser_only_missing_database_never_creates_it(config,tmp_path,monkeypatch):
    from qa_sentinel.host.config import HostError
    value=HostConfig(mode='local',database=tmp_path/'absent.sqlite3',frontend_dist=config.frontend_dist,projects=[{'key':'absent','browser_only':True}])
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.setattr(composition,'bootstrap_database',lambda *a:pytest.fail('No migration/bootstrap'))
    with pytest.raises(HostError):composition.compose(value)
    assert not value.database.exists()
