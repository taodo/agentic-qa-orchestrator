"""Immutable preparation contracts. Execution progress and QA outcomes are independent."""
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import json
from typing import Annotated, Literal
from uuid import UUID, uuid4, uuid5
from pydantic import Field, StringConstraints, AwareDatetime, model_validator
from .target import TargetSnapshot
from .executor import ExecutorKind
from .browser_execution import BrowserPlanEnvelope, BrowserRuntimeIdentity, BrowserErrorCode
from .campaign import CampaignName, CampaignObjective
from .campaign_content import Frozen, CampaignRequirement, Hash
from .campaign_review import ApprovalEvidence, Readiness, content_hash
from .test_specification import CampaignTestSpecification

MAX_SNAPSHOT_RECORDS = 1000
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
SNAPSHOT_VERSION = "qa-run-snapshot-v1"
BROWSER_SNAPSHOT_VERSION = "qa-run-browser-v3"
IdempotencyKey = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
RunNote = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1000)]


class RunExecutionStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"  # Execution-system failure only; never an assertion failure.


class QAOutcome(StrEnum):
    NOT_EVALUATED = "NOT_EVALUATED"
    PASS = "PASS"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"


class RunTestExecutionStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"


class QAResult(StrEnum):
    NOT_EVALUATED = "NOT_EVALUATED"
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


class CreateQARun(Frozen):
    idempotency_key: IdempotencyKey
    note: RunNote | None = None
    test_specification_ids: tuple[UUID, ...] | None = Field(default=None,min_length=1,max_length=500)

    @model_validator(mode="after")
    def unique_selection(self):
        if self.test_specification_ids and len(set(self.test_specification_ids)) != len(self.test_specification_ids):
            raise ValueError("Duplicate selection")
        return self


class CampaignSnapshot(Frozen):
    id: UUID
    project_id: UUID
    name: CampaignName
    objective: CampaignObjective | None
    status: Literal["DRAFT", "READY_FOR_REVIEW", "APPROVED"]


