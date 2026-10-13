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


# All wire/DNS/TLS failures below are deterministic doubles; no public connections.
class WireRequest:
    def __init__(self,url='https://example.com/start',method='GET',body=b'',headers=None):
        self.url,self.method,self.post_data_buffer=url,method,body
        self.headers=headers or {}
    async def all_headers(self): return self.headers


def wire_transport(monkeypatch,raw=b'HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\n',data=b'body',peer='8.8.8.8',failure=None):
    import qa_sentinel.execution.browser_network as module
    from types import SimpleNamespace
    calls=[];writers=[]
    async def resolution(*args):return [(2,1,6,'',('8.8.8.8',443))]
    monkeypatch.setattr(module,'resolve',resolution)
    async def connect(address,port,**kwargs):
        calls.append((address,port,kwargs))
        if failure: raise failure
        class Reader:
            async def readuntil(self,delimiter):return raw
            async def readexactly(self,length):
                if len(data)<length:raise asyncio.IncompleteReadError(data,length)
                return data[:length]
        class Writer:
            closed=False
            def get_extra_info(self,key):return (peer,443)
            def write(self,wire):self.wire=wire
            async def drain(self):pass
            def close(self):self.closed=True
            async def wait_closed(self):pass
        writer=Writer();writers.append(writer)
        return Reader(),writer
    monkeypatch.setattr(asyncio,'open_connection',connect)
    return calls,writers


@pytest.mark.parametrize('status',[200,404,500])
def test_real_http_status_is_not_an_automatic_qa_failure(monkeypatch,status):
    calls,writers=wire_transport(monkeypatch,f'HTTP/1.1 {status} Response\r\nContent-Length: 4\r\n\r\n'.encode())
    result=asyncio.run(PinnedNetwork(target()).fetch(WireRequest()))
    assert result[0]==status and result[2]==b'body' and writers[0].closed
    assert calls[0][0]=='8.8.8.8' and calls[0][2]['server_hostname']=='example.com'


@pytest.mark.parametrize('mode', ['chunked','gzip','unknown-length','duplicate-length','oversized-body','negative-length',
    'oversized-header','header-count','invalid-header','invalid-status','request-body','request-header-count','request-header-size'])
def test_proxy_bounds_and_unsupported_framing_fail_closed(monkeypatch,mode):
    headers={'chunked':b'Transfer-Encoding: chunked\r\nContent-Length: 4',
        'gzip':b'Content-Encoding: gzip\r\nContent-Length: 4','unknown-length':b'X-Only: true',
        'duplicate-length':b'Content-Length: 4\r\nContent-Length: 0','oversized-body':b'Content-Length: 4194305',
        'negative-length':b'Content-Length: -1','oversized-header':b'X-Large: '+b'x'*16384,
        'header-count':b'Content-Length: 0\r\n'+b'\r\n'.join(f'X-{i}: 1'.encode() for i in range(100)),
        'invalid-header':b'bad name: value\r\nContent-Length: 4'}
    raw=b'HTTP/1.1 200 OK\r\n'+headers.get(mode,b'Content-Length: 4')+b'\r\n\r\n'
    if mode=='invalid-status':raw=b'HTTP/1.1 not-a-status SECRET\r\nContent-Length: 4\r\n\r\n'
    request=WireRequest(body=b'x'*65537 if mode=='request-body' else b'',
        headers={f'x-{i}':'v' for i in range(101)} if mode=='request-header-count' else {'x-big':'x'*16385} if mode=='request-header-size' else {})
    _,writers=wire_transport(monkeypatch,raw)
    with pytest.raises(BrowserExecutionError,match='BROWSER_UNSUPPORTED_FEATURE') as error:
        asyncio.run(PinnedNetwork(target()).fetch(request))
    assert 'SECRET' not in str(error.value) and writers[0].closed


@pytest.mark.parametrize('failure,code',[(ConnectionRefusedError('SECRET /local/path'),'BROWSER_TARGET_UNREACHABLE')])
def test_transport_failure_is_safe(monkeypatch,failure,code):
    wire_transport(monkeypatch,failure=failure)
    with pytest.raises(BrowserExecutionError,match=code) as error:asyncio.run(PinnedNetwork(target()).fetch(WireRequest()))
    assert 'SECRET' not in str(error.value)


def test_tls_certificate_error_is_safe(monkeypatch):
    import ssl
    wire_transport(monkeypatch,failure=ssl.SSLCertVerificationError('SECRET certificate /private/path'))
    with pytest.raises(BrowserExecutionError,match='BROWSER_TLS_FAILED'):asyncio.run(PinnedNetwork(target()).fetch(WireRequest()))


