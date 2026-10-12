"""Pure bounded admission. No browser, network, source tree or provider needed."""
from uuid import uuid4
import socket
import subprocess
import pytest
from pydantic import ValidationError
from qa_sentinel.domain.browser_execution import BrowserExecutionPlan, BrowserPlanEnvelope, MAX_ACTIONS
from qa_sentinel.domain.target import TargetUnderTest, TargetSnapshot
from qa_sentinel.execution.browser_policy import BrowserExecutionPolicy, BrowserPolicyError, relative_destination

LOC = {"strategy": "ROLE", "role": "button", "name": "Continue"}
ACTIONS = [
    {"action": "NAVIGATE", "path": "/courses"},
    {"action": "CLICK", "locator": LOC},
    {"action": "FILL", "locator": {"strategy": "LABEL", "value": "Email"}, "value": "qa@example.com"},
    {"action": "SELECT", "locator": LOC, "value": "standard"},
    {"action": "CHECK", "locator": LOC, "checked": True},
    {"action": "PRESS", "locator": LOC, "key": "Enter"},
    {"action": "WAIT_FOR", "locator": LOC, "condition": "VISIBLE"},
    {"action": "ASSERT_TEXT", "locator": LOC, "text": "Available"},
    {"action": "ASSERT_VISIBLE", "locator": LOC},
    {"action": "ASSERT_URL", "path": "/courses"},
]


def target(url="https://example.com/app"):
    return TargetSnapshot.capture(TargetUnderTest(project_id=uuid4(), name="WEB", environment="STAGING", configuration={"base_url": url}))


def plan(step=None, **kwargs):
    return BrowserExecutionPlan(steps=(step or ACTIONS[0],), **kwargs)


def test_all_actions_strict_discriminated_and_frozen():
    accepted = BrowserExecutionPlan(steps=tuple(ACTIONS))
    assert BrowserExecutionPolicy().validate(accepted, target()) == accepted
    schema = BrowserExecutionPlan.model_json_schema()
    assert len(schema["properties"]["steps"]["items"]["discriminator"]["mapping"]) == 10
    with pytest.raises(ValidationError): accepted.test_timeout_ms = 1
    for step in ACTIONS:
        with pytest.raises(ValidationError): plan({**step, "script": "alert(1)"})


@pytest.mark.parametrize("action", ["EVALUATE", "JAVASCRIPT", "SHELL", "PROCESS", "READ_FILE", "WRITE_FILE", "DOWNLOAD", "SCREENSHOT", "sleep", "UNKNOWN"])
def test_unrepresentable_capabilities(action):
    with pytest.raises(ValidationError): plan({"action": action})


@pytest.mark.parametrize("extra", [{"version": "v2"}, {"browser_args": ["--no-sandbox"]}, {"steps": []}, {"steps": [ACTIONS[0]] * (MAX_ACTIONS+1)}, {"executor_kind": "SYNTHETIC"}, {"workspace_root": "C:/target"}, {"allow_private_destinations": True}])
def test_plan_closed_version_fields_and_step_bounds(extra):
    with pytest.raises(ValidationError): BrowserExecutionPlan.model_validate({"steps": [ACTIONS[0]], **extra})


@pytest.mark.parametrize("strategy", ["LABEL", "TEXT", "TEST_ID", "PLACEHOLDER", "CSS"])
def test_locator_strategies_bounds_and_no_expressions(strategy):
    locator = {"strategy": strategy, "value": "submit"}
    BrowserExecutionPolicy().validate(plan({"action": "CLICK", "locator": locator}), target())
    for value in ["", "x"*513, 123]:
        with pytest.raises(ValidationError): plan({"action": "CLICK", "locator": {**locator, "value": value}})
    with pytest.raises(ValidationError): plan({"action": "CLICK", "locator": {**locator, "evaluate": "code"}})