class QARun(Frozen):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    campaign_id: UUID
    run_number: int = Field(ge=1, strict=True)
    idempotency_key: IdempotencyKey
    note: RunNote | None = None
    snapshot_version: Literal["qa-run-snapshot-v1", "qa-run-selection-v2", "qa-run-browser-v3"] = SNAPSHOT_VERSION
    snapshot_hash: Hash
    target_snapshot: TargetSnapshot | None = None
    executor_kind: ExecutorKind = ExecutorKind.SYNTHETIC
    runtime_identity: BrowserRuntimeIdentity | None = None
    browser_error_code: BrowserErrorCode | None = None
    campaign_snapshot: CampaignSnapshot
    readiness_at_creation: Readiness
    preparation_id: UUID | None = None
    requirement_count: int = Field(ge=0, le=MAX_SNAPSHOT_RECORDS, strict=True)
    test_count: int = Field(ge=1, le=MAX_SNAPSHOT_RECORDS, strict=True)
    execution_status: RunExecutionStatus = RunExecutionStatus.CREATED
    qa_outcome: QAOutcome = QAOutcome.NOT_EVALUATED
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    execution_error_code: Literal["RUN_EXECUTION_FAILED"] | None = None

    @model_validator(mode="after")
    def snapshot_owner(self):
        if self.snapshot_version != BROWSER_SNAPSHOT_VERSION and (self.requirement_count == 0 or self.preparation_id is not None):
            raise ValueError("Historical snapshots require Requirements and no preparation link")
        if self.snapshot_version == BROWSER_SNAPSHOT_VERSION and self.executor_kind != "WEB_BROWSER":
            raise ValueError("Browser-v3 is not a Synthetic escape hatch")
        if self.executor_kind == "SYNTHETIC" and (self.runtime_identity is not None or self.browser_error_code is not None):
            raise ValueError("Synthetic identity cannot contain browser claims")
        if self.executor_kind == "WEB_BROWSER" and (self.target_snapshot is None or self.runtime_identity is None):
            raise ValueError("Browser identity requires captured Target and runtime")
        if self.browser_error_code is not None and self.execution_status != "FAILED":
            raise ValueError("Browser system code requires execution failure")
        if self.execution_status == "CREATED" and (self.started_at or self.completed_at or self.execution_error_code or self.qa_outcome != "NOT_EVALUATED"):
            raise ValueError("Invalid CREATED lifecycle")
        if self.execution_status == "RUNNING" and (self.started_at is None or self.completed_at or self.execution_error_code or self.qa_outcome != "NOT_EVALUATED"):
            raise ValueError("Invalid RUNNING lifecycle")
        if self.execution_status in {"COMPLETED", "FAILED"}:
            if self.started_at is None or self.completed_at is None or self.completed_at < self.started_at:
                raise ValueError("Terminal execution needs valid timestamps")
            if self.execution_status == "FAILED" and (self.execution_error_code != "RUN_EXECUTION_FAILED" or self.qa_outcome not in {"PARTIAL", "NOT_EVALUATED"}):
                raise ValueError("Invalid system failure")
            if self.execution_status == "COMPLETED" and (self.execution_error_code or self.qa_outcome == "PARTIAL"):
                raise ValueError("Invalid normal completion")
        if self.target_snapshot is not None and self.target_snapshot.project_id != self.project_id:
            raise ValueError("Run target ownership invalid")
        if ((self.campaign_snapshot.project_id, self.campaign_snapshot.id) != (self.project_id, self.campaign_id)
                or (self.readiness_at_creation.project_id, self.readiness_at_creation.campaign_id) != (self.project_id, self.campaign_id)
                or (self.snapshot_version == "qa-run-snapshot-v1" and (self.campaign_snapshot.status != "APPROVED"
                    or self.readiness_at_creation.status != "READY" or self.readiness_at_creation.blocker_codes))):
            raise ValueError("Run requires its own READY preparation snapshot")
        return self


def validate_approval(content, approval, kind, *, source_free=False):
    from .campaign_review import source_free_reviewable
    blocked = not source_free_reviewable(content) if source_free and kind == "TEST_SPECIFICATION" else bool(content.information_markers)
    if (approval is None or content.review_status != "APPROVED" or blocked
            or (approval.object_id, approval.project_id, approval.campaign_id, approval.object_kind)
            != (content.id, content.project_id, content.campaign_id, kind)
            or approval.content_hash != content_hash(content)):
        raise ValueError("Snapshot approval does not match immutable content")


class QARunRequirement(Frozen):
    id: UUID
    run_id: UUID
    original_requirement_id: UUID
    position: int = Field(ge=1, le=MAX_SNAPSHOT_RECORDS, strict=True)
    content: CampaignRequirement
    approval: ApprovalEvidence

    @model_validator(mode="after")
    def approved(self):
        validate_approval(self.content, self.approval, "REQUIREMENT")
        if self.original_requirement_id != self.content.id or not self.content.acceptance_criteria:
            raise ValueError("Invalid requirement snapshot")
        return self


