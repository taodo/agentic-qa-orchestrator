"""Real controlled HTTP/Chromium security fixtures. No public internet/provider/source."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
from time import sleep
import pytest
from qa_sentinel.domain.browser_execution import BrowserExecutionPlan
from qa_sentinel.execution.playwright_browser import PlaywrightBrowserExecutor
from test_qa_runs import ready
from test_campaign_review import review
from test_qa_run_lifecycle import showcase
from test_playwright_runtime import actual_cleanup_proof


@pytest.fixture
def hardened_site():
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            seen.append(self.path)
            locations={'/one':'/final','/two':'/one','/loop':'/loop','/cross':'http://127.0.0.1:1/private',
                '/scheme':'file:///SECRET/private','/credentials':'http://user:SECRET@'+self.headers['Host']+'/final',
                '/r307':'/final','/r308':'/final'}
            if self.path in locations or self.path=='/missing':
                self.send_response(307 if self.path=='/r307' else 308 if self.path=='/r308' else 302)
                if self.path in locations:self.send_header('Location',locations[self.path])
                self.send_header('Content-Length','0');self.end_headers();return
            if self.path=='/slow':sleep(.4)
            body=b'<h1>Ready</h1>'
            if self.path=='/popup':body+=b'<button id="popup" onclick="window.open(&quot;/final&quot;)">Open</button>'
            if self.path=='/link':body+=b'<a id=link href=/one>Follow</a>'
            if self.path=='/password':body+=b'<input id=password type=password>'
            if self.path=='/image-redirect':body+=b'<img src=/one>'
            if self.path=='/frame':body+=b'<iframe src="/final"></iframe>'
            if self.path=='/worker':body+=b'<script>new Worker("/worker.js")</script>'
            if self.path=='/socket':body+=b'<script>new WebSocket("ws://"+location.host+"/socket-stream")</script>'
            if self.path=='/requests':body+=b'<script>for(let i=0;i<10;i++) fetch("/final?i="+i)</script>'
            self.send_response(500 if self.path=='/server-error' else 404 if self.path=='/not-found' else 200)
            self.send_header('Content-Type','text/html')
            if self.path=='/gzip':self.send_header('Content-Encoding','gzip')
            if self.path=='/chunked':self.send_header('Transfer-Encoding','chunked')
            if self.path=='/download':self.send_header('Content-Disposition','attachment; filename="SECRET.txt"')
            self.send_header('Content-Length',str(len(body)));self.end_headers()
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}',seen
    finally:server.shutdown();server.server_close();thread.join(timeout=2)


def configured(ready,site,steps,redirects=3):
    app,_,_,_,p,c,_,spec=ready
    app._browser_executor=PlaywrightBrowserExecutor(trusted_local_origin=site[0])
    target=app.create_target(p.id,name='Configured WEB',environment='LOCAL',configuration={'base_url':site[0]})
    app.associate_campaign_target(p.id,c.id,target_id=target.id)
    plan=BrowserExecutionPlan(steps=steps,redirect_limit=redirects)
    run=app.create_browser_qa_run(p.id,c.id,idempotency_key='controlled',plans={spec.id:plan})
    return app,p,c,run


ASSERT={'action':'ASSERT_TEXT','locator':{'strategy':'CSS','value':'h1'},'text':'Ready'}


@pytest.mark.parametrize('path,limit,expected',[('/final',0,'PASS'),('/one',1,'PASS'),('/two',2,'PASS'),('/r307',1,'PASS'),('/r308',1,'PASS'),
    ('/one',0,'BROWSER_REDIRECT_DENIED'),('/two',1,'BROWSER_REDIRECT_DENIED'),('/loop',2,'BROWSER_REDIRECT_DENIED'),
    ('/cross',3,'BROWSER_REDIRECT_DENIED'),('/scheme',3,'BROWSER_REDIRECT_DENIED'),('/credentials',3,'BROWSER_REDIRECT_DENIED'),('/missing',3,'BROWSER_REDIRECT_DENIED')])
def test_controlled_redirects_use_exact_pinned_boundary(ready,hardened_site,path,limit,expected):
    steps=({'action':'NAVIGATE','path':path},ASSERT)
    if expected=='PASS':steps+=({'action':'ASSERT_URL','path':'/final'},)
    app,p,c,run=configured(ready,hardened_site,steps,limit)
    assert hardened_site[1]==[]
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    view=app.get_qa_run_results(p.id,c.id,run.id)
    if expected=='PASS':
        assert (final.execution_status,final.qa_outcome)==('COMPLETED','PASS'),final.browser_error_code
        assert hardened_site[1][-1]=='/final' and view.tests.items[0].evidence_count==3
        # Each redirect source and terminal URL is requested once, no retry/final double-fetch.
        assert len(hardened_site[1])==len(set(hardened_site[1]))
    else:
        assert (final.execution_status,str(final.browser_error_code))==('FAILED',expected)
        assert final.qa_outcome=='NOT_EVALUATED' and view.tests.items[0].evidence_count==0
    assert '/private' not in hardened_site[1] and 'SECRET' not in final.model_dump_json()
    if path=='/loop':assert len(hardened_site[1])==limit+1


@pytest.mark.parametrize('path', ['/not-found','/server-error'])
def test_http_error_status_allows_real_assertions(ready,hardened_site,path):
    app,p,c,run=configured(ready,hardened_site,({'action':'NAVIGATE','path':path},ASSERT))
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    assert (final.execution_status,final.qa_outcome)==('COMPLETED','PASS')


@pytest.mark.parametrize('path', ['/gzip','/chunked','/download','/frame','/worker','/socket'])
def test_unsupported_capability_has_no_fabricated_assertion(ready,hardened_site,path):
    app,p,c,run=configured(ready,hardened_site,({'action':'NAVIGATE','path':path},ASSERT))
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    assert (final.execution_status,str(final.browser_error_code))==('FAILED','BROWSER_UNSUPPORTED_FEATURE')
    assert app.get_qa_run_results(p.id,c.id,run.id).tests.items[0].evidence_count==0
    assert 'SECRET' not in final.model_dump_json()


def test_page_closure_is_crash_not_assertion_failure(ready,hardened_site,monkeypatch):
    from playwright.async_api import Page
    original=Page.goto
    async def close_after_navigation(self,*a,**k):
        result=await original(self,*a,**k);await self.close();return result
    monkeypatch.setattr(Page,'goto',close_after_navigation)
    app,p,c,run=configured(ready,hardened_site,({'action':'NAVIGATE','path':'/final'},ASSERT))
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    assert (final.execution_status,str(final.browser_error_code))==('FAILED','BROWSER_CRASHED')
    assert app.get_qa_run_results(p.id,c.id,run.id).tests.items[0].evidence_count==0


def test_navigation_timeout_is_bounded_system_failure(ready,hardened_site):
    app,p,c,run=configured(ready,hardened_site,({'action':'NAVIGATE','path':'/slow','timeout_ms':100},ASSERT))
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    assert (final.execution_status,str(final.browser_error_code))==('FAILED','BROWSER_ACTION_TIMEOUT')


def test_background_request_limit_cannot_escape_completion(ready,hardened_site,monkeypatch):
    monkeypatch.setattr('qa_sentinel.execution.browser_network.MAX_REQUESTS',3)
    app,p,c,run=configured(ready,hardened_site,({'action':'NAVIGATE','path':'/requests'},ASSERT))
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    assert (final.execution_status,str(final.browser_error_code))==('FAILED','BROWSER_UNSUPPORTED_FEATURE')
    assert app.get_qa_run_results(p.id,c.id,run.id).tests.items[0].evidence_count==0


def test_later_cleanup_failure_preserves_committed_evidence(showcase,hardened_site,monkeypatch):
    from playwright.async_api import BrowserContext,Error
    ready,_=showcase;app,_,_,_,p,c,_,_=ready
    executor=PlaywrightBrowserExecutor(trusted_local_origin=hardened_site[0]);app._browser_executor=executor
    target=app.create_target(p.id,name='Configured WEB',environment='LOCAL',configuration={'base_url':hardened_site[0]});app.associate_campaign_target(p.id,c.id,target_id=target.id)
    specs=app.list_campaign_test_specifications(p.id,c.id).items
    plans={s.id:BrowserExecutionPlan(steps=({'action':'NAVIGATE','path':'/final'},ASSERT)) for s in specs}
    run=app.create_browser_qa_run(p.id,c.id,idempotency_key='partial',plans=plans)
    original=BrowserContext.close;count=[]
    async def close(self,*a,**k):
        await original(self,*a,**k);count.append(True)
        if len(count)==2:raise Error('SECRET /local/path raw-body')
    monkeypatch.setattr(BrowserContext,'close',close)
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    assert (final.execution_status,final.qa_outcome,str(final.browser_error_code))==('FAILED','PARTIAL','BROWSER_CLEANUP_FAILED')
    tests=app.get_qa_run_results(p.id,c.id,run.id).tests.items
    assert tests[0].qa_result=='PASS' and tests[0].evidence_count==2
    assert tests[1].execution_status=='RUNNING' and tests[1].evidence_count==0
    assert tests[2].execution_status=='NOT_STARTED' and tests[2].evidence_count==0
    assert len(count)==2 and len(hardened_site[1])==2 and 'SECRET' not in final.model_dump_json()



def test_click_redirect_is_not_a_repeated_click_or_terminal_request(ready,hardened_site):
    app,p,c,run=configured(ready,hardened_site,({'action':'NAVIGATE','path':'/link'},
        {'action':'CLICK','locator':{'strategy':'CSS','value':'#link'}},ASSERT,{'action':'ASSERT_URL','path':'/final'}),1)
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    assert (final.execution_status,final.qa_outcome)==('COMPLETED','PASS'),final.browser_error_code
    assert hardened_site[1]==['/link','/one','/final']


def test_subresource_redirect_remains_unsupported(ready,hardened_site):
    app,p,c,run=configured(ready,hardened_site,({'action':'NAVIGATE','path':'/image-redirect'},ASSERT),2)
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    assert (final.execution_status,str(final.browser_error_code))==('FAILED','BROWSER_UNSUPPORTED_FEATURE')
    assert '/final' not in hardened_site[1]


def test_password_filling_remains_unsupported(ready,hardened_site):
    app,p,c,run=configured(ready,hardened_site,({'action':'NAVIGATE','path':'/password'},
        {'action':'FILL','locator':{'strategy':'CSS','value':'#password'},'value':'non-secret'}))
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    assert (final.execution_status,str(final.browser_error_code))==('FAILED','BROWSER_UNSUPPORTED_FEATURE')
