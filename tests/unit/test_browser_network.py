"""Resolved-address admission is pinned, bounded and never uses live internet."""
import asyncio
import socket
import pytest
from qa_sentinel.domain.target import TargetSnapshot, TargetUnderTest
from uuid import uuid4
from qa_sentinel.execution.browser_network import PinnedNetwork, BrowserExecutionError
from qa_sentinel.execution.playwright_browser import PlaywrightBrowserExecutor


def target(url='https://example.com'):
    return TargetSnapshot.capture(TargetUnderTest(project_id=uuid4(),name='WEB',environment='STAGING',configuration={'base_url':url}))


@pytest.mark.parametrize('addresses',[['10.0.0.1'],['169.254.169.254'],['127.0.0.1'],['::1'],['8.8.8.8','10.0.0.1']])
def test_public_name_resolving_private_rejected(monkeypatch,addresses):
    async def check():
        loop=asyncio.get_running_loop()
        def resolve(*args,**kwargs):return [(2,1,6,'',(address,443)) for address in addresses]
        monkeypatch.setattr(socket,'getaddrinfo',resolve)
        with pytest.raises(BrowserExecutionError,match='BROWSER_NETWORK_DENIED'): await PinnedNetwork(target()).addresses()
    asyncio.run(check())


def test_rebinding_rejected_before_connection(monkeypatch):
    async def check():
        loop=asyncio.get_running_loop();calls=iter(['8.8.8.8','1.1.1.1'])
        def resolve(*args,**kwargs):return [(2,1,6,'',(next(calls),443))]
        monkeypatch.setattr(socket,'getaddrinfo',resolve)
        network=PinnedNetwork(target());assert await network.addresses()=={'8.8.8.8'}
        with pytest.raises(BrowserExecutionError,match='BROWSER_NETWORK_DENIED'):await network.addresses()
    asyncio.run(check())


@pytest.mark.parametrize('url',['https://example.com','http://10.0.0.1','file:///tmp/a'])
def test_trusted_local_override_cannot_allow_general_private_egress(url):
    with pytest.raises((BrowserExecutionError,ValueError)):PlaywrightBrowserExecutor(trusted_local_origin=url)


@pytest.mark.parametrize('strategy,method', [('ROLE','get_by_role'),('LABEL','get_by_label'),('TEXT','get_by_text'),('TEST_ID','get_by_test_id'),('PLACEHOLDER','get_by_placeholder'),('CSS','locator')])
def test_locator_mapping_without_sdk(strategy,method):
    from qa_sentinel.domain.browser_execution import BrowserExecutionPlan
    calls=[]
    class Page:
        def __getattr__(self,name):
            def capture(*args,**kwargs):calls.append((name,args,kwargs));return self
            return capture
    intent={'strategy':strategy,'role':'button','name':'Save'} if strategy=='ROLE' else {'strategy':strategy,'value':'button'}
    locator=BrowserExecutionPlan(steps=({'action':'CLICK','locator':intent},)).steps[0].locator
    PlaywrightBrowserExecutor.locator(Page(),locator)
    assert calls[0][0]==method
    if strategy=='CSS':assert calls[0][1]==('css=button',)



def test_dns_failure_safe_and_no_raw_details(monkeypatch):
    async def check():
        def resolve(*args,**kwargs):raise OSError('SECRET /local/path')
        monkeypatch.setattr(socket,'getaddrinfo',resolve)
        with pytest.raises(BrowserExecutionError,match='BROWSER_DNS_FAILED') as error:await PinnedNetwork(target()).addresses()
        assert 'SECRET' not in str(error.value)
    asyncio.run(check())


def test_cross_origin_denied_before_dns_or_connect(monkeypatch):
    async def check():
        class Request:url='https://other.example/private'
        async def forbidden(*args,**kwargs):raise AssertionError('No connection allowed')
        monkeypatch.setattr(asyncio.get_running_loop(),'getaddrinfo',forbidden)
        monkeypatch.setattr(asyncio,'open_connection',forbidden)
        with pytest.raises(BrowserExecutionError,match='BROWSER_NETWORK_DENIED'):await PinnedNetwork(target()).fetch(Request())
    asyncio.run(check())