def test_peer_pinning_mismatch_fails_closed(monkeypatch):
    _,writers=wire_transport(monkeypatch,peer='1.1.1.1')
    with pytest.raises(BrowserExecutionError,match='BROWSER_NETWORK_DENIED'):asyncio.run(PinnedNetwork(target()).fetch(WireRequest()))
    assert writers[0].closed


def test_request_and_aggregate_response_budgets(monkeypatch):
    wire_transport(monkeypatch)
    async def check():
        network=PinnedNetwork(target());network.request_count=100
        with pytest.raises(BrowserExecutionError,match='BROWSER_UNSUPPORTED_FEATURE'):await network.fetch(WireRequest())
        network=PinnedNetwork(target());network.body_bytes=32*1024*1024
        with pytest.raises(BrowserExecutionError,match='BROWSER_UNSUPPORTED_FEATURE'):await network.fetch(WireRequest())
    asyncio.run(check())


@pytest.mark.parametrize('location',['/done','done','https://example.com/done','?page=2'])
def test_same_origin_redirect_validation_and_budget(location):
    network=PinnedNetwork(target(),redirect_limit=2)
    assert network.redirect_destination('https://example.com/start',302,location).startswith('https://example.com/')
    network.redirect_destination('https://example.com/start',307,'/done')
    with pytest.raises(BrowserExecutionError,match='BROWSER_REDIRECT_DENIED'):network.redirect_destination('https://example.com/start',308,'/done')


@pytest.mark.parametrize('location',['https://other.example/x','http://127.0.0.1/x','file:///private','javascript:alert(1)',
    '//other.example/x','https://user:SECRET@example.com/x','/x#SECRET','/x\r\nX-Secret: v','/%0aSECRET','/x\\other','',None])
def test_redirect_escapes_denied_without_leaking_location(location):
    network=PinnedNetwork(target(),redirect_limit=5)
    with pytest.raises(BrowserExecutionError,match='BROWSER_REDIRECT_DENIED') as error:
        network.redirect_destination('https://example.com/start',302,location)
    assert 'SECRET' not in str(error.value)


@pytest.mark.parametrize('status',[300,304,305,306,399])
def test_alternate_3xx_cannot_bypass_redirect_policy(status):
    with pytest.raises(BrowserExecutionError,match='BROWSER_REDIRECT_DENIED'):
        PinnedNetwork(target(),redirect_limit=5).redirect_destination('https://example.com/start',status,'/done')


def test_redirected_fetch_revalidates_dns_and_rejects_rebinding(monkeypatch):
    import qa_sentinel.execution.browser_network as module
    calls,_=wire_transport(monkeypatch,b'HTTP/1.1 302 Found\r\nLocation: /done\r\nContent-Length: 0\r\n\r\n')
    resolutions=iter(['8.8.8.8','1.1.1.1'])
    async def resolve(*args):return [(2,1,6,'',(next(resolutions),443))]
    monkeypatch.setattr(module,'resolve',resolve)
    async def check():
        network=PinnedNetwork(target(),redirect_limit=1)
        status,headers,_=await network.fetch(WireRequest())
        assert status==302
        with pytest.raises(BrowserExecutionError,match='BROWSER_NETWORK_DENIED'):
            await network.fetch(WireRequest(url=headers['location']))
    asyncio.run(check());assert len(calls)==1



def test_redirect_cookie_semantics_fail_closed(monkeypatch):
    wire_transport(monkeypatch,b'HTTP/1.1 302 Found\r\nLocation: /done\r\nSet-Cookie: session=SECRET\r\nContent-Length: 0\r\n\r\n')
    with pytest.raises(BrowserExecutionError,match='BROWSER_UNSUPPORTED_FEATURE'):
        asyncio.run(PinnedNetwork(target(),redirect_limit=1).fetch(WireRequest()))


@pytest.mark.parametrize('path',['/%25250aSECRET','/%2525252fother','/bad%escape'])
def test_nested_url_escapes_fail_closed(monkeypatch,path):
    wire_transport(monkeypatch)
    with pytest.raises(BrowserExecutionError,match='BROWSER_NETWORK_DENIED'):
        asyncio.run(PinnedNetwork(target()).fetch(WireRequest(url='https://example.com'+path)))



def test_request_header_bound_includes_transport_owned_headers(monkeypatch):
    wire_transport(monkeypatch)
    with pytest.raises(BrowserExecutionError,match='BROWSER_UNSUPPORTED_FEATURE'):
        asyncio.run(PinnedNetwork(target()).fetch(WireRequest(headers={f'x-{i}':'v' for i in range(97)})))
