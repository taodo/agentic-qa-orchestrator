"""Pure static admission; never DNS, HTTP, browser, filesystem or execution."""
from hashlib import sha256
from ipaddress import ip_address
from urllib.parse import urlsplit, urlunsplit, unquote
import re
from qa_sentinel.domain.browser_execution import BrowserExecutionPlan, BrowserPlanEnvelope
from qa_sentinel.domain.campaign_content import Frozen
from qa_sentinel.domain.qa_run import QARun, QARunTest, canonical_json
from qa_sentinel.domain.target import TargetSnapshot
from pydantic import Field


class BrowserPolicyError(ValueError):
    """Fixed safe error code, never untrusted input or raw internal exception."""


def digest(value):
    return sha256(canonical_json(value.model_dump(mode="json"))).hexdigest()


def run_test_snapshot_digest(test):
    # Progress/outcome change; approved immutable content, links and receipt do not.
    return sha256(canonical_json(test.model_dump(mode="json", exclude={"execution_status", "qa_result", "browser_plan"}))).hexdigest()


def relative_destination(base_url, path):
    decoded = path
    for _ in range(3):
        if (not decoded.startswith("/") or decoded.startswith("//") or "\\" in decoded
                or any(ord(c) <= 32 or ord(c) == 127 for c in decoded)):
            raise BrowserPolicyError("BROWSER_NAVIGATION_REJECTED")
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    else:
        raise BrowserPolicyError("BROWSER_NAVIGATION_REJECTED")
    if re.search(r"%(?![0-9a-fA-F]{2})", path):
        raise BrowserPolicyError("BROWSER_NAVIGATION_REJECTED")
    base = urlsplit(base_url)
    # Origin-root-relative, never urljoin authority replacement.
    return urlunsplit((base.scheme, base.netloc, path, "", ""))


class BrowserExecutionPolicy(Frozen):
    # Trusted host construction only; not a plan field or public request option.
    allow_private_destinations: bool = Field(default=False, strict=True)

    def validate_target(self, target):
        target = TargetSnapshot.model_validate(target.model_dump())
        host = urlsplit(target.base_url).hostname.rstrip(".").lower()
        if self.allow_private_destinations:
            return target
        try:
            address = ip_address(host)
        except ValueError:
            if ("." not in host or host in {"localhost", "home.arpa"} or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa"))
                    or re.fullmatch(r"[0-9.]+", host) or host.startswith("0x")):
                raise BrowserPolicyError("BROWSER_TARGET_REJECTED") from None
        else:
            mapped = getattr(address, "ipv4_mapped", None)
            if (not address.is_global or address.is_multicast or getattr(address, "is_site_local", False)
                    or (mapped is not None and (not mapped.is_global or mapped.is_multicast))):
                raise BrowserPolicyError("BROWSER_TARGET_REJECTED")
        return target

    def validate(self, plan, target):
        # Revalidation also rejects forged frozen model_copy values.
        plan = BrowserExecutionPlan.model_validate(plan.model_dump())
        target = self.validate_target(target)
        for step in plan.steps:
            if step.action in {"NAVIGATE", "ASSERT_URL", "ASSERT_PAGE_LOAD"}:
                relative_destination(target.base_url, step.path)
            if step.timeout_ms > plan.test_timeout_ms:
                raise BrowserPolicyError("BROWSER_TIMEOUT_REJECTED")
        return plan

    def validate_envelope(self, envelope, run, test):
        envelope = BrowserPlanEnvelope.model_validate(envelope.model_dump())
        run = QARun.model_validate(run.model_dump())
        test = QARunTest.model_validate({**test.model_dump(), "snapshot_version": run.snapshot_version})
        target = run.target_snapshot
        if (target is None or test.run_id != run.id or
                (test.content.project_id, test.content.campaign_id) != (run.project_id, run.campaign_id) or
                (envelope.project_id, envelope.campaign_id, envelope.run_id, envelope.run_test_id) !=
                (run.project_id, run.campaign_id, run.id, test.id) or
                envelope.test_snapshot_hash != run_test_snapshot_digest(test) or
                envelope.target_snapshot_hash != digest(target) or envelope.plan_hash != digest(envelope.plan)):
            raise BrowserPolicyError("BROWSER_PROVENANCE_REJECTED")
        self.validate(envelope.plan, target)
        return envelope
