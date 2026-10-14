"""Closed reviewed evidence variants and their validation/presentation policies.

Safety limits and protocol identities are not operator-configurable. Adding a
variant requires a reviewed typed payload, policy and entry in this module.
"""
from types import MappingProxyType
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .campaign_content import Frozen, Hash
from uuid import UUID
from .executor import ExecutorKind
from .qa_run import QAResult, QARunTest, MAX_SNAPSHOT_RECORDS

MAX_TEST_EVIDENCE = 20
EVIDENCE_PREVIEW_LIMIT = 5
MAX_EVIDENCE_BYTES = 2048
MAX_EVIDENCE_SUMMARY_CHARS = 512
MAX_EVIDENCE_DETAILS = 8
MAX_DETAIL_LABEL_CHARS = 64
MAX_DETAIL_VALUE_CHARS = 512
MAX_EVIDENCE_IDENTITY_CHARS = 64
EVIDENCE_SCHEMA_VERSION = "qa-run-evidence-v1"
OBSERVATION_KIND = "EXECUTION_OBSERVATION"


class EvidenceDetail(Frozen):
    label: str = Field(min_length=1, max_length=MAX_DETAIL_LABEL_CHARS, strict=True)
    value: str = Field(max_length=MAX_DETAIL_VALUE_CHARS, strict=True)


class EvidencePresentation(Frozen):
    variant: str = Field(min_length=1, max_length=MAX_EVIDENCE_IDENTITY_CHARS, strict=True)
    display_label: str = Field(min_length=1, max_length=MAX_EVIDENCE_IDENTITY_CHARS, strict=True)
    details: tuple[EvidenceDetail, ...] = Field(max_length=MAX_EVIDENCE_DETAILS)


class SyntheticObservation(Frozen):
    variant: Literal["synthetic-observation-v1"] = "synthetic-observation-v1"
    strategy: Literal["synthetic-position-v1"] = "synthetic-position-v1"
    position: int = Field(ge=1, le=MAX_SNAPSHOT_RECORDS, strict=True)
    outcome: Literal["PASS", "FAIL", "SKIP"]

    def safe_summary(self):
        return f"Synthetic fixture position {self.position}: {self.outcome}. No external target was tested."


class SyntheticEvidencePolicy:
    executor_kind = ExecutorKind.SYNTHETIC
    payload_type = SyntheticObservation
    variant = SyntheticObservation.model_fields["variant"].default
    source = "synthetic"
    schema_version = EVIDENCE_SCHEMA_VERSION
    kind = OBSERVATION_KIND

    def validate_identity(self, source, schema_version, kind):
        if (source, schema_version, kind) != (self.source, self.schema_version, self.kind):
            raise ValueError("Invalid evidence identity")

    def validate_envelope(self, payload: SyntheticObservation, summary: str):
        if summary != payload.safe_summary():
            raise ValueError("Invalid evidence summary")

    def validate_result(self, payload: SyntheticObservation, result: QAResult):
        if payload.outcome != result:
            raise ValueError("Evidence does not describe the completed result")

    def validate_snapshot(self, payload: SyntheticObservation, snapshot: QARunTest):
        if payload.position != snapshot.position:
            raise ValueError("Evidence does not belong to the test snapshot")

    def presentation(self, payload: SyntheticObservation):
        return EvidencePresentation(variant=self.variant, display_label="SYNTHETIC", details=(
            EvidenceDetail(label="Strategy", value=payload.strategy),
            EvidenceDetail(label="Snapshot position", value=str(payload.position)),
            EvidenceDetail(label="Observed synthetic outcome", value=payload.outcome)))


