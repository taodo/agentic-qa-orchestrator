"""Pinned bounded HTTP(S) transport for intercepted browser traffic. No raw persistence."""
import asyncio
from ipaddress import ip_address
import ssl
import socket
from threading import Thread, BoundedSemaphore
from urllib.parse import urlsplit, urljoin, unquote
import re
from qa_sentinel.domain.target import web_base_url
from .browser_policy import BrowserExecutionPolicy
from qa_sentinel.domain.browser_execution import BrowserErrorCode


_DNS_SLOTS=BoundedSemaphore(4)
MAX_REQUESTS=100
MAX_HEADERS=100
MAX_HEADER_BYTES=16384
MAX_BODY_BYTES=4*1024*1024
MAX_TOTAL_BODY_BYTES=32*1024*1024
MAX_REQUEST_BODY_BYTES=65536


def checked_url(url):
    # Runtime/Location data is untrusted, including encoded control/authority escapes.
    if not isinstance(url,str) or len(url)>4096 or any(ord(c)<=32 or ord(c)==127 for c in url):
        raise BrowserExecutionError(BrowserErrorCode.NETWORK)
    decoded=url
    for _ in range(3):
        if "\\" in decoded or any(ord(c)<32 or ord(c)==127 for c in decoded):
            raise BrowserExecutionError(BrowserErrorCode.NETWORK)
        next_value=unquote(decoded)
        if next_value==decoded: break
        decoded=next_value
    else:
        raise BrowserExecutionError(BrowserErrorCode.NETWORK)
    if re.search(r"%(?![0-9a-fA-F]{2})",url) or urlsplit(url).fragment:
        raise BrowserExecutionError(BrowserErrorCode.NETWORK)
    origin(url)
    return url



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
    def __init__(self,target, trusted_local_origin=None, *, redirect_limit=0, observation_only=False):
        self.observation_only=observation_only
        self.target=target
        self.authority=origin(target.base_url)
        self.local=trusted_local_origin is not None and origin(web_base_url(trusted_local_origin))==self.authority
        BrowserExecutionPolicy(allow_private_destinations=self.local).validate_target(target)
        self.pinned=None
        if type(redirect_limit) is not int or not 0<=redirect_limit<=5:
            raise BrowserExecutionError(BrowserErrorCode.REDIRECT)
        self.redirect_limit=redirect_limit
        self.redirect_count=0
        self.body_bytes=0
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

    def redirect_destination(self,url,status,location):
        # Never hand a 3xx to Chromium: its native redirect routing can skip interception.
        if status not in {301,302,303,307,308} or not location or len(location)>2048:
            raise BrowserExecutionError(BrowserErrorCode.REDIRECT)
        self.redirect_count+=1
        if self.redirect_count>self.redirect_limit:
            raise BrowserExecutionError(BrowserErrorCode.REDIRECT)
        try:
            checked_url(url)
            # Validate BEFORE urljoin, which normalizes/removes some controls.
            if "\\" in location or any(ord(c)<=32 or ord(c)==127 for c in location):
                raise ValueError()
            destination=checked_url(urljoin(url,location))
            if origin(destination)!=self.authority: raise ValueError()
        except (ValueError,BrowserExecutionError):
            raise BrowserExecutionError(BrowserErrorCode.REDIRECT) from None
        return destination

    async def fetch(self,request):
        self.request_count+=1
        if self.request_count>MAX_REQUESTS: raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
        async with self.inflight:
            try:
                async with asyncio.timeout(15):
                    return await self._fetch(request)
            except TimeoutError:
                raise BrowserExecutionError(BrowserErrorCode.UNREACHABLE) from None

    async def _fetch(self,request):
        checked_url(request.url)
        if origin(request.url)!=self.authority: raise BrowserExecutionError(BrowserErrorCode.NETWORK)
        inspection_headers=None
        if self.observation_only:
            if request.method not in {"GET","HEAD"} or (urlsplit(request.url).query and request.is_navigation_request()):
                raise BrowserExecutionError(BrowserErrorCode.NETWORK)
            inspection_headers=await request.all_headers()
            if any(k.lower() in {"authorization","cookie","proxy-authorization","x-api-key","x-auth-token"} for k in inspection_headers):
                raise BrowserExecutionError(BrowserErrorCode.NETWORK)
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
            if len(body)>MAX_REQUEST_BODY_BYTES: raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
            headers=inspection_headers if inspection_headers is not None else await request.all_headers()
            headers={k:v for k,v in headers.items() if k.lower() not in {"host","connection","content-length","accept-encoding","proxy-authorization","transfer-encoding"}}
            if len(headers)>MAX_HEADERS or sum(len(k.encode("latin-1"))+len(v.encode("latin-1"))+4 for k,v in headers.items())>MAX_HEADER_BYTES:
                raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
            authority=p.netloc
            headers.update({"host":authority,"connection":"close","accept-encoding":"identity","content-length":str(len(body))})
            if len(headers)>MAX_HEADERS: raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
            if any("\r" in k+v or "\n" in k+v for k,v in headers.items()): raise BrowserExecutionError(BrowserErrorCode.NETWORK)
            wire=f"{method} {path} HTTP/1.1\r\n"+"".join(f"{k}: {v}\r\n" for k,v in headers.items())+"\r\n"
            encoded=wire.encode("latin-1")
            if len(encoded)>MAX_HEADER_BYTES: raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
            writer.write(encoded+body);await asyncio.wait_for(writer.drain(),3)
            raw=await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"),5)
            if len(raw)>MAX_HEADER_BYTES: raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
            lines=raw.decode("latin-1").split("\r\n")
            if not re.fullmatch(r"HTTP/1\.[01] [1-5][0-9]{2}(?: [^\r\n]*)?",lines[0]):
                raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
            status=int(lines[0].split()[1])
            response_headers={}
            for line in lines[1:]:
                if line:
                    if len(response_headers)>=MAX_HEADERS or ":" not in line:
                        raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
                    key,value=line.split(":",1);key=key.lower()
                    if (not re.fullmatch(r"[!#$%&'*+.^_`|~0-9a-z-]+",key) or key in response_headers
                            or any(ord(c)<32 and c!="\t" or ord(c)==127 for c in value)):
                        raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
                    response_headers[key]=value.strip()
            if self.observation_only and "set-cookie" in response_headers:
                raise BrowserExecutionError(BrowserErrorCode.NETWORK)
            if 300<=status<400:
                if "set-cookie" in response_headers: raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
                response_headers["location"]=self.redirect_destination(request.url,status,response_headers.get("location"))
                return status,response_headers,b""
            if (status<200 or response_headers.get("transfer-encoding")
                    or response_headers.get("content-encoding","identity").lower()!="identity"):
                raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
            if "attachment" in response_headers.get("content-disposition","").lower():
                raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
            no_body=method=="HEAD" or status in {204,205}
            raw_length=response_headers.get("content-length","0" if no_body else "")
            if not re.fullmatch(r"[0-9]{1,10}",raw_length):
                raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
            length=int(raw_length)
            if length>MAX_BODY_BYTES or (not no_body and self.body_bytes+length>MAX_TOTAL_BODY_BYTES):
                raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
            if not no_body: self.body_bytes+=length  # Reserve before awaiting, including concurrent transfers.
            data=b"" if no_body else await asyncio.wait_for(reader.readexactly(length),5)
            response_headers={k:v for k,v in response_headers.items() if k not in {"connection","content-length","transfer-encoding","content-encoding"}}
            return status,response_headers,data
        except BrowserExecutionError: raise
        except (asyncio.LimitOverrunError,ValueError,UnicodeError):
            raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED) from None
        except Exception:
            raise BrowserExecutionError(BrowserErrorCode.UNREACHABLE) from None
        finally:
            writer.close()
            try: await asyncio.wait_for(writer.wait_closed(),1)
            except Exception: pass  # Transport already closed; never reused.