class QARunTest(Frozen):
    id: UUID
    run_id: UUID
    original_test_specification_id: UUID
    position: int = Field(ge=1, le=MAX_SNAPSHOT_RECORDS, strict=True)
    content: CampaignTestSpecification
    approval: ApprovalEvidence
    # Context is supplied by the owning Run, excluded from historical bytes/DB rows.
    snapshot_version: Literal["qa-run-snapshot-v1", "qa-run-selection-v2", "qa-run-browser-v3"] = Field(default=SNAPSHOT_VERSION, exclude=True)
    linked_requirement_snapshot_ids: tuple[UUID, ...] = Field(max_length=20)
    execution_status: RunTestExecutionStatus = RunTestExecutionStatus.NOT_STARTED
    qa_result: QAResult = QAResult.NOT_EVALUATED
    browser_plan: BrowserPlanEnvelope | None = None

    @model_validator(mode="after")
    def approved(self):
        if (self.execution_status == "COMPLETED") != (self.qa_result != "NOT_EVALUATED"):
            raise ValueError("QA results require completed test execution")
        source_free = self.snapshot_version == BROWSER_SNAPSHOT_VERSION
        validate_approval(self.content, self.approval, "TEST_SPECIFICATION", source_free=source_free)
        if (self.original_test_specification_id != self.content.id or self.content.unresolved_requirement_refs
                or (not source_free and (not self.content.requirement_ids or not self.linked_requirement_snapshot_ids))
                or (bool(self.content.requirement_ids) != bool(self.linked_requirement_snapshot_ids))):
            raise ValueError("Invalid test snapshot")
        return self


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def snapshot_fingerprint(campaign, requirements, tests, version=SNAPSHOT_VERSION, target_snapshot=None, runtime_identity=None, preparation_id=None):
    # Run identities, caller intent, wall-clock snapshot/approval timestamps and live
    # readiness counts are excluded. Accepted approval hashes are retained as stable
    # content-version identities (including their original immutable creation time).
    def facts(entry):
        fact = {"position": entry.position, "content": entry.content.model_dump(mode="json", exclude={"created_at", "updated_at"}),
                "approved_content_hash": entry.approval.content_hash}
        if getattr(entry, "browser_plan", None) is not None:
            fact["browser_plan"] = entry.browser_plan.model_dump(mode="json")
        return fact
    payload = {"version": version, "campaign": campaign.model_dump(mode="json"),
        "requirements": [facts(r) for r in requirements], "tests": [facts(t) for t in tests]}
    # Null keeps legacy fingerprints byte-for-byte; captured context is separately
    # versioned and included in the sealed fingerprint, never a live join.
    if target_snapshot is not None:
        payload["target_snapshot"] = target_snapshot.model_dump(mode="json")
    if runtime_identity is not None:
        payload["executor_kind"] = "WEB_BROWSER"
        payload["runtime_identity"] = runtime_identity.model_dump(mode="json")
    if preparation_id is not None:
        payload["preparation_id"] = str(preparation_id)
    return sha256(canonical_json(payload)).hexdigest()


