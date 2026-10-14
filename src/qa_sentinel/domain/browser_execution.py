"""Inert browser intents, independent of Playwright and source repositories."""
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID
from pydantic import Field, StringConstraints, field_validator
from .campaign_content import Frozen, Hash
from .executor import ExecutorKind

PLAN_VERSION = "browser-execution-plan-v1"
MAX_ACTIONS = 50
MAX_TEXT = 4000
MAX_LOCATOR = 512
MAX_REDIRECTS = 5
MAX_SCREENSHOTS = 3
MAX_SCREENSHOT_BYTES = 2 * 1024 * 1024
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=MAX_TEXT)]
LocatorValue = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=MAX_LOCATOR)]
ActionTimeout = Annotated[int, Field(strict=True, ge=100, le=30_000)]
RelativeURL = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2048)]


class RoleLocator(Frozen):
    strategy: Literal["ROLE"]
    role: Literal["button", "link", "textbox", "checkbox", "radio", "combobox", "option", "heading", "listitem", "dialog", "navigation", "tab"]
    name: LocatorValue | None = None
    exact: bool = Field(default=True, strict=True)


class LabelLocator(Frozen):
    strategy: Literal["LABEL"]
    value: LocatorValue
    exact: bool = Field(default=True, strict=True)


class TextLocator(Frozen):
    strategy: Literal["TEXT"]
    value: LocatorValue
    exact: bool = Field(default=True, strict=True)


class TestIdLocator(Frozen):
    strategy: Literal["TEST_ID"]
    value: LocatorValue


class PlaceholderLocator(Frozen):
    strategy: Literal["PLACEHOLDER"]
    value: LocatorValue
    exact: bool = Field(default=True, strict=True)


class CSSLocator(Frozen):
    strategy: Literal["CSS"]
    value: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]

    @field_validator("value")
    @classmethod
    def one_css_engine(cls, value):
        if ">>" in value or any(ord(c) < 32 for c in value) or value.startswith(("xpath=", "javascript=", "text=")):
            raise ValueError("Unsupported CSS locator")
        return value


Locator = Annotated[RoleLocator | LabelLocator | TextLocator | TestIdLocator | PlaceholderLocator | CSSLocator, Field(discriminator="strategy")]


class Action(Frozen):
    timeout_ms: ActionTimeout = 5000


class Navigate(Action):
    action: Literal["NAVIGATE"]
    path: RelativeURL


class Click(Action):
    action: Literal["CLICK"]
    locator: Locator


class Fill(Action):
    action: Literal["FILL"]
    locator: Locator
    value: Annotated[str, StringConstraints(strict=True, max_length=MAX_TEXT)]


class Select(Action):
    action: Literal["SELECT"]
    locator: Locator
    value: LocatorValue


class Check(Action):
    action: Literal["CHECK"]
    locator: Locator
    checked: bool = Field(default=True, strict=True)


class Press(Action):
    action: Literal["PRESS"]
    locator: Locator
    key: Literal["Enter", "Tab", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space", "Backspace", "Delete"]


class WaitFor(Action):
    action: Literal["WAIT_FOR"]
    locator: Locator
    condition: Literal["VISIBLE", "HIDDEN", "ATTACHED", "DETACHED"]


class AssertText(Action):
    action: Literal["ASSERT_TEXT"]
    locator: Locator
    text: Text
    exact: bool = Field(default=True, strict=True)


class AssertVisible(Action):
    action: Literal["ASSERT_VISIBLE"]
    locator: Locator
    visible: bool = Field(default=True, strict=True)


class AssertURL(Action):
    action: Literal["ASSERT_URL"]
    path: RelativeURL


class AssertPageLoad(Action):
    """Load event completed at the sealed destination with a 2xx main response."""
    action: Literal["ASSERT_PAGE_LOAD"]
    path: RelativeURL


BrowserAction = Annotated[AssertPageLoad | Navigate | Click | Fill | Select | Check | Press | WaitFor | AssertText | AssertVisible | AssertURL, Field(discriminator="action")]


class BrowserExecutionPlan(Frozen):
    version: Literal["browser-execution-plan-v1"] = PLAN_VERSION
    steps: tuple[BrowserAction, ...] = Field(min_length=1, max_length=MAX_ACTIONS)
    test_timeout_ms: int = Field(default=60_000, strict=True, ge=1000, le=120_000)
    redirect_limit: int = Field(default=3, strict=True, ge=0, le=MAX_REDIRECTS)
    evidence_limit: int = Field(default=20, strict=True, ge=1, le=20)
    screenshot_limit: int = Field(default=0, strict=True, ge=0, le=MAX_SCREENSHOTS)
    screenshot_max_bytes: int = Field(default=MAX_SCREENSHOT_BYTES, strict=True, ge=1, le=MAX_SCREENSHOT_BYTES)


class PlanOrigin(StrEnum):
    MANUAL = "MANUAL"
    DETERMINISTIC = "DETERMINISTIC"
    AI = "AI"  # Provenance label only: no planner/provider implemented.


class BrowserPlanEnvelope(Frozen):
    """Candidate provenance, not an approval receipt or persisted execution claim."""
    executor_kind: Literal[ExecutorKind.WEB_BROWSER] = ExecutorKind.WEB_BROWSER
    project_id: UUID
    campaign_id: UUID
    run_id: UUID
    run_test_id: UUID
    origin: PlanOrigin
    test_snapshot_hash: Hash
    target_snapshot_hash: Hash
    plan_hash: Hash
    plan: BrowserExecutionPlan


class BrowserErrorCode(StrEnum):
    UNAVAILABLE = "BROWSER_RUNTIME_UNAVAILABLE"
    LAUNCH = "BROWSER_LAUNCH_FAILED"
    CRASH = "BROWSER_CRASHED"
    NETWORK = "BROWSER_NETWORK_DENIED"
    DNS = "BROWSER_DNS_FAILED"
    TLS = "BROWSER_TLS_FAILED"
    UNREACHABLE = "BROWSER_TARGET_UNREACHABLE"
    TIMEOUT = "BROWSER_TEST_TIMEOUT"
    ACTION_TIMEOUT = "BROWSER_ACTION_TIMEOUT"
    CLEANUP = "BROWSER_CLEANUP_FAILED"
    INTERNAL = "BROWSER_INTERNAL_ERROR"
    PLAN = "BROWSER_PLAN_REJECTED"
    REDIRECT = "BROWSER_REDIRECT_DENIED"
    UNSUPPORTED = "BROWSER_UNSUPPORTED_FEATURE"


class BrowserRuntimeIdentity(Frozen):
    adapter_version: Literal["playwright-chromium-v1"] = "playwright-chromium-v1"
    engine: Literal["CHROMIUM"] = "CHROMIUM"
    playwright_version: Annotated[str, StringConstraints(strict=True, max_length=32, pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    chromium_revision: Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9]{1,12}$")]
    browser_version: Annotated[str, StringConstraints(strict=True, max_length=64, pattern=r"^[0-9]+(\.[0-9]+){3}$")]
