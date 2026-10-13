"""Pre-Run intent and preparation outcomes; never browser execution evidence."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Literal
from uuid import UUID, uuid4, uuid5
from pydantic import AwareDatetime, Field, model_validator
from .campaign_content import Frozen, Hash
from .campaign_review import ApprovalEvidence, content_hash
from .qa_run import IdempotencyKey, canonical_json, validate_approval
from .target import TargetSnapshot
from .test_specification import CampaignTestSpecification

PREPARATION_VERSION = "browser-preparation-v1"
MAX_PREPARATION_BYTES = 16 * 1024 * 1024
BrowserMode = Literal["HEADLESS", "HEADED"]
PreparationStatus = Literal["CREATED", "PREPARING", "COMPLETED", "FAILED"]
ItemStatus = Literal["PENDING", "PREPARING", "RUNNABLE", "NEEDS_ATTENTION", "SYSTEM_ERROR"]
ReasonCode = Literal["INSUFFICIENT_TEST_INFORMATION", "AMBIGUOUS_TARGET", "UNSUPPORTED_BEHAVIOR", "POLICY_REJECTED", "GROUNDING_UNAVAILABLE", "PREPARATION_SYSTEM_ERROR", "PREPARATION_INTERRUPTED"]
TERMINAL_ITEMS = {"RUNNABLE", "NEEDS_ATTENTION", "SYSTEM_ERROR"}


def now():
    return datetime.now(timezone.utc)


class PreparationSizeError(Exception):
    """A complete selection cannot fit; never wrap as an invalid approval."""


class PreparationError(ValueError):
    pass


class CreateBrowserPreparation(Frozen):
    idempotency_key: IdempotencyKey
    browser_mode: BrowserMode = "HEADLESS"
    test_specification_ids: tuple[UUID, ...] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.test_specification_ids)) != len(self.test_specification_ids):
            raise ValueError("Duplicate selected Test")
        return self


class PreparationItem(Frozen):
    id: UUID
    preparation_id: UUID
    original_test_id: UUID
    position: int = Field(ge=1, le=500, strict=True)
    test: CampaignTestSpecification
    approval: ApprovalEvidence
    test_hash: Hash
    status: ItemStatus = "PENDING"
    attempt_id: UUID | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    reason_code: ReasonCode | None = None
    # Identifiers/hashes only: observation payloads belong to 5.8B.
    grounding_id: UUID | None = None
    observation_hash: Hash | None = None
    plan_hash: Hash | None = None

    @model_validator(mode="after")
    def identity_and_progress(self):
        validate_approval(self.test, self.approval, "TEST_SPECIFICATION", source_free=True)
        if self.original_test_id != self.test.id or self.test_hash != content_hash(self.test):
            raise ValueError("Preparation Test identity mismatch")
        hooks = (self.grounding_id, self.observation_hash, self.plan_hash)
        if self.status == "PENDING":
            if self.attempt_id or self.started_at or self.finished_at or self.reason_code or any(hooks):
                raise ValueError("Pending item cannot claim work")
        else:
            if self.attempt_id is None or self.started_at is None:
                raise ValueError("Preparation work needs durable attempt identity")
            if self.status == "PREPARING":
                if self.finished_at or self.reason_code or any(hooks):
                    raise ValueError("Started item cannot claim completion")
            elif self.finished_at is None or self.finished_at < self.started_at:
                raise ValueError("Terminal item needs ordered timestamps")
        if self.status == "RUNNABLE":
            if self.reason_code or any(h is None for h in hooks):
                raise ValueError("Runnable item requires sealed grounding identity")
        elif any(hooks):
            raise ValueError("Non-runnable item cannot claim a sealed plan")
        if self.status == "NEEDS_ATTENTION" and self.reason_code not in {"INSUFFICIENT_TEST_INFORMATION", "AMBIGUOUS_TARGET", "UNSUPPORTED_BEHAVIOR", "POLICY_REJECTED", "GROUNDING_UNAVAILABLE"}:
            raise ValueError("Needs attention requires safe actionable reason")
        if self.status == "SYSTEM_ERROR" and self.reason_code not in {"PREPARATION_SYSTEM_ERROR", "PREPARATION_INTERRUPTED"}:
            raise ValueError("System failure requires a system reason")
        return self


def selection_hash(target, mode, items):
    return sha256(canonical_json({"version": PREPARATION_VERSION,
        "target": target.model_dump(mode="json"), "browser_mode": mode,
        "selection": [{"position": i.position, "test": i.test.model_dump(mode="json"),
            "approval": i.approval.model_dump(mode="json"), "test_hash": i.test_hash} for i in items]})).hexdigest()


class BrowserPreparation(Frozen):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    contract_version: Literal["browser-preparation-v1"] = PREPARATION_VERSION
    target_snapshot: TargetSnapshot
    browser_mode: BrowserMode
    idempotency_key: IdempotencyKey
    selection_hash: Hash
    selected_count: int = Field(ge=1, le=500, strict=True)
    items: tuple[PreparationItem, ...] = Field(min_length=1, max_length=500)
    status: PreparationStatus = "CREATED"
    created_at: AwareDatetime = Field(default_factory=now)
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    error_code: Literal["PREPARATION_SYSTEM_ERROR", "PREPARATION_INTERRUPTED"] | None = None

    @model_validator(mode="after")
    def sealed_selection(self):
        if self.target_snapshot.project_id != self.project_id or self.selected_count != len(self.items):
            raise ValueError("Preparation ownership/count mismatch")
        if ([i.position for i in self.items] != list(range(1, len(self.items) + 1))
                or len({i.id for i in self.items}) != len(self.items)
                or len({i.original_test_id for i in self.items}) != len(self.items)):
            raise ValueError("Preparation selection identity/order mismatch")
        for item in self.items:
            if (item.preparation_id != self.id or (item.test.project_id, item.test.campaign_id) != (self.project_id, self.campaign_id)
                    or item.id != uuid5(self.id, "test:" + str(item.original_test_id))):
                raise ValueError("Preparation item ownership mismatch")
        if self.selection_hash != selection_hash(self.target_snapshot, self.browser_mode, self.items):
            raise ValueError("Preparation fingerprint mismatch")
        if self.status == "CREATED":
            if self.started_at or self.finished_at or self.error_code or any(i.status != "PENDING" for i in self.items):
                raise ValueError("Created preparation cannot claim work")
        else:
            if self.started_at is None or self.started_at < self.created_at:
                raise ValueError("Preparation needs ordered start time")
            if any(i.started_at and i.started_at < self.started_at for i in self.items):
                raise ValueError("Item started before preparation")
            if self.status == "PREPARING":
                if self.finished_at or self.error_code:
                    raise ValueError("Started preparation cannot claim completion")
            elif self.finished_at is None or self.finished_at < self.started_at or any(i.finished_at and i.finished_at > self.finished_at for i in self.items):
                raise ValueError("Preparation needs ordered finish time")
            if self.status == "COMPLETED" and (self.error_code or any(i.status not in TERMINAL_ITEMS for i in self.items)):
                raise ValueError("Completed preparation must retain all item outcomes")
            if self.status == "FAILED" and self.error_code is None:
                raise ValueError("Failed preparation needs safe system code")
        if len(json.dumps(self.model_dump(mode="json", exclude={"resulting_run_id"}), allow_nan=False).encode("utf-8")) > MAX_PREPARATION_BYTES:
            raise PreparationSizeError()
        return self


class BrowserPreparationView(BrowserPreparation):
    resulting_run_id: UUID | None = None


def create_preparation(project_id, campaign_id, command, target, selected):
    command = CreateBrowserPreparation.model_validate(command.model_dump())
    id = uuid4()
    items = tuple(PreparationItem(id=uuid5(id, "test:" + str(test.id)), preparation_id=id,
        original_test_id=test.id, position=n, test=test, approval=approval, test_hash=content_hash(test))
        for n, (test, approval) in enumerate(selected, 1))
    if tuple(i.original_test_id for i in items) != command.test_specification_ids:
        raise ValueError("Preparation must retain exact ordered selection")
    return BrowserPreparation(id=id, project_id=project_id, campaign_id=campaign_id,
        target_snapshot=target, browser_mode=command.browser_mode, idempotency_key=command.idempotency_key,
        selection_hash=selection_hash(target, command.browser_mode, items), selected_count=len(items), items=items)


def start_preparation(record):
    if record.status != "CREATED":
        raise PreparationError("PREPARATION_INVALID_STATE")
    return BrowserPreparation.model_validate({**record.model_dump(), "status": "PREPARING", "started_at": now()})


def start_item(record, item_id):
    if record.status != "PREPARING":
        raise PreparationError("PREPARATION_INVALID_STATE")
    item = next((i for i in record.items if i.id == item_id), None)
    if item is None or item.status != "PENDING":
        raise PreparationError("PREPARATION_INVALID_STATE")
    changed = PreparationItem.model_validate({**item.model_dump(), "status": "PREPARING", "attempt_id": uuid4(), "started_at": now()})
    return BrowserPreparation.model_validate({**record.model_dump(), "items": tuple(changed if i.id == item_id else i for i in record.items)})


def finish_item(record, item_id, *, attempt_id, status, reason_code=None, grounding_id=None, observation_hash=None, plan_hash=None):
    if record.status != "PREPARING" or status not in TERMINAL_ITEMS:
        raise PreparationError("PREPARATION_INVALID_STATE")
    item = next((i for i in record.items if i.id == item_id), None)
    if item is None or item.status != "PREPARING" or item.attempt_id != attempt_id:
        raise PreparationError("PREPARATION_INVALID_STATE")
    changed = PreparationItem.model_validate({**item.model_dump(), "status": status, "finished_at": now(),
        "reason_code": reason_code, "grounding_id": grounding_id, "observation_hash": observation_hash, "plan_hash": plan_hash})
    return BrowserPreparation.model_validate({**record.model_dump(), "items": tuple(changed if i.id == item_id else i for i in record.items)})


def finish_preparation(record, *, error_code=None):
    if record.status != "PREPARING":
        raise PreparationError("PREPARATION_INVALID_STATE")
    return BrowserPreparation.model_validate({**record.model_dump(), "status": "FAILED" if error_code else "COMPLETED", "error_code": error_code, "finished_at": now()})
