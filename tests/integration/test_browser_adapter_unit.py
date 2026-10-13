"""Deterministic SDK doubles prove cleanup/error mapping even without installed browsers."""
import asyncio
from types import SimpleNamespace,ModuleType
import sys
import pytest
from qa_sentinel.execution.playwright_browser import PlaywrightBrowserExecutor
from qa_sentinel.execution.browser_network import BrowserExecutionError
from qa_sentinel.domain.browser_execution import BrowserExecutionPlan
from test_browser_execution_foundation import browser_candidate,ready,review


@pytest.mark.parametrize('mode,expected',[('pass','PASS'),('mismatch','FAIL'),('launch','BROWSER_LAUNCH_FAILED'),('action','BROWSER_ACTION_TIMEOUT'),('overall','BROWSER_TEST_TIMEOUT'),('cleanup','BROWSER_CLEANUP_FAILED'),('cleanup_stall','BROWSER_CLEANUP_FAILED'),('barrier_timeout','BROWSER_ACTION_TIMEOUT'),('driver','BROWSER_LAUNCH_FAILED'),('context','BROWSER_LAUNCH_FAILED'),('page','BROWSER_LAUNCH_FAILED'),('page_close','BROWSER_CRASHED'),('context_close','BROWSER_CRASHED'),('disconnect','BROWSER_CRASHED'),('assertion_stall','BROWSER_ACTION_TIMEOUT'),('cancel','CANCELLED')])
def test_sdk_cleanup_and_truthful_error_mapping(browser_candidate,monkeypatch,mode,expected):
    _,run,test,envelope=browser_candidate
    closes=[];events={"page":{},"context":{},"browser":{}}
    class Error(Exception):pass
    class Timeout(Error):pass
    class Locator:
        async def wait_for(self,**kwargs):
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
            if mode=='action':raise Timeout('SECRET /private/path')
            if mode in {'overall','cancel'}:await asyncio.Event().wait()
            if mode=='page_close':events['page']['close'](self)
            if mode=='context_close':events['context']['close'](None)
            if mode=='disconnect':events['browser']['disconnected'](None)
        def locator(self,*args):return Locator()
    class Context:
        async def new_page(self):
            if mode=='page':raise Error('SECRET /private/page')
            return Page()
        async def route(self,*args):pass
        async def route_web_socket(self,*args):pass
        async def unroute_all(self,**kwargs):pass
        def on(self,name,handler):events["context"][name]=handler
        async def close(self):
            closes.append('context')
            if mode=='cleanup':raise Error('SECRET /private/path')
            if mode=='cleanup_stall':await asyncio.Event().wait()
    class Browser:
        def on(self,name,handler):events["browser"][name]=handler
        version='153.0.8010.12'
        async def new_context(self,**kwargs):
            assert kwargs["permissions"]==[] and kwargs["service_workers"]=="block" and not kwargs["accept_downloads"]
            if mode=='context':raise Error('SECRET /private/context')
            return Context()
        async def close(self):closes.append('browser')
    class Chromium:
        async def launch(self,**kwargs):
            assert '--deny-permission-prompts' in kwargs['args']
            assert kwargs['headless'] and 'executable_path' not in kwargs
            assert 'OPENAI_API_KEY' not in kwargs['env']
            if mode=='launch':raise Error('SECRET /private/path')
            return Browser()
    class Driver:
        chromium=Chromium()
        async def stop(self):closes.append('driver')
    class Manager:
        async def start(self):
            if mode=='driver':raise Error('SECRET /private/driver')
            return Driver()
        async def __aexit__(self,*args):closes.append('manager')
    sdk=ModuleType('playwright.async_api');sdk.async_playwright=Manager;sdk.Error=Error;sdk.TimeoutError=Timeout
    monkeypatch.setitem(sys.modules,'playwright.async_api',sdk)
    class Network:
        authority=('https','example.com',443)
        def __init__(self,*args,**kwargs):pass
        async def addresses(self):return {'8.8.8.8'}
    monkeypatch.setattr('qa_sentinel.execution.playwright_browser.PinnedNetwork',Network)
    executor=object.__new__(PlaywrightBrowserExecutor)
    executor.trusted_local_origin=None
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
        assert 'SECRET' not in str(error.value)
    assert closes==(['manager'] if mode=='driver' else ['driver'] if mode=='launch' else ['browser','driver'] if mode=='context' else ['context','browser','driver'])
