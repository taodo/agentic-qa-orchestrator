"""Deterministic SDK doubles prove cleanup/error mapping even without installed browsers."""
import asyncio
from types import SimpleNamespace,ModuleType
import sys
import pytest
from qa_sentinel.execution.playwright_browser import PlaywrightBrowserExecutor
from qa_sentinel.execution.browser_network import BrowserExecutionError
from qa_sentinel.domain.browser_execution import BrowserExecutionPlan
from test_browser_execution_foundation import browser_candidate,ready,review


@pytest.mark.parametrize('mode,expected',[('pass','PASS'),('mismatch','FAIL'),('launch','BROWSER_LAUNCH_FAILED'),('action','BROWSER_ACTION_TIMEOUT'),('overall','BROWSER_TEST_TIMEOUT'),('cleanup','BROWSER_CLEANUP_FAILED'),('cleanup_stall','BROWSER_CLEANUP_FAILED'),('barrier_timeout','BROWSER_ACTION_TIMEOUT')])
def test_sdk_cleanup_and_truthful_error_mapping(browser_candidate,monkeypatch,mode,expected):
    _,run,test,envelope=browser_candidate
    closes=[]
    class Error(Exception):pass
    class Timeout(Error):pass
    class Locator:
        async def wait_for(self,**kwargs):pass
        async def inner_text(self,**kwargs):return 'wrong' if mode=='mismatch' else 'Courses'
    class Page:
        main_frame=object()
        def on(self,*args):pass
        titles=0
        async def title(self):
            self.titles+=1
            if mode=='barrier_timeout' and self.titles==2:await asyncio.Event().wait()
            return 'test'
        async def goto(self,*args,**kwargs):
            if mode=='action':raise Timeout('SECRET /private/path')
            if mode=='overall':await asyncio.Event().wait()
        def locator(self,*args):return Locator()
    class Context:
        async def new_page(self):return Page()
        async def route(self,*args):pass
        async def route_web_socket(self,*args):pass
        def on(self,*args):pass
        async def close(self):
            closes.append('context')
            if mode=='cleanup':raise Error('SECRET /private/path')
            if mode=='cleanup_stall':await asyncio.Event().wait()
    class Browser:
        version='153.0.8010.12'
        async def new_context(self,**kwargs):return Context()
        async def close(self):closes.append('browser')
    class Chromium:
        async def launch(self,**kwargs):
            assert kwargs['headless'] and 'executable_path' not in kwargs
            assert 'OPENAI_API_KEY' not in kwargs['env']
            if mode=='launch':raise Error('SECRET /private/path')
            return Browser()
    class Driver:
        chromium=Chromium()
        async def stop(self):closes.append('driver')
    class Manager:
        async def start(self):return Driver()
    sdk=ModuleType('playwright.async_api');sdk.async_playwright=Manager;sdk.Error=Error;sdk.TimeoutError=Timeout
    monkeypatch.setitem(sys.modules,'playwright.async_api',sdk)
    class Network:
        authority=('https','example.com',443)
        def __init__(self,*args):pass
        async def addresses(self):return {'8.8.8.8'}
    monkeypatch.setattr('qa_sentinel.execution.playwright_browser.PinnedNetwork',Network)
    executor=object.__new__(PlaywrightBrowserExecutor)
    executor.trusted_local_origin=None
    executor.identity=SimpleNamespace(browser_version='153.0.8010.12')
    plan=BrowserExecutionPlan(steps=({'action':'NAVIGATE','path':'/','timeout_ms':1000},
        {'action':'ASSERT_TEXT','locator':{'strategy':'CSS','value':'h1'},'text':'Courses','timeout_ms':100 if mode=='barrier_timeout' else 1000}),test_timeout_ms=1000)
    candidate=envelope.model_copy(update={'plan':plan})
    if expected in {'PASS','FAIL'}:
        result=asyncio.run(executor._run(candidate,run));assert result.qa_result==expected
        assert all('SECRET' not in item.summary for item in result.evidence)
    else:
        with pytest.raises(BrowserExecutionError,match=expected) as error:asyncio.run(executor._run(candidate,run))
        assert 'SECRET' not in str(error.value)
    assert closes==(['driver'] if mode=='launch' else ['context','browser','driver'])
