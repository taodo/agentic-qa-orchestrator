"""Deterministic SDK doubles prove cleanup/error mapping even without installed browsers."""
import asyncio
from types import SimpleNamespace,ModuleType
import sys
import pytest
from qa_sentinel.execution.playwright_browser import PlaywrightBrowserExecutor
from qa_sentinel.execution.browser_network import BrowserExecutionError, PinnedNetwork
from qa_sentinel.domain.browser_execution import BrowserErrorCode
from qa_sentinel.domain.browser_execution import BrowserExecutionPlan
from test_browser_execution_foundation import browser_candidate,ready,review


@pytest.mark.parametrize('mode,expected',[('pass','PASS'),('headed','PASS'),('mismatch','FAIL'),('launch','BROWSER_LAUNCH_FAILED'),('action','BROWSER_ACTION_TIMEOUT'),('overall','BROWSER_TEST_TIMEOUT'),('cleanup','BROWSER_CLEANUP_FAILED'),('cleanup_stall','BROWSER_CLEANUP_FAILED'),('barrier_timeout','BROWSER_ACTION_TIMEOUT'),('driver','BROWSER_LAUNCH_FAILED'),('context','BROWSER_LAUNCH_FAILED'),('page','BROWSER_LAUNCH_FAILED'),('page_close','BROWSER_CRASHED'),('context_close','BROWSER_CRASHED'),('disconnect','BROWSER_CRASHED'),('assertion_stall','BROWSER_ACTION_TIMEOUT'),('cancel','CANCELLED'),
    *[(f'{stage}_{kind}', 'BROWSER_LAUNCH_FAILED') for stage in ('factory','driver','launch','context','page') for kind in ('os','runtime')],
    ('invalid_locator','BROWSER_INTERNAL_ERROR'),('strict_mode','BROWSER_INTERNAL_ERROR'),
    ('action_disconnect','BROWSER_CRASHED'),('transport','BROWSER_TARGET_UNREACHABLE'),
    ('policy_action','BROWSER_NETWORK_DENIED')])
