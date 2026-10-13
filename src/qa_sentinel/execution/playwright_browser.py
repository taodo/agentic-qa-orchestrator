"""Chromium-only allowlisted adapter. No generated code, arbitrary JS or user launch options."""
import asyncio
import os
from importlib.metadata import version, PackageNotFoundError
from importlib.resources import files
import json
from ipaddress import ip_address
from urllib.parse import urlsplit
from qa_sentinel.domain.browser_execution import BrowserRuntimeIdentity, BrowserErrorCode
from qa_sentinel.domain.qa_run_evidence import EvidenceDraft, TestExecutionResult
from qa_sentinel.domain.evidence_variants import BrowserObservation
from .browser_policy import BrowserExecutionPolicy, relative_destination
from .browser_network import PinnedNetwork, BrowserExecutionError, origin

# Internal fixed safety settings, never selected by plan/operator input.
SECURITY_ARGS=("--proxy-bypass-list=<-loopback>","--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
               "--force-webrtc-ip-handling-policy=disable_non_proxied_udp")


class PlaywrightBrowserExecutor:
    def __init__(self, *, trusted_local_origin=None):
        if trusted_local_origin is not None:
            try:
                if not ip_address(origin(trusted_local_origin)[1]).is_loopback: raise ValueError()
            except ValueError: raise BrowserExecutionError(BrowserErrorCode.NETWORK) from None
        self.trusted_local_origin=trusted_local_origin
        try:
            package_version=version("playwright")
            manifest=json.loads(files("playwright").joinpath("driver/package/browsers.json").read_text(encoding="utf-8"))
            chromium=next(b for b in manifest["browsers"] if b["name"]=="chromium")
            self.identity=BrowserRuntimeIdentity(playwright_version=package_version,chromium_revision=chromium["revision"],browser_version=chromium["browserVersion"])
        except (PackageNotFoundError,ImportError,ValueError,KeyError,StopIteration):
            raise BrowserExecutionError(BrowserErrorCode.UNAVAILABLE) from None

    def policy_for(self,target):
        local=self.trusted_local_origin is not None and origin(self.trusted_local_origin)==origin(target.base_url)
        return BrowserExecutionPolicy(allow_private_destinations=local)

    def execute(self,envelope,run,test):
        try:
            self.policy_for(run.target_snapshot).validate_envelope(envelope,run,test)
            if (run.executor_kind!="WEB_BROWSER" or run.runtime_identity!=self.identity or test.browser_plan!=envelope):
                raise ValueError()
            captures=sum(step.action in {"NAVIGATE","ASSERT_TEXT","ASSERT_VISIBLE","ASSERT_URL"} for step in envelope.plan.steps)
            if (envelope.plan.screenshot_limit or not captures or captures>envelope.plan.evidence_limit or envelope.plan.steps[0].action!="NAVIGATE"):
                raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
            if any(key in os.environ for key in ("PLAYWRIGHT_NODEJS_PATH","PLAYWRIGHT_BROWSERS_PATH","NODE_OPTIONS","PWDEBUG","DEBUG")):
                raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
        except BrowserExecutionError: raise
        except Exception: raise BrowserExecutionError(BrowserErrorCode.PLAN) from None
        return asyncio.run(self._run(envelope,run))

    @staticmethod
    def locator(page,intent):
        if intent.strategy=="ROLE": return page.get_by_role(intent.role,name=intent.name,exact=intent.exact)
        if intent.strategy=="LABEL": return page.get_by_label(intent.value,exact=intent.exact)
        if intent.strategy=="TEXT": return page.get_by_text(intent.value,exact=intent.exact)
        if intent.strategy=="TEST_ID": return page.get_by_test_id(intent.value)
        if intent.strategy=="PLACEHOLDER": return page.get_by_placeholder(intent.value,exact=intent.exact)
        if intent.strategy=="CSS": return page.locator("css="+intent.value)
        raise BrowserExecutionError(BrowserErrorCode.PLAN)

    async def _run(self,envelope,run):
        from playwright.async_api import async_playwright, Error, TimeoutError as PWTimeout
        driver=browser=context=proxy=None
        blocked=[];observations=[];outcome="PASS"
        def record(code):
            if not blocked: blocked.append(code)
        async def deny(reader,writer):
            # Chromium never receives permission for direct egress or CONNECT tunnels.
            record(BrowserErrorCode.NETWORK)
            writer.close()
        try:
            async with asyncio.timeout(envelope.plan.test_timeout_ms/1000):
                network=PinnedNetwork(run.target_snapshot,self.trusted_local_origin)
                await network.addresses()
                proxy=await asyncio.start_server(deny,"127.0.0.1",0)
                proxy_url=f"http://127.0.0.1:{proxy.sockets[0].getsockname()[1]}"
                driver=await async_playwright().start()
                safe_env={k:v for k,v in os.environ.items() if k.upper() in {"SYSTEMROOT","WINDIR","SYSTEMDRIVE","TEMP","TMP","PATH","PATHEXT"}}
                try:
                    browser=await driver.chromium.launch(headless=True,args=list(SECURITY_ARGS),proxy={"server":proxy_url,"bypass":""},env=safe_env,timeout=min(envelope.plan.test_timeout_ms,10000))
                    if browser.version!=self.identity.browser_version: raise BrowserExecutionError(BrowserErrorCode.INTERNAL)
                    context=await browser.new_context(service_workers="block",accept_downloads=False,
                        proxy={"server":proxy_url,"bypass":""})
                    page=await context.new_page()
                except BrowserExecutionError: raise
                except Error: raise BrowserExecutionError(BrowserErrorCode.LAUNCH) from None
                async def handle(route):
                    try:
                        try: controlled = route.request.frame == page.main_frame
                        except Exception: raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED) from None
                        if not controlled:
                            raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
                        status,headers,body=await network.fetch(route.request)
                        await route.fulfill(status=status,headers=headers,body=body)
                    except BrowserExecutionError as error:
                        record(error.code);await route.abort()
                    except Exception:
                        record(BrowserErrorCode.INTERNAL);await route.abort()
                await context.route("**/*",handle)
                async def websocket(ws):
                    record(BrowserErrorCode.UNSUPPORTED);await ws.close()
                await context.route_web_socket("**/*",websocket)
                def popup(extra):
                    if extra!=page: record(BrowserErrorCode.UNSUPPORTED)
                context.on("page",popup)
                page.on("download",lambda _:record(BrowserErrorCode.UNSUPPORTED))
                page.on("worker",lambda _:record(BrowserErrorCode.UNSUPPORTED))
                page.on("frameattached",lambda _:record(BrowserErrorCode.UNSUPPORTED))
                def navigation(frame):
                    if frame.url!="about:blank":
                        try:
                            if origin(frame.url)!=network.authority: record(BrowserErrorCode.NETWORK)
                        except BrowserExecutionError: record(BrowserErrorCode.NETWORK)
                page.on("framenavigated",navigation)
                page.on("crash",lambda _:record(BrowserErrorCode.CRASH))
                for number,step in enumerate(envelope.plan.steps,1):
                    matched=True
                    assertion_observation=step.action in {"ASSERT_TEXT","ASSERT_VISIBLE","ASSERT_URL"}
                    try:
                        async with asyncio.timeout(step.timeout_ms/1000):
                            action=step.action
                            loc=self.locator(page,step.locator) if hasattr(step,"locator") else None
                            if action=="NAVIGATE":
                                await page.goto(relative_destination(run.target_snapshot.base_url,step.path),wait_until="load",timeout=step.timeout_ms)
                            elif action=="CLICK":
                                href=await loc.get_attribute("href",timeout=step.timeout_ms)
                                if href and urlsplit(href).scheme and urlsplit(href).scheme not in {"http","https"}:
                                    raise BrowserExecutionError(BrowserErrorCode.NETWORK)
                                await loc.click(timeout=step.timeout_ms)
                            elif action=="FILL":
                                if await loc.get_attribute("type",timeout=step.timeout_ms)=="password":
                                    raise BrowserExecutionError(BrowserErrorCode.UNSUPPORTED)
                                await loc.fill(step.value,timeout=step.timeout_ms)
                            elif action=="SELECT": await loc.select_option(step.value,timeout=step.timeout_ms)
                            elif action=="CHECK": await loc.set_checked(step.checked,timeout=step.timeout_ms)
                            elif action=="PRESS": await loc.press(step.key,timeout=step.timeout_ms)
                            elif action=="WAIT_FOR": await loc.wait_for(state=step.condition.lower(),timeout=step.timeout_ms)
                            elif action=="ASSERT_TEXT":
                                await loc.wait_for(state="attached",timeout=step.timeout_ms)
                                actual=await loc.inner_text(timeout=step.timeout_ms)
                                matched=actual==step.text if step.exact else step.text in actual
                            elif action=="ASSERT_VISIBLE": matched=await loc.is_visible()==step.visible
                            elif action=="ASSERT_URL": matched=page.url==relative_destination(run.target_snapshot.base_url,step.path)
                            else: raise BrowserExecutionError(BrowserErrorCode.PLAN)
                            assertion_observation=False
                            await page.title()  # Protocol transport failure is infrastructure, not assertion mismatch.
                    except (PWTimeout,TimeoutError):
                        if assertion_observation: matched=False
                        else: raise BrowserExecutionError(BrowserErrorCode.ACTION_TIMEOUT) from None
                    except Error:
                        raise BrowserExecutionError(blocked[0] if blocked else BrowserErrorCode.CRASH if not browser.is_connected() else BrowserErrorCode.UNREACHABLE) from None
                    if blocked: raise BrowserExecutionError(blocked[0])
                    if step.action in {"NAVIGATE","ASSERT_TEXT","ASSERT_VISIBLE","ASSERT_URL"}:
                        observations.append((number,step.action,matched))
                    if not matched:
                        outcome="FAIL";break
                if blocked: raise BrowserExecutionError(blocked[0])
        except BrowserExecutionError: raise
        except TimeoutError: raise BrowserExecutionError(BrowserErrorCode.TIMEOUT) from None
        except Exception: raise BrowserExecutionError(BrowserErrorCode.INTERNAL) from None
        finally:
            cleanup_failed=False
            # A stalled context must not consume the browser/driver cleanup opportunity.
            for resource,deadline in ((context,1),(browser,2),(driver,2)):
                if resource is not None:
                    try:
                        async with asyncio.timeout(deadline):
                            await (resource.stop() if resource is driver else resource.close())
                    except Exception: cleanup_failed=True
            if proxy:
                proxy.close()
                try:
                    async with asyncio.timeout(1): await proxy.wait_closed()
                except Exception: cleanup_failed=True
            if proxy: proxy.close()
            if cleanup_failed: raise BrowserExecutionError(BrowserErrorCode.CLEANUP) from None
        evidence=[]
        for number,action,matched in observations:
            observation=BrowserObservation(category="NAVIGATION" if action=="NAVIGATE" else "ASSERTION",run_test_id=envelope.run_test_id,
                plan_hash=envelope.plan_hash,step_number=number,action=action,matched=matched,outcome=outcome,browser_version=self.identity.browser_version)
            evidence.append(EvidenceDraft(source="web-browser",payload=observation,summary=observation.safe_summary()))
        return TestExecutionResult(executor_kind="WEB_BROWSER",qa_result=outcome,evidence=tuple(evidence))
