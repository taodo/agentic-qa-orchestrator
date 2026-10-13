"""Current observation references and immutable grounding; not QA execution evidence."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Annotated, Literal
from uuid import UUID, uuid4
from urllib.parse import urlsplit
from pydantic import Field, StringConstraints, AwareDatetime, model_validator
from .campaign_content import Frozen, Hash
from .browser_execution import BrowserRuntimeIdentity, BrowserAction, RoleLocator, LabelLocator, PlaceholderLocator
from .target import TargetSnapshot
from .qa_run import canonical_json
from qa_sentinel.execution.browser_policy import BrowserExecutionPolicy, relative_destination
from qa_sentinel.models.base import ModelSettings, ModelMetadata

OBSERVATION_VERSION="browser-grounding-observation-v1"
GROUNDING_VERSION="browser-grounding-v1"
MAX_OBSERVATION_BYTES=65536
MAX_MODEL_BYTES=196608
MAX_OUTPUT_BYTES=16384
SafeText=Annotated[str,StringConstraints(strict=True,max_length=512)]
ElementRef=Annotated[str,StringConstraints(strict=True,pattern=r"^e[1-9][0-9]?$|^e100$")]
PathRef=Annotated[str,StringConstraints(strict=True,pattern=r"^p[1-9][0-9]?$")]
ValueRef=Annotated[str,StringConstraints(strict=True,pattern=r"^v([1-9]|1[0-9]|20)$")]
OperationName=Literal["NAVIGATE","CLICK","FILL","SELECT","CHECK"]
Reason=Literal["INSUFFICIENT_TEST_INFORMATION","AMBIGUOUS_TARGET","UNSUPPORTED_BEHAVIOR","POLICY_REJECTED","GROUNDING_UNAVAILABLE","INVALID_REFERENCE","OBSERVATION_LIMIT","CONTEXT_LIMIT","MODEL_UNAVAILABLE","OBSERVATION_RUNTIME_ERROR"]


def now(): return datetime.now(timezone.utc)
def digest(value): return sha256(canonical_json(value.model_dump(mode="json") if hasattr(value,"model_dump") else value)).hexdigest()


class GroundingLimitation(Exception):
    def __init__(self,reason,step=None):
        self.reason=reason;self.step=step
        super().__init__(reason)


def secret_looking(text):
    return bool(re.search(r"(?i)(?:\b(?:bearer|password|passwd|credential|cookie|otp|2fa|secret|session|token)\b|api[ _-]?key|sk-[a-z0-9_-]{8,}|gh[pousr]_[a-z0-9]{8,}|[a-z0-9_-]{20,}\.[a-z0-9_-]{20,}\.[a-z0-9_-]{10,}|\b[a-f0-9]{32,}\b)",text))


def safe_path(value,target):
    parsed=urlsplit(value)
    if parsed.query or parsed.fragment or parsed.scheme or parsed.netloc or secret_looking(value):
        raise GroundingLimitation("POLICY_REJECTED")
    try: relative_destination(target.base_url,value)
    except ValueError: raise GroundingLimitation("POLICY_REJECTED") from None
    return value


class ObservationLimits(Frozen):
    version: Literal["single-page-observation-v1"]="single-page-observation-v1"
    pages: Literal[1]=1
    max_elements: Literal[80]=80
    max_paths: Literal[20]=20
    max_text_chars: Literal[16384]=16384
    max_bytes: Literal[65536]=MAX_OBSERVATION_BYTES
    test_timeout_ms: Literal[20000]=20000
    redirect_limit: Literal[1]=1


class GroundingScope(Frozen):
    project_id: UUID
    campaign_id: UUID
    preparation_id: UUID
    item_id: UUID
    attempt_id: UUID
    test_id: UUID
    test_hash: Hash
    approval_hash: Hash
    target: TargetSnapshot
    target_hash: Hash
    policy: BrowserExecutionPolicy
    policy_version: Literal["pinned-observation-network-v1"]="pinned-observation-network-v1"
    limits: ObservationLimits=Field(default_factory=ObservationLimits)

    @model_validator(mode="after")
    def owner(self):
        if secret_looking(self.target.base_url):raise ValueError("Sensitive Target cannot be grounded")
        if self.target.project_id!=self.project_id or self.target_hash!=digest(self.target):
            raise ValueError("Grounding Target identity mismatch")
        return self


ObservedLocator=Annotated[RoleLocator | LabelLocator | PlaceholderLocator,Field(discriminator="strategy")]


class ObservedElement(Frozen):
    ref: ElementRef
    role: Literal["heading","button","link","textbox","checkbox","combobox"]
    name: Annotated[str,StringConstraints(strict=True,max_length=256)] | None
    text: SafeText=""
    visible: Literal[True]=True
    enabled: bool=Field(default=True,strict=True)
    sensitive: bool=Field(default=False,strict=True)
    blocked_destination: bool=Field(default=False,strict=True)
    locator: ObservedLocator | None
    matches: int=Field(ge=0,le=80,strict=True)
    path_ref: PathRef | None=None

    @model_validator(mode="after")
    def safe(self):
        if secret_looking((self.name or "")+" "+self.text):raise ValueError("Sensitive observation text is not admissible")
        if self.sensitive and (self.name is not None or self.text or self.locator is not None):raise ValueError("Sensitive control cannot contain captured data")
        if self.locator is not None and (not self.locator.exact or (self.locator.strategy=="ROLE" and (self.locator.role!=self.role or self.locator.name!=self.name))):
            raise ValueError("Observed locator must be exact")
        return self


class ObservedPath(Frozen):
    ref: PathRef
    path: Annotated[str,StringConstraints(strict=True,min_length=1,max_length=2048)]
    source: Literal["TARGET_BASE","CURRENT_PAGE","LINK"]
    element_ref: ElementRef | None=None


class BrowserGroundingObservation(Frozen):
    id: UUID=Field(default_factory=uuid4)
    contract_version: Literal["browser-grounding-observation-v1"]=OBSERVATION_VERSION
    scope: GroundingScope
    runtime_identity: BrowserRuntimeIdentity
    started_at: AwareDatetime
    finished_at: AwareDatetime
    current_path_ref: PathRef
    title: SafeText
    elements: tuple[ObservedElement,...]=Field(max_length=80)
    paths: tuple[ObservedPath,...]=Field(min_length=1,max_length=20)
    observation_hash: Hash

    @model_validator(mode="after")
    def canonical(self):
        if self.finished_at<self.started_at or (self.finished_at-self.started_at).total_seconds()>25:raise ValueError("Observation time bound")
        if [e.ref for e in self.elements]!=["e"+str(n) for n in range(1,len(self.elements)+1)]:raise ValueError("Observation-local element order")
        if [p.ref for p in self.paths]!=["p"+str(n) for n in range(1,len(self.paths)+1)] or len({p.path for p in self.paths})!=len(self.paths):raise ValueError("Observation-local path order")
        refs={p.ref for p in self.paths};elements={e.ref:e for e in self.elements}
        if self.current_path_ref not in refs or self.paths[0].source!="TARGET_BASE" or self.paths[0].path!=(urlsplit(self.scope.target.base_url).path or "/"):raise ValueError("Observation current/base path mismatch")
        for path in self.paths:
            safe_path(path.path,self.scope.target)
            if path.source=="LINK" and (path.element_ref not in elements or elements[path.element_ref].path_ref!=path.ref):raise ValueError("Link observation provenance mismatch")
        if any(e.path_ref not in refs for e in self.elements if e.path_ref is not None):raise ValueError("Unknown observed path")
        if secret_looking(self.title):raise ValueError("Sensitive page title")
        if len(self.title)+sum(len(e.name or "")+len(e.text) for e in self.elements)+sum(len(p.path) for p in self.paths)>self.scope.limits.max_text_chars:raise ValueError("Observation aggregate text bound")
        payload=self.model_dump(mode="json",exclude={"observation_hash"})
        if digest(payload)!=self.observation_hash or len(canonical_json(self.model_dump(mode="json")))>MAX_OBSERVATION_BYTES:raise ValueError("Observation hash/byte bound")
        return self


class TestValue(Frozen):
    ref: ValueRef
    step_index: int=Field(ge=1,le=20,strict=True)
    value: Annotated[str,StringConstraints(strict=True,min_length=1,max_length=64)]

    @model_validator(mode="after")
    def non_secret(self):
        if secret_looking(self.value) or any(ord(c)<32 for c in self.value):raise ValueError("Unsafe Test-derived value")
        return self


class GroundingOperation(Frozen):
    action: OperationName
    element_ref: ElementRef | None
    path_ref: PathRef | None
    value_ref: ValueRef | None

    @model_validator(mode="after")
    def shape(self):
        if self.action=="NAVIGATE":
            if self.path_ref is None or self.element_ref or self.value_ref:raise ValueError("Navigation reference shape")
        elif self.element_ref is None or self.path_ref is not None or ((self.action in {"FILL","SELECT","CHECK"})!=(self.value_ref is not None)):
            raise ValueError("Control reference shape")
        return self


class GroundingAssertion(Frozen):
    kind: Literal["TEXT","VISIBLE","URL"]
    element_ref: ElementRef | None
    path_ref: PathRef | None

    @model_validator(mode="after")
    def shape(self):
        if (self.kind=="URL" and (self.path_ref is None or self.element_ref)) or (self.kind!="URL" and (self.element_ref is None or self.path_ref)):
            raise ValueError("Assertion reference shape")
        return self


class GroundingStep(Frozen):
    step_index: int=Field(ge=1,le=20,strict=True)
    operations: tuple[GroundingOperation,...]=Field(max_length=4)
    assertion: GroundingAssertion


class GroundingOutput(Frozen):
    observation_id: UUID
    observation_hash: Hash
    test_hash: Hash
    target_hash: Hash
    disposition: Literal["GROUNDED","CANNOT_GROUND"]
    steps: tuple[GroundingStep,...]=Field(max_length=20)
    reason: Reason | None
    affected_step: int | None=Field(default=None,ge=1,le=20,strict=True)

    @model_validator(mode="after")
    def shape(self):
        if self.disposition=="GROUNDED" and (not self.steps or self.reason is not None or self.affected_step is not None):raise ValueError("Grounded output shape")
        if self.disposition=="CANNOT_GROUND" and (self.steps or self.reason is None):raise ValueError("Cannot-ground output shape")
        if sum(len(s.operations)+1 for s in self.steps)>50 or len(canonical_json(self.model_dump(mode="json")))>MAX_OUTPUT_BYTES:raise ValueError("Grounding output bound")
        return self


class SystemBrowserConstraints(Frozen):
    contract_version: Literal["system-browser-constraints-v1"]="system-browser-constraints-v1"
    observation_id: UUID
    observation_hash: Hash
    grounding_id: UUID
    required_actions: tuple[tuple[OperationName,...],...]=Field(min_length=1,max_length=20)
    locators: tuple[ObservedLocator,...]=Field(max_length=20)
    paths: tuple[str,...]=Field(max_length=20)
    input_values: tuple[str,...]=Field(max_length=20)
    # Per-action manifest additionally constrains the legacy planner's global allowlists.
    action_manifest: tuple[BrowserAction,...]=Field(max_length=50)
    step_bindings: tuple[int,...]=Field(max_length=50)


class BrowserGroundingRecord(Frozen):
    id: UUID=Field(default_factory=uuid4)
    contract_version: Literal["browser-grounding-v1"]=GROUNDING_VERSION
    scope: GroundingScope
    settings: ModelSettings
    prompt_version: Literal["browser-grounder-v1"]="browser-grounder-v1"
    status: Literal["STARTED","GROUNDED","NEEDS_ATTENTION","SYSTEM_ERROR"]="STARTED"
    started_at: AwareDatetime=Field(default_factory=now)
    finished_at: AwareDatetime | None=None
    observation_id: UUID | None=None
    observation_hash: Hash | None=None
    intent_hash: Hash | None=None
    output: GroundingOutput | None=None
    constraints: SystemBrowserConstraints | None=None
    metadata: ModelMetadata | None=None
    reason: Reason | None=None
    affected_step: int | None=Field(default=None,ge=1,le=20,strict=True)
    browser_error_code: str | None=Field(default=None,pattern=r"^BROWSER_[A-Z_]+$")

    @model_validator(mode="after")
    def lifecycle(self):
        if self.status=="STARTED":
            if any(v is not None for v in (self.finished_at,self.observation_id,self.observation_hash,self.intent_hash,self.output,self.constraints,self.metadata,self.reason,self.affected_step,self.browser_error_code)):
                raise ValueError("Started grounding does not claim completion")
        elif self.finished_at is None or self.finished_at<self.started_at:raise ValueError("Grounding completion timestamp")
        if self.status=="GROUNDED":
            if self.output is None or self.output.disposition!="GROUNDED" or self.constraints is None or self.reason or self.metadata is None or self.metadata.status!="completed" or self.intent_hash is None:
                raise ValueError("Grounded record needs validated output and provider completion")
            if (self.output.observation_id,self.output.observation_hash,self.output.test_hash,self.output.target_hash)!=(self.observation_id,self.observation_hash,self.scope.test_hash,self.scope.target_hash):raise ValueError("Grounding output scope mismatch")
            if self.browser_error_code is not None or self.affected_step is not None:raise ValueError("Grounding success cannot claim failure")
            if (self.observation_id,self.observation_hash,self.id)!=(self.constraints.observation_id,self.constraints.observation_hash,self.constraints.grounding_id):raise ValueError("Grounding constraint provenance mismatch")
        if self.status in {"NEEDS_ATTENTION","SYSTEM_ERROR"} and (self.reason is None or self.output is not None or self.constraints is not None):raise ValueError("Limitation cannot claim a grounded result")
        if (self.observation_id is None)!=(self.observation_hash is None):raise ValueError("Observation identity pair")
        if len(canonical_json(self.model_dump(mode="json")))>131072:raise ValueError("Grounding record bound")
        return self


ACTION_HINTS={
    "INSUFFICIENT_TEST_INFORMATION":"Clarify the Test action and literal expected result, then review the new Test version.",
    "AMBIGUOUS_TARGET":"Clarify which visible control the Test means; identical candidates cannot be chosen safely.",
    "UNSUPPORTED_BEHAVIOR":"Use a supported public-page Test without credentials or secret values.",
    "POLICY_REJECTED":"Review Target configuration with the local operator; network protections remain enforced.",
    "GROUNDING_UNAVAILABLE":"Review the Test against the current page; the required visible candidate is unavailable.",
    "INVALID_REFERENCE":"Review the failed attempt; its structured references do not match the immutable inputs.",
    "OBSERVATION_LIMIT":"Use a smaller page/Test surface; required facts exceeded the observation limits.",
    "CONTEXT_LIMIT":"Reduce the Test/page scope; required context cannot fit without truncation.",
    "MODEL_UNAVAILABLE":"Ask the operator to check model availability; this attempt was not retried.",
    "OBSERVATION_RUNTIME_ERROR":"Ask the operator to check the Chromium/network runtime; this is not QA FAIL.",
}


def action_hint(record):
    return None if record.reason is None else ACTION_HINTS[record.reason]