class PreparedQARun(Frozen):
    run: QARun
    requirements: tuple[QARunRequirement, ...] = Field(max_length=MAX_SNAPSHOT_RECORDS)
    tests: tuple[QARunTest, ...] = Field(min_length=1, max_length=MAX_SNAPSHOT_RECORDS)

    @model_validator(mode="before")
    @classmethod
    def owning_version(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            run = value.get("run")
            version = run.snapshot_version if isinstance(run, QARun) else (run or {}).get("snapshot_version", SNAPSHOT_VERSION)
            value["tests"] = tuple(QARunTest.model_validate({
                **(test.model_dump() if isinstance(test, QARunTest) else test), "snapshot_version": version})
                for test in value.get("tests", ()))
        return value

    @model_validator(mode="after")
    def complete(self):
        run = self.run
        if (run.requirement_count, run.test_count) != (len(self.requirements), len(self.tests)):
            raise ValueError("Incomplete Run snapshot")
        ready = run.readiness_at_creation
        if run.snapshot_version == "qa-run-snapshot-v1" and (ready.approved_requirements, ready.total_requirements, ready.approved_test_specifications) != (len(self.requirements), len(self.requirements), len(self.tests)):
            raise ValueError("Snapshot does not match readiness selection")
        for entries in (self.requirements, self.tests):
            if [e.position for e in entries] != list(range(1, len(entries) + 1)) or len({e.id for e in entries}) != len(entries):
                raise ValueError("Snapshot order/identity invalid")
            originals = [e.content.id for e in entries]
            if len(set(originals)) != len(originals):
                raise ValueError("Duplicate original snapshot identity")
            for e in entries:
                if e.run_id != run.id or (e.content.project_id, e.content.campaign_id) != (run.project_id, run.campaign_id):
                    raise ValueError("Snapshot ownership invalid")
        ids = {r.content.id: r.id for r in self.requirements}
        covered = set()
        for test in self.tests:
            if any(id not in ids for id in test.content.requirement_ids):
                raise ValueError("Snapshot link outside Run")
            if tuple(ids[id] for id in test.content.requirement_ids) != test.linked_requirement_snapshot_ids:
                raise ValueError("Snapshot links inconsistent")
            covered.update(test.content.requirement_ids)
        if covered != set(ids):
            raise ValueError("Snapshot coverage incomplete")
        for test in self.tests:
            envelope = test.browser_plan
            if run.executor_kind == "SYNTHETIC":
                if envelope is not None: raise ValueError("Synthetic test cannot own a browser plan")
                continue
            if envelope is None: raise ValueError("Browser test requires sealed plan")
            def fingerprint(value): return sha256(canonical_json(value)).hexdigest()
            if ((envelope.project_id,envelope.campaign_id,envelope.run_id,envelope.run_test_id) !=
                    (run.project_id,run.campaign_id,run.id,test.id) or
                    envelope.plan_hash != fingerprint(envelope.plan.model_dump(mode="json")) or
                    envelope.target_snapshot_hash != fingerprint(run.target_snapshot.model_dump(mode="json")) or
                    envelope.test_snapshot_hash != fingerprint(test.model_dump(mode="json",exclude={"execution_status","qa_result","browser_plan"}))):
                raise ValueError("Browser plan provenance inconsistent")
        if run.snapshot_hash != snapshot_fingerprint(run.campaign_snapshot, self.requirements, self.tests, run.snapshot_version, run.target_snapshot, run.runtime_identity, run.preparation_id):
            raise ValueError("Snapshot fingerprint inconsistent")
        if len(canonical_json(self.model_dump(mode="json"))) > MAX_SNAPSHOT_BYTES:
            raise SnapshotSizeError()
        return self


class SnapshotSizeError(Exception):
    pass


def prepare_run(campaign, readiness, command, run_number, requirements, tests, target_snapshot=None):
    run_id = uuid4()
    campaign_snapshot = CampaignSnapshot.model_validate(campaign.model_dump(include=set(CampaignSnapshot.model_fields)))
    reqs = tuple(QARunRequirement(id=uuid5(run_id, "requirement:" + str(record.id)), run_id=run_id,
        original_requirement_id=record.id, position=i, content=record, approval=approval)
        for i, (record, approval) in enumerate(sorted(requirements, key=lambda pair: (pair[0].logical_key, str(pair[0].id))), 1))
    ids = {r.content.id: r.id for r in reqs}
    specs = tuple(QARunTest(id=uuid5(run_id, "test:" + str(record.id)), run_id=run_id,
        original_test_specification_id=record.id, position=i, content=record, approval=approval,
        linked_requirement_snapshot_ids=tuple(ids[id] for id in record.requirement_ids))
        for i, (record, approval) in enumerate(sorted(tests, key=lambda pair: (pair[0].logical_key, str(pair[0].id))), 1))
    version = "qa-run-selection-v2" if command.test_specification_ids is not None else SNAPSHOT_VERSION
    run = QARun(id=run_id, project_id=campaign.project_id, campaign_id=campaign.id, run_number=run_number,
        **command.model_dump(exclude={"test_specification_ids"}), snapshot_version=version, target_snapshot=target_snapshot, campaign_snapshot=campaign_snapshot, readiness_at_creation=readiness,
        requirement_count=len(reqs), test_count=len(specs), snapshot_hash=snapshot_fingerprint(campaign_snapshot, reqs, specs, version, target_snapshot))
    return PreparedQARun(run=run, requirements=reqs, tests=specs)