class BrowserObservation(Frozen):
    variant: Literal["browser-observation-v1"] = "browser-observation-v1"
    category: Literal["NAVIGATION", "ASSERTION"]
    run_test_id: UUID
    plan_hash: Hash
    step_number: int = Field(ge=1, le=50, strict=True)
    action: Literal["NAVIGATE", "ASSERT_TEXT", "ASSERT_VISIBLE", "ASSERT_URL", "ASSERT_PAGE_LOAD"]
    matched: bool = Field(strict=True)
    outcome: Literal["PASS", "FAIL"]
    browser_version: str = Field(min_length=1,max_length=64,pattern=r"^[0-9]+(\.[0-9]+){3}$",strict=True)

    @model_validator(mode="after")
    def observation_kind(self):
        if (self.category == "NAVIGATION") != (self.action == "NAVIGATE"):
            raise ValueError("Browser observation category mismatch")
        if self.category == "NAVIGATION" and not self.matched:
            raise ValueError("Navigation failure is not completed evidence")
        return self

    def safe_summary(self):
        if self.action=="ASSERT_PAGE_LOAD":
            return f"Browser step {self.step_number}: completed load at the sealed destination with a 2xx main response {'matched' if self.matched else 'mismatched'}."
        return f"Browser step {self.step_number}: {self.action} {'matched' if self.matched else 'mismatched'}."


class BrowserEvidencePolicy(SyntheticEvidencePolicy):
    executor_kind = ExecutorKind.WEB_BROWSER
    payload_type = BrowserObservation
    variant = "browser-observation-v1"
    source = "web-browser"

    def validate_snapshot(self,payload,snapshot):
        plan=snapshot.browser_plan
        if (plan is None or payload.run_test_id!=snapshot.id or payload.plan_hash!=plan.plan_hash or
                payload.step_number>len(plan.plan.steps) or
                payload.action!=plan.plan.steps[payload.step_number-1].action):
            raise ValueError("Browser observation outside sealed test")

    def presentation(self,payload):
        return EvidencePresentation(variant=self.variant,display_label="WEB_BROWSER",details=(
            EvidenceDetail(label="Observed action",value=payload.action),
            EvidenceDetail(label="Snapshot step",value=str(payload.step_number)),
            EvidenceDetail(label="Matched",value=str(payload.matched)),
            EvidenceDetail(label="Chromium",value=payload.browser_version)))


BROWSER_EVIDENCE = BrowserEvidencePolicy()
SYNTHETIC_EVIDENCE = SyntheticEvidencePolicy()
# Compile-time closed discriminated boundary, not arbitrary JSON or runtime plugins.
# A future reviewed variant extends this alias and the explicit policy mapping.
EvidencePayload = Annotated[SyntheticObservation | BrowserObservation, Field(discriminator="variant")]
_POLICIES = MappingProxyType({SyntheticObservation: SYNTHETIC_EVIDENCE, BrowserObservation: BROWSER_EVIDENCE})


def evidence_policy(payload):
    policy = _POLICIES.get(type(payload))
    if policy is None:
        raise ValueError("Unregistered evidence variant")
    return policy


# Legacy fallback applies only to historical identities explicitly reviewed here.
_VARIANTS = MappingProxyType({policy.variant: policy for policy in _POLICIES.values()})
_LEGACY_IDENTITIES = MappingProxyType({
    (SYNTHETIC_EVIDENCE.source, SYNTHETIC_EVIDENCE.schema_version, SYNTHETIC_EVIDENCE.kind): SYNTHETIC_EVIDENCE,
})


def parse_payload(source, schema_version, kind, payload):
    if not all(isinstance(value, str) for value in (source, schema_version, kind)):
        raise ValueError("Invalid evidence identity")
    if isinstance(payload, Frozen):
        evidence_policy(payload)  # Unknown classes cannot masquerade as a registered variant.
        payload = payload.model_dump()
    if not isinstance(payload, dict):
        raise ValueError("Invalid typed evidence payload")
    if "variant" not in payload:
        # Old immutable 0011 rows predate the discriminator; no row rewrite.
        policy = _LEGACY_IDENTITIES.get((source, schema_version, kind))
    else:
        tag = payload["variant"]
        policy = _VARIANTS.get(tag) if isinstance(tag, str) else None
    if policy is None:
        raise ValueError("Unregistered evidence variant")
    policy.validate_identity(source, schema_version, kind)
    return policy.payload_type.model_validate(payload)
