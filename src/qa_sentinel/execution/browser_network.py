"""Pinned bounded HTTP(S) transport for intercepted browser traffic. No raw persistence."""
import asyncio
from ipaddress import ip_address
import ssl
import socket
from threading import Thread, BoundedSemaphore
from urllib.parse import urlsplit
from qa_sentinel.domain.target import web_base_url
from .browser_policy import BrowserExecutionPolicy
from qa_sentinel.domain.browser_execution import BrowserErrorCode


_DNS_SLOTS=BoundedSemaphore(4)


async def resolve(host,port):
    # A stuck OS resolver cannot block asyncio.run executor shutdown or queue unlimited work.
    if not _DNS_SLOTS.acquire(blocking=False): raise BrowserExecutionError(BrowserErrorCode.DNS)
    loop=asyncio.get_running_loop();future=loop.create_future()
    def finish(value,error):
        if not future.done():
            if error: future.set_exception(BrowserExecutionError(BrowserErrorCode.DNS))
            else: future.set_result(value)
    def worker():
        value=None;error=False
        try: value=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
        except Exception: error=True
        finally:
            _DNS_SLOTS.release()
            try: loop.call_soon_threadsafe(finish,value,error)
            except RuntimeError: pass  # Timed-out loop already closed; no result or connection is created.
    try: Thread(target=worker,daemon=True,name="qa-browser-dns").start()
    except Exception:
        _DNS_SLOTS.release();raise BrowserExecutionError(BrowserErrorCode.DNS) from None
    return await asyncio.wait_for(future,2)


class BrowserExecutionError(RuntimeError):
    def __init__(self,code):
        self.code=BrowserErrorCode(code)
        super().__init__(self.code.value)


def origin(url):
    p=urlsplit(url)
    if p.scheme not in {"http","https"} or p.username or p.password or not p.hostname:
        raise BrowserExecutionError(BrowserErrorCode.NETWORK)
    return p.scheme,p.hostname.lower(),p.port or (443 if p.scheme=="https" else 80)


class PinnedNetwork:
    def __init__(self,target, trusted_local_origin=None):
        self.target=target
        self.authority=origin(target.base_url)
        self.local=trusted_local_origin is not None and origin(web_base_url(trusted_local_origin))==self.authority
        BrowserExecutionPolicy(allow_private_destinations=self.local).validate_target(target)
        self.pinned=None
        self.request_count=0
        self.inflight=asyncio.Semaphore(8)

    async def addresses(self):
        try:
            try:
                numeric=ip_address(self.authority[1])
            except ValueError:
                infos=await resolve(self.authority[1],self.authority[2])
            else:
                infos=[(None,None,None,None,(str(numeric),self.authority[2]))]
        except Exception:
            raise BrowserExecutionError(BrowserErrorCode.DNS) from None
        addresses=frozenset(info[4][0] for info in infos)
        if not addresses or len(addresses)>16: raise BrowserExecutionError(BrowserErrorCode.DNS)
        for raw in addresses:
            address=ip_address(raw)
            mapped=getattr(address,"ipv4_mapped",None)
            if self.local and not address.is_loopback: raise BrowserExecutionError(BrowserErrorCode.NETWORK)
            if (address.is_multicast or getattr(address,"is_site_local",False) or
                    (not self.local and (not address.is_global or (mapped is not None and not mapped.is_global)))):
                raise BrowserExecutionError(BrowserErrorCode.NETWORK)
            # Trusted local access is limited to this exact sealed origin, not general private egress.
        if self.pinned is not None and addresses!=self.pinned:
            raise BrowserExecutionError(BrowserErrorCode.NETWORK)
        self.pinned=addresses
        return addresses

    async def fetch(self,request):
        self.request_count+=1
        if self.request_count>100: raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
        async with self.inflight:
            return await self._fetch(request)

    async def _fetch(self,request):
        if origin(request.url)!=self.authority: raise BrowserExecutionError(BrowserErrorCode.NETWORK)
        await self.addresses()  # Detect rebinding; connection never uses a second DNS resolution.
        scheme,host,port=self.authority
        address=sorted(self.pinned)[0]
        try:
            reader,writer=await asyncio.wait_for(asyncio.open_connection(address,port,
                ssl=ssl.create_default_context() if scheme=="https" else None,
                server_hostname=host if scheme=="https" else None,limit=32768),3)
        except ssl.SSLError:
            raise BrowserExecutionError(BrowserErrorCode.TLS) from None
        except Exception:
            raise BrowserExecutionError(BrowserErrorCode.UNREACHABLE) from None
        try:
            if writer.get_extra_info("peername")[0] not in self.pinned:
                raise BrowserExecutionError(BrowserErrorCode.NETWORK)
            p=urlsplit(request.url)
            path=p.path or "/"
            if p.query: path+="?"+p.query
            method=request.method
            if method not in {"GET","HEAD","POST","PUT","PATCH","DELETE","OPTIONS"}:
                raise BrowserExecutionError(BrowserErrorCode.NETWORK)
            body=request.post_data_buffer or b""
            if len(body)>65536: raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
            headers=await request.all_headers()
            headers={k:v for k,v in headers.items() if k.lower() not in {"host","connection","content-length","accept-encoding","proxy-authorization","transfer-encoding"}}
            if len(headers)>100 or sum(len(k)+len(v) for k,v in headers.items())>16384:
                raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
            authority=p.netloc
            headers.update({"host":authority,"connection":"close","accept-encoding":"identity","content-length":str(len(body))})
            if any("\r" in k+v or "\n" in k+v for k,v in headers.items()): raise BrowserExecutionError(BrowserErrorCode.NETWORK)
            wire=f"{method} {path} HTTP/1.1\r\n"+"".join(f"{k}: {v}\r\n" for k,v in headers.items())+"\r\n"
            writer.write(wire.encode("latin-1")+body);await writer.drain()
            raw=await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"),5)
            if len(raw)>16384: raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
            lines=raw.decode("latin-1").split("\r\n")
            status=int(lines[0].split()[1])
            response_headers={}
            for line in lines[1:]:
                if line:
                    key,value=line.split(":",1);response_headers[key.lower()]=value.strip()
            # Every redirect is denied before Chromium receives a Location response.
            if 300<=status<400: raise BrowserExecutionError(BrowserErrorCode.REDIRECT)
            if response_headers.get("transfer-encoding") or response_headers.get("content-encoding", "identity")!="identity":
                raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
            if "attachment" in response_headers.get("content-disposition","").lower():
                raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
            maximum=4*1024*1024
            length=int(response_headers.get("content-length",maximum+1))
            if length<0 or length>maximum: raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
            data=b"" if method=="HEAD" else await asyncio.wait_for(reader.readexactly(length),5)
            response_headers={k:v for k,v in response_headers.items() if k not in {"connection","content-length","transfer-encoding","content-encoding"}}
            return status,response_headers,data
        except BrowserExecutionError: raise
        except Exception:
            raise BrowserExecutionError(BrowserErrorCode.UNREACHABLE) from None
        finally:
            writer.close()
            try: await asyncio.wait_for(writer.wait_closed(),1)
            except Exception: pass  # Transport already closed; never reused.