def test_sdk_cleanup_and_truthful_error_mapping(browser_candidate,monkeypatch,mode,expected):
    _,run,test,envelope=browser_candidate
    closes=[];routes={};drafts=[];events={"page":{},"context":{},"browser":{}}
    def startup_failure(stage):
        if mode==f'{stage}_os':raise OSError('SECRET /private/startup')
        if mode==f'{stage}_runtime':raise RuntimeError('SECRET /private/startup')
    import qa_sentinel.execution.playwright_browser as runtime
    original_draft=runtime.EvidenceDraft
    def draft(**kwargs):
        drafts.append(kwargs)
        return original_draft(**kwargs)
    monkeypatch.setattr(runtime,'EvidenceDraft',draft)
    class Error(Exception):pass
    class Timeout(Error):pass
    class Locator:
        async def wait_for(self,**kwargs):
            if mode=='invalid_locator':raise Error('SECRET invalid CSS selector /private/action')
            if mode=='strict_mode':raise Error('SECRET strict-mode locator violation /private/action')
            if mode=='action_disconnect':raise Error('SECRET disconnected /private/action')
            if mode=='assertion_stall': await asyncio.Event().wait()
        async def inner_text(self,**kwargs):return 'wrong' if mode=='mismatch' else 'Courses'
    class Page:
        main_frame=object()
        def on(self,name,handler):events["page"][name]=handler
        titles=0
        async def title(self):
            self.titles+=1
            if mode=='barrier_timeout' and self.titles==2:await asyncio.Event().wait()
            return 'test'
        async def goto(self,*args,**kwargs):
            if mode in {'transport','policy_action'}:
                class Route:
                    request=SimpleNamespace(frame=self.main_frame,url=args[0])
                    async def abort(self):pass
                await routes['handler'](Route())
                raise Error('SECRET navigation aborted /private/transport')
            if mode=='action':raise Timeout('SECRET /private/path')
            if mode in {'overall','cancel'}:await asyncio.Event().wait()
            if mode=='page_close':events['page']['close'](self)
            if mode=='context_close':events['context']['close'](None)
            if mode=='disconnect':events['browser']['disconnected'](None)
        def locator(self,*args):return Locator()
    class Context:
        async def new_page(self):
            startup_failure('page')
            if mode=='page':raise Error('SECRET /private/page')
            return Page()
        async def route(self,*args):routes['handler']=args[1]
        async def route_web_socket(self,*args):pass
        async def unroute_all(self,**kwargs):pass
        def on(self,name,handler):events["context"][name]=handler
        async def close(self):
            closes.append('context')
            if mode=='cleanup':raise Error('SECRET /private/path')
            if mode=='cleanup_stall':await asyncio.Event().wait()
    class Browser:
        def on(self,name,handler):events["browser"][name]=handler
        def is_connected(self):return mode!='action_disconnect'
        version='153.0.8010.12'
        async def new_context(self,**kwargs):
            startup_failure('context')
            assert kwargs["permissions"]==[] and kwargs["service_workers"]=="block" and not kwargs["accept_downloads"]
            if mode=='context':raise Error('SECRET /private/context')
            return Context()
        async def close(self):closes.append('browser')
    class Chromium:
        async def launch(self,**kwargs):
            startup_failure('launch')
            assert '--deny-permission-prompts' in kwargs['args']
            assert kwargs['headless']==(mode!='headed') and 'executable_path' not in kwargs
            assert 'OPENAI_API_KEY' not in kwargs['env']
            if mode=='launch':raise Error('SECRET /private/path')
            return Browser()
    class Driver:
        chromium=Chromium()
        async def stop(self):closes.append('driver')
    class Manager:
        async def start(self):
            startup_failure('driver')
            if mode=='driver':raise Error('SECRET /private/driver')
            return Driver()
        async def __aexit__(self,*args):closes.append('manager')
    def manager_factory():
        startup_failure('factory')
        return Manager()
    sdk=ModuleType('playwright.async_api');sdk.async_playwright=manager_factory;sdk.Error=Error;sdk.TimeoutError=Timeout
    monkeypatch.setitem(sys.modules,'playwright.async_api',sdk)
    class Network:
        authority=('https','example.com',443)
        def __init__(self,*args,**kwargs):pass
        async def addresses(self):return {'8.8.8.8'}
    if mode=='transport':
        class RefusedNetwork(PinnedNetwork):
            async def addresses(self):
                self.pinned=frozenset({'8.8.8.8'})
                return self.pinned
        async def refused(*args,**kwargs):
            raise ConnectionRefusedError('SECRET /private/connection')
        monkeypatch.setattr(asyncio,'open_connection',refused)
        Network=RefusedNetwork
    elif mode=='policy_action':
        async def denied(self,request):raise BrowserExecutionError(BrowserErrorCode.NETWORK)
        Network.fetch=denied
    monkeypatch.setattr(runtime,'PinnedNetwork',Network)
    executor=object.__new__(PlaywrightBrowserExecutor)
    executor.trusted_local_origin=None
    executor.mode="HEADED" if mode=="headed" else "HEADLESS"
    executor.identity=SimpleNamespace(browser_version='153.0.8010.12')
    plan=BrowserExecutionPlan(steps=({'action':'NAVIGATE','path':'/','timeout_ms':1000},
        {'action':'ASSERT_TEXT','locator':{'strategy':'CSS','value':'h1'},'text':'Courses','timeout_ms':100 if mode in {'barrier_timeout','assertion_stall'} else 1000}),test_timeout_ms=1000)
    candidate=envelope.model_copy(update={'plan':plan})
    if expected=='CANCELLED':
        async def cancel():
            task=asyncio.create_task(executor._run(candidate,run))
            await asyncio.sleep(.05);task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
        asyncio.run(cancel())
    elif expected in {'PASS','FAIL'}:
        result=asyncio.run(executor._run(candidate,run));assert result.qa_result==expected
        assert all('SECRET' not in item.summary for item in result.evidence)
    else:
        with pytest.raises(BrowserExecutionError,match=expected) as error:asyncio.run(executor._run(candidate,run))
        assert error.value.code.value==expected
        assert 'SECRET' not in str(error.value)
        assert drafts==[]  # Failed execution must not fabricate assertion/result evidence.
    stage=mode.split('_')[0]
    assert closes==([] if stage=='factory' else ['manager'] if stage=='driver' else ['driver'] if stage=='launch' else ['browser','driver'] if stage=='context' and mode!='context_close' else ['context','browser','driver'])
