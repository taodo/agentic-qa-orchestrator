"""Ingress body limit applies before JSON parsing, with or without Content-Length."""
import asyncio
from qa_sentinel.api.source_body_limit import SourceBodyLimit, MAX_SOURCE_BODY_BYTES


def test_chunked_body_is_counted_without_following_more_messages():
    async def run():
        called=[];sent=[];chunks=iter([{'type':'http.request','body':b'x'*300000,'more_body':True},
                                     {'type':'http.request','body':b'x'*300000,'more_body':True}])
        async def receive():return next(chunks)
        async def send(message):sent.append(message)
        async def app(*args):called.append(True)
        scope={'type':'http','method':'POST','path':'/api/v1/projects/p/campaigns/c/sources','headers':[]}
        await SourceBodyLimit(app)(scope,receive,send)
        assert not called and sent[0]['status']==413
        assert b'SOURCE_SIZE_LIMIT' in sent[1]['body']
    asyncio.run(run())


def test_declared_oversize_does_not_read_body_and_other_routes_are_unchanged():
    async def run():
        called=[];sent=[]
        async def receive():raise AssertionError('Declared excessive source must not be read')
        async def send(message):sent.append(message)
        async def app(*args):called.append(True)
        scope={'type':'http','method':'POST','path':'/api/v1/projects/p/campaigns/c/sources',
            'headers':[(b'content-length',str(MAX_SOURCE_BODY_BYTES+1).encode())]}
        limiter=SourceBodyLimit(app)
        await limiter(scope,receive,send)
        assert not called and sent[0]['status']==413
        await limiter({**scope,'path':'/api/v1/tasks/t/run'},receive,send)
        assert called==[True]
    asyncio.run(run())


def test_empty_stream_chunks_and_utf8_body_are_replayed_exactly():
    async def run():
        chunks = iter([{'type':'http.request','body':b'','more_body':True} for _ in range(1000)] +
            [{'type':'http.request','body':'λ'.encode('utf-8'),'more_body':False}])
        async def receive():return next(chunks)
        async def send(message):raise AssertionError('No rejection expected')
        async def app(scope, receive, send):
            assert await receive() == {'type':'http.request','body':'λ'.encode('utf-8'),'more_body':False}
        scope={'type':'http','method':'POST','path':'/api/v1/projects/p/campaigns/c/sources','headers':[]}
        await SourceBodyLimit(app)(scope,receive,send)
    asyncio.run(run())
