"""Disposable generic Target, production local host HTTP path, real Chromium, fake model."""
from pathlib import Path
from fastapi.testclient import TestClient
import pytest
from qa_sentinel.host.config import HostConfig
from qa_sentinel.host.web import create_host_app
from qa_sentinel.host import composition,browser
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from qa_sentinel.execution.playwright_browser import PlaywrightBrowserExecutor
from test_local_web_e2e import web_setup,sites,seed,available_chromium

@pytest.mark.parametrize('actual,outcome',[('Expected','PASS'),('Mismatch','FAIL')])
def test_source_free_http_generate_accept_start_real_browser(web_setup,sites,tmp_path,monkeypatch,actual,outcome):
    available_chromium()
    url,seen,_=sites('/page',actual)
    p,c,spec,_=seed(web_setup,key='generic-http',url=url,path='/page',expected='Expected',locator={'strategy':'CSS','value':'h1'})
    *_,database,mock=web_setup
    monkeypatch.setattr(browser,'PlaywrightBrowserExecutor',lambda:PlaywrightBrowserExecutor(trusted_local_origin=url))
    monkeypatch.setattr(composition,'OpenAIModelAdapter',lambda:OpenAIModelAdapter(client=mock.client))
    monkeypatch.setattr(composition,'real_components',lambda *a:pytest.fail('No source workspace'))
    dist=tmp_path/'dist';dist.mkdir();(dist/'index.html').write_text('<!doctype html>',encoding='utf-8')
    config=HostConfig(mode='local',database=database,frontend_dist=dist,projects=[{'key':p.key,'browser_only':True}])
    host=create_host_app(config,existing_database=True)
    base=f'/api/v1/projects/{p.id}/campaigns/{c.id}'
    with TestClient(host,base_url='http://127.0.0.1:8000',client=('127.0.0.1',1234),headers={'origin':'http://127.0.0.1:8000'}) as client:
        assert client.get(base+'/browser/tests/'+str(spec.id)+'/readiness').json()['status']=='AVAILABLE'
        generated=client.post(base+'/browser/tests/'+str(spec.id)+'/generate',json={});assert generated.status_code==200,generated.text
        candidate=generated.json();assert candidate['status']=='SUCCEEDED' and len(mock.calls)==1 and seen==[]
        assert client.get(base+'/browser/generations/'+candidate['id']).json()==candidate and seen==[]
        accepted=client.post(base+'/browser/generations/'+candidate['id']+'/accept',json={'idempotency_key':'explicit'})
        assert accepted.status_code==201,accepted.text
        run=accepted.json();assert run['execution_status']=='CREATED' and seen==[] and len(mock.calls)==1
        monkeypatch.delenv('OPENAI_API_KEY')
        finished=client.post(base+'/browser/runs/'+run['id']+'/start',json={})
        assert finished.status_code==200,finished.text
        assert finished.json()['execution_status']=='COMPLETED' and finished.json()['qa_outcome']==outcome
        results=client.get(base+'/runs/'+run['id']+'/results').json()
        assert results['run']['executor_kind']=='WEB_BROWSER' and results['summary']['completed']==1
        assert seen==['/page'] and len(mock.calls)==1
        assert 'synthetic-do-not-render' not in generated.text+accepted.text+finished.text