@pytest.mark.parametrize("locator", [{"strategy":"XPATH","value":"//button"}, {"strategy":"ROLE","role":"arbitrary"}, {"strategy":"ROLE","role":"button","name":"x"*513}, {"strategy":"CSS","value":"div >> xpath=//button"}, {"strategy":"CSS","value":"xpath=//button"}])
def test_unsupported_locator(locator):
    with pytest.raises(ValidationError): plan({"action": "CLICK", "locator": locator})


@pytest.mark.parametrize("change", [{"timeout_ms": 0}, {"timeout_ms": 30_001}, {"timeout_ms": True}, {"timeout_ms": "1000"}])
def test_action_timeout_bounds(change):
    with pytest.raises(ValidationError): plan({**ACTIONS[0], **change})


@pytest.mark.parametrize("change", [{"test_timeout_ms": 999}, {"test_timeout_ms": 120_001}, {"redirect_limit": 6}, {"redirect_limit": -1}, {"evidence_limit": 21}, {"screenshot_limit": 4}, {"screenshot_max_bytes": 2*1024*1024+1}])
def test_resource_bounds(change):
    with pytest.raises(ValidationError): plan(**change)


def test_timeout_cannot_exceed_test_budget_and_wait_is_condition_only():
    with pytest.raises(BrowserPolicyError, match="BROWSER_TIMEOUT_REJECTED"):
        BrowserExecutionPolicy().validate(plan(test_timeout_ms=1000), target())
    for fields in [{"condition":"SLEEP"}, {"sleep_ms":1}, {"condition":"VISIBLE","duration_ms":1}]:
        with pytest.raises(ValidationError): plan({"action":"WAIT_FOR","locator":LOC,**fields})


@pytest.mark.parametrize("action,field", [("FILL","value"),("ASSERT_TEXT","text"),("SELECT","value")])
def test_text_and_input_bounds(action, field):
    with pytest.raises(ValidationError): plan({"action":action,"locator":LOC,field:"x"*4001})


@pytest.mark.parametrize("path", ["https://evil.example/path", "//evil.example/path", "file:///tmp/a", "javascript:alert(1)", "data:text/plain,x", "C:/file", "/\\evil.example", "/%2f%2fevil.example", "/%5cevil.example", "/%0aevil", "/bad%ZZ", "/bad path", "/"+"x"*2048])
@pytest.mark.parametrize("action", ["NAVIGATE", "ASSERT_URL"])
def test_navigation_cannot_replace_authority(path, action):
    with pytest.raises((ValidationError, BrowserPolicyError)):
        BrowserExecutionPolicy().validate(plan({"action":action,"path":path}), target())


def test_relative_navigation_keeps_snapshot_origin_without_network(monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError("Side effect forbidden")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    saved = target()
    approved = BrowserExecutionPolicy().validate(plan(), saved)
    assert relative_destination(saved.base_url, approved.steps[0].path) == "https://example.com/courses"
    assert relative_destination(saved.base_url,"/courses?q=1#list") == "https://example.com/courses?q=1#list"


@pytest.mark.parametrize("url", ["http://localhost:3000", "http://127.0.0.1", "http://10.1.2.3", "http://169.254.169.254", "http://[::1]", "http://[::ffff:127.0.0.1]", "http://host.internal", "http://host.local", "http://intranet", "http://2130706433", "http://127.1", "http://224.0.0.1", "http://[ff02::1]", "http://[fec0::1]", "http://home.arpa"])
def test_private_target_requires_trusted_policy(url):
    saved = target(url)
    with pytest.raises(BrowserPolicyError,match="BROWSER_TARGET_REJECTED"):
        BrowserExecutionPolicy().validate(plan(), saved)
    assert BrowserExecutionPolicy(allow_private_destinations=True).validate(plan(), saved)


def test_forged_frozen_plan_is_revalidated():
    forged = plan().model_copy(update={"steps": plan().steps*51})
    with pytest.raises(ValidationError): BrowserExecutionPolicy().validate(forged,target())
