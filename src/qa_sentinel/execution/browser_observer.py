"""Fixed semantic inspection through the accepted pinned Chromium session."""
import asyncio
import os
from uuid import uuid4
from urllib.parse import urlsplit, urljoin
from qa_sentinel.domain.browser_grounding import (GroundingScope, ObservationLimits, ObservedElement,
    ObservedPath, BrowserGroundingObservation, GroundingLimitation, secret_looking, safe_path, now, digest)
from qa_sentinel.domain.browser_execution import RoleLocator, LabelLocator, PlaceholderLocator, BrowserErrorCode
from .playwright_browser import PlaywrightBrowserExecutor
from .browser_network import origin, BrowserExecutionError, checked_url

# Fixed tooling queries; never supplied by a model, Test, operator request, or stored plan.
GROUPS=(("h1,h2,h3,h4,h5,h6", "heading"), ("button,[role=button]", "button"),
    ("a[href],[role=link]", "link"),
    ('input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=submit]):not([role=combobox]),textarea',"textbox"),
    ('input[type=checkbox],[role=checkbox]',"checkbox"), ('select,[role=combobox]',"combobox"))


def bounded(text, maximum):
    if len(text)>maximum:raise GroundingLimitation("OBSERVATION_LIMIT")
    if secret_looking(text):raise GroundingLimitation("UNSUPPORTED_BEHAVIOR")
    return text


class PlaywrightBrowserObserver:
    def __init__(self, *, trusted_local_origin=None):
        self.runtime=PlaywrightBrowserExecutor(trusted_local_origin=trusted_local_origin)

    def policy_for(self,target):return self.runtime.policy_for(target)

    def observe(self,scope):
        scope=GroundingScope.model_validate(scope.model_dump())
        if scope.policy!=self.policy_for(scope.target):raise GroundingLimitation("POLICY_REJECTED")
        scope.policy.validate_target(scope.target)
        if any(key in os.environ for key in ("PLAYWRIGHT_NODEJS_PATH","PLAYWRIGHT_BROWSERS_PATH","NODE_OPTIONS","PWDEBUG","DEBUG")):
            raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
        return asyncio.run(self.runtime._secured_session(scope.target,scope.limits,observation_context=scope))


async def collect_page(page,navigate,target,scope,identity):
    started=now()
    await navigate(target.base_url,10000)
    checked_url(page.url)
    if origin(page.url)!=origin(target.base_url):raise GroundingLimitation("POLICY_REJECTED")
    current=urlsplit(page.url)
    if current.query or current.fragment:raise GroundingLimitation("POLICY_REJECTED")
    title=bounded(await page.title(),512)
    paths=[];elements=[]
    def path_ref(path,source,element_ref=None):
        safe_path(path,target)
        old=next((p for p in paths if p.path==path),None)
        if old is not None:return old.ref
        if len(paths)>=scope.limits.max_paths:raise GroundingLimitation("OBSERVATION_LIMIT")
        ref="p"+str(len(paths)+1);paths.append(ObservedPath(ref=ref,path=path,source=source,element_ref=element_ref));return ref
    path_ref(urlsplit(target.base_url).path or "/","TARGET_BASE")
    current_ref=path_ref(current.path or "/","CURRENT_PAGE")
    scanned=0
    for selector,role in GROUPS:
        nodes=page.locator(selector);count=await nodes.count();scanned+=count
        if scanned>scope.limits.max_elements:raise GroundingLimitation("OBSERVATION_LIMIT")
        for index in range(count):
            node=nodes.nth(index)
            if not await node.is_visible():continue
            ref="e"+str(len(elements)+1)
            declared=await node.get_attribute("role",timeout=1000)
            # Unsupported explicit semantics are not guessed from visual appearance.
            if declared and declared!=role:raise GroundingLimitation("UNSUPPORTED_BEHAVIOR")
            input_type=await node.get_attribute("type",timeout=1000) or ""
            if role=="textbox" and input_type.lower() not in {"","text","email","search","tel","url","password"}:
                raise GroundingLimitation("UNSUPPORTED_BEHAVIOR")
            if input_type.lower()=="file":raise GroundingLimitation("UNSUPPORTED_BEHAVIOR")
            autocomplete=await node.get_attribute("autocomplete",timeout=1000) or ""
            label=await node.get_attribute("aria-label",timeout=1000)
            sensitive=input_type.lower()=="password" or autocomplete.lower() in {"current-password","new-password","one-time-code"} or bool(label and secret_looking(label))
            text="";name=None;locator=None;matches=0;destination=None;blocked=False
            if not sensitive:
                if role in {"heading","button","link"}:
                    text=bounded(await node.inner_text(timeout=1000),512)
                    name=bounded(" ".join((label or text).split()),256) or None
                    if name is not None:locator=RoleLocator(strategy="ROLE",role=role,name=name,exact=True)
                else:
                    placeholder=await node.get_attribute("placeholder",timeout=1000)
                    if label:
                        name=bounded(" ".join(label.split()),256);locator=LabelLocator(strategy="LABEL",value=name,exact=True)
                    elif placeholder and role=="textbox":
                        name=bounded(placeholder,256);locator=PlaceholderLocator(strategy="PLACEHOLDER",value=name,exact=True)
                if locator is not None:
                    matches=await PlaywrightBrowserExecutor.locator(page,locator).count()
                    if matches>scope.limits.max_elements:raise GroundingLimitation("OBSERVATION_LIMIT")
                if role=="link":
                    href=await node.get_attribute("href",timeout=1000)
                    try:
                        if not href or len(href)>2048:raise GroundingLimitation("POLICY_REJECTED")
                        resolved=checked_url(urljoin(page.url,href));parsed=urlsplit(resolved)
                        if origin(resolved)!=origin(target.base_url) or parsed.query or parsed.fragment:raise GroundingLimitation("POLICY_REJECTED")
                        destination=path_ref(parsed.path or "/","LINK",ref)
                    except GroundingLimitation as failure:
                        if failure.reason != "POLICY_REJECTED":raise
                        blocked=True
                    except (ValueError,BrowserExecutionError):blocked=True
            elements.append(ObservedElement(ref=ref,role=role,name=name,text=text,enabled=await node.is_enabled(),
                sensitive=sensitive,blocked_destination=blocked,locator=locator,matches=matches,path_ref=destination))
            if len(title)+sum(len(e.name or "")+len(e.text) for e in elements)+sum(len(p.path) for p in paths)>scope.limits.max_text_chars:
                raise GroundingLimitation("OBSERVATION_LIMIT")
    payload=dict(id=uuid4(),contract_version="browser-grounding-observation-v1",scope=scope,
        runtime_identity=identity,started_at=started,finished_at=now(),current_path_ref=current_ref,title=title,elements=tuple(elements),paths=tuple(paths))
    # Hash the actual structured capture; never claim truncated facts were observed.
    from pydantic import TypeAdapter
    encoded=TypeAdapter(dict).dump_python(payload,mode="json")
    try:return BrowserGroundingObservation(**payload,observation_hash=digest(encoded))
    except ValueError:raise GroundingLimitation("OBSERVATION_LIMIT") from None
