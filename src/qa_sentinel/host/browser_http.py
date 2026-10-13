"""Loopback/same-origin browser controls; no request-selectable execution policy."""
from ipaddress import ip_address
from qa_sentinel.api.errors import error_response
from qa_sentinel.api.browser import local_router

class LocalBrowserAccess:
    def __init__(self,app,*,host,port):
        self.app=app
        self.authority=f'[{host}]:{port}' if ':' in host else f'{host}:{port}'
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or '/browser/' not in scope['path']:
            return await self.app(scope,receive,send)
        headers=scope['headers']
        hosts=[v.decode('latin-1') for k,v in headers if k.lower()==b'host']
        origins=[v.decode('latin-1') for k,v in headers if k.lower()==b'origin']
        try:peer=ip_address(scope['client'][0]).is_loopback
        except (ValueError,TypeError,IndexError):peer=False
        unsafe=scope['method'] not in {'GET','HEAD'}
        if (not peer or hosts!=[self.authority] or (origins and origins!=['http://'+self.authority])
                or (unsafe and origins!=['http://'+self.authority])):
            return await error_response(403,'HOST_LOCAL_ACCESS_REQUIRED','Trusted local same-origin access required')(scope,receive,send)
        return await self.app(scope,receive,send)

def add_browser_http(app,config):
    app.state.browser_project_keys=tuple(p.key for p in config.projects)
    app.include_router(local_router,prefix='/api/v1')
    app.add_middleware(LocalBrowserAccess,host=config.host,port=config.port)
