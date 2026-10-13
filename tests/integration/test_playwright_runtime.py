"""Actual Chromium against a controlled HTTP fixture. No public internet/provider/source tree."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from fastapi.testclient import TestClient
from qa_sentinel.api import create_api_app
from qa_sentinel.application import ApplicationError
from qa_sentinel.domain.browser_execution import BrowserExecutionPlan
from qa_sentinel.execution.playwright_browser import PlaywrightBrowserExecutor
from test_qa_run_lifecycle import showcase
from test_qa_runs import ready
from test_campaign_review import review


@pytest.fixture
def site():
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            seen.append(self.path)
            if self.path.startswith("/redirect"):
                self.send_response(302);self.send_header("Location","http://127.0.0.1:1/forbidden");self.send_header("Content-Length","0");self.end_headers();return
            if self.path.startswith('/escape'):
                body=b'<h1>Escape</h1><img src="http://127.0.0.1:1/private">'
            elif self.path.startswith('/scheme'):
                body=b'<a href="javascript:alert(1)">Danger</a>'
            else:
                body=(b'<h1>Done</h1>' if self.path.startswith('/done') else b"""<html><body><h1>Courses</h1>
            <label>Name<input placeholder="Your name" data-testid="name"></label>
            <label for="tier">Tier</label><select id="tier"><option value="basic">Basic</option><option value="pro">Pro</option></select>
            <label>Agree<input type="checkbox"></label><a href="/done">Continue</a>
            <button onclick="window.open('/done')">Popup</button></body></html>""")
            self.send_response(200);self.send_header("Content-Type","text/html");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}',seen
    finally: server.shutdown();server.server_close();thread.join(timeout=2)


def browser_run(ready,site,steps,key='browser'):
    app,_,_,_,p,c,_,spec=ready
    app._browser_executor=PlaywrightBrowserExecutor(trusted_local_origin=site[0])
    target=app.create_target(p.id,name='Controlled local WEB',environment='LOCAL',configuration={'base_url':site[0]})
    app.associate_campaign_target(p.id,c.id,target_id=target.id)
    plan=BrowserExecutionPlan(steps=tuple(steps))
    run=app.create_browser_qa_run(p.id,c.id,idempotency_key=key,plans={spec.id:plan})
    return app,p,c,run


NAV={'action':'NAVIGATE','path':'/'}
TEXT={'action':'ASSERT_TEXT','locator':{'strategy':'ROLE','role':'heading'},'text':'Courses'}


def test_real_all_actions_and_locator_strategies(ready,site):
    steps=[NAV,TEXT,
        {'action':'FILL','locator':{'strategy':'LABEL','value':'Name'},'value':'Ada'},
        {'action':'PRESS','locator':{'strategy':'PLACEHOLDER','value':'Your name'},'key':'Tab'},
        {'action':'FILL','locator':{'strategy':'TEST_ID','value':'name'},'value':'Lin'},
        {'action':'SELECT','locator':{'strategy':'LABEL','value':'Tier'},'value':'pro'},
        {'action':'CHECK','locator':{'strategy':'LABEL','value':'Agree'},'checked':True},
        {'action':'WAIT_FOR','locator':{'strategy':'CSS','value':'h1'},'condition':'VISIBLE'},
        {'action':'ASSERT_VISIBLE','locator':{'strategy':'TEXT','value':'Courses'}},
        {'action':'CLICK','locator':{'strategy':'ROLE','role':'link','name':'Continue'}},
        {'action':'ASSERT_URL','path':'/done'},
        {'action':'ASSERT_TEXT','locator':{'strategy':'CSS','value':'h1'},'text':'Done'}]
    app,p,c,run=browser_run(ready,site,steps)
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    assert final.execution_status=='COMPLETED' and final.qa_outcome=='PASS',(final.browser_error_code,site[1])
    view=app.get_qa_run_results(p.id,c.id,run.id)
    assert view.tests.items[0].evidence_count==5
    for evidence in view.tests.items[0].evidence.items:
        assert evidence.executor_kind=='WEB_BROWSER' and evidence.payload.plan_hash==view.tests.items[0].browser_plan.plan_hash
        assert evidence.payload.browser_version=='153.0.8010.12'
    assert '/' in site[1] and '/done' in site[1]


@pytest.mark.parametrize('assertion',[{**TEXT,'text':'wrong'},
    {'action':'ASSERT_VISIBLE','locator':{'strategy':'CSS','value':'#missing'}},
    {'action':'ASSERT_URL','path':'/wrong'}])
def test_real_assertion_mismatch_is_qa_fail(ready,site,assertion):
    app,p,c,run=browser_run(ready,site,[NAV,assertion])
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    assert (final.execution_status,final.qa_outcome,final.browser_error_code)==('COMPLETED','FAIL',None)
    test=app.get_qa_run_results(p.id,c.id,run.id).tests.items[0]
    assert test.execution_status=='COMPLETED' and test.qa_result=='FAIL' and test.evidence_count==2
    assert test.evidence.items[-1].payload.matched is False


@pytest.mark.parametrize('steps,code',[
    ([{'action':'NAVIGATE','path':'/redirect'}],'BROWSER_REDIRECT_DENIED'),
    ([{'action':'NAVIGATE','path':'/escape'}],'BROWSER_NETWORK_DENIED'),
    ([{'action':'NAVIGATE','path':'/scheme'},{'action':'CLICK','locator':{'strategy':'ROLE','role':'link','name':'Danger'}}],'BROWSER_NETWORK_DENIED'),
    ([NAV,{'action':'WAIT_FOR','locator':{'strategy':'CSS','value':'#missing'},'condition':'VISIBLE','timeout_ms':100}],'BROWSER_ACTION_TIMEOUT'),
    ([NAV,{'action':'CLICK','locator':{'strategy':'ROLE','role':'button','name':'Popup'}}],'BROWSER_UNSUPPORTED_FEATURE')])
def test_real_policy_or_runtime_failure_no_fake_evidence(ready,site,steps,code):
    app,p,c,run=browser_run(ready,site,steps)
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    assert final.execution_status=='FAILED' and final.browser_error_code==code,final
    assert final.qa_outcome=='NOT_EVALUATED'
    assert app.get_qa_run_results(p.id,c.id,run.id).tests.items[0].evidence_count==0
    assert '/forbidden' not in site[1]


def test_seal_reopen_immutability_and_public_start_disabled(ready,site):
    app,p,c,run=browser_run(ready,site,[NAV,TEXT])
    assert run.runtime_identity.engine=='CHROMIUM' and run.executor_kind=='WEB_BROWSER'
    engine=ready[2];engine.dispose()
    saved=app.get_qa_run(p.id,c.id,run.id)
    assert saved==run and saved.runtime_identity.playwright_version=='1.63.0'
    for sql in ['UPDATE qa_runs SET executor_kind=executor_kind','UPDATE qa_run_tests SET browser_plan=browser_plan']:
        with pytest.raises(IntegrityError),engine.begin() as db: db.execute(text(sql))
    with pytest.raises(ApplicationError): app.start_qa_run(p.id,c.id,run.id)
    with TestClient(create_api_app(app)) as client:
        assert client.post(f'/api/v1/projects/{p.id}/campaigns/{c.id}/runs/{run.id}/start').status_code==409
    assert app.get_qa_run(p.id,c.id,run.id).execution_status=='CREATED'


def test_real_fail_continues_remaining_tests_and_preserves_synthetic(showcase,site):
    ready,synthetic=showcase
    app,_,_,_,p,c,_,_=ready
    app._browser_executor=PlaywrightBrowserExecutor(trusted_local_origin=site[0])
    target=app.create_target(p.id,name='Local fixture',environment='LOCAL',configuration={'base_url':site[0]})
    app.associate_campaign_target(p.id,c.id,target_id=target.id)
    specs=sorted(app.list_campaign_test_specifications(p.id,c.id).items,key=lambda s:s.logical_key)
    plans={s.id:BrowserExecutionPlan(steps=(NAV,{**TEXT,'text':'wrong' if i==0 else 'Courses'})) for i,s in enumerate(specs)}
    run=app.create_browser_qa_run(p.id,c.id,idempotency_key='mixed-real',plans=plans)
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    assert (final.execution_status,final.qa_outcome)==('COMPLETED','FAIL')
    assert [test.qa_result for test in app.list_qa_run_tests(p.id,c.id,run.id).items]==['FAIL','PASS','PASS']
    assert app.get_qa_run(p.id,c.id,synthetic.id).executor_kind=='SYNTHETIC'


def test_migration_backfill_reopen_and_downgrade_guard(ready,site):
    from alembic import command
    app,_,engine,config,p,c,_,_=ready
    legacy=app.create_qa_run(p.id,c.id,idempotency_key='legacy')
    command.downgrade(config,'0013')
    with engine.connect() as db:assert db.scalar(text('SELECT snapshot_hash FROM qa_runs'))==legacy.snapshot_hash
    command.upgrade(config,'head');command.check(config);engine.dispose()
    assert app.get_qa_run(p.id,c.id,legacy.id).executor_kind=='SYNTHETIC'
    _,_,_,sealed=browser_run(ready,site,[NAV,TEXT])
    with pytest.raises(RuntimeError,match='cannot erase browser execution history'):command.downgrade(config,'0013')
    assert app.get_qa_run(p.id,c.id,sealed.id)==sealed


def test_changed_plan_retry_rejected_before_launch(ready,site):
    app,p,c,run=browser_run(ready,site,[NAV,TEXT])
    spec=ready[-1]
    with pytest.raises(ApplicationError,match='RUN_IDEMPOTENCY_CONFLICT'):
        app.create_browser_qa_run(p.id,c.id,idempotency_key='browser',plans={spec.id:BrowserExecutionPlan(steps=(NAV,{**TEXT,'text':'changed'}))})
    assert site[1]==[] and app.get_qa_run(p.id,c.id,run.id).execution_status=='CREATED'


def test_real_unreachable_is_safe_system_failure(ready,free_tcp_port):
    site=(f'http://127.0.0.1:{free_tcp_port}',[])
    app,p,c,run=browser_run(ready,site,[NAV,TEXT])
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    assert (final.execution_status,final.browser_error_code)==('FAILED','BROWSER_TARGET_UNREACHABLE')
    assert app.get_qa_run_results(p.id,c.id,run.id).tests.items[0].evidence_count==0


@pytest.fixture(autouse=True)
def actual_cleanup_proof(monkeypatch):
    try:
        from playwright.async_api import Browser,BrowserContext
        from playwright.sync_api import sync_playwright
    except ImportError: pytest.skip("Official Playwright package unavailable; SDK-double tests remain active")
    from pathlib import Path
    with sync_playwright() as runtime:
        if not Path(runtime.chromium.executable_path).is_file():
            pytest.skip("Chromium unavailable; explicit installation required; SDK-double tests remain active")
    closed=[]
    original_browser=Browser.close;original_context=BrowserContext.close
    async def browser_close(self,*args,**kwargs):
        await original_browser(self,*args,**kwargs)
        assert not self.is_connected();closed.append('browser')
    async def context_close(self,*args,**kwargs):
        await original_context(self,*args,**kwargs);closed.append('context')
    monkeypatch.setattr(Browser,'close',browser_close);monkeypatch.setattr(BrowserContext,'close',context_close)
    yield
    if closed:assert closed.count('browser')==closed.count('context')


def test_later_browser_system_failure_preserves_earlier_evidence(showcase,site):
    ready,_=showcase
    app,_,_,_,p,c,_,_=ready
    app._browser_executor=PlaywrightBrowserExecutor(trusted_local_origin=site[0])
    target=app.create_target(p.id,name='Local fixture',environment='LOCAL',configuration={'base_url':site[0]})
    app.associate_campaign_target(p.id,c.id,target_id=target.id)
    specs=sorted(app.list_campaign_test_specifications(p.id,c.id).items,key=lambda s:s.logical_key)
    plans={s.id:BrowserExecutionPlan(steps=({'action':'NAVIGATE','path':'/redirect'},) if i==1 else (NAV,TEXT)) for i,s in enumerate(specs)}
    run=app.create_browser_qa_run(p.id,c.id,idempotency_key='partial-real',plans=plans)
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    assert (final.execution_status,final.qa_outcome,final.browser_error_code)==('FAILED','PARTIAL','BROWSER_REDIRECT_DENIED')
    tests=app.get_qa_run_results(p.id,c.id,run.id).tests.items
    assert tests[0].qa_result=='PASS' and tests[0].evidence_count==2
    assert tests[1].execution_status=='RUNNING' and tests[1].evidence_count==0
    assert tests[2].execution_status=='NOT_STARTED' and tests[2].evidence_count==0
