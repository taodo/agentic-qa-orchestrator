"""Immutable preparation contracts. Execution progress and QA outcomes are independent."""
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import json
from typing import Annotated, Literal
from uuid import UUID, uuid4, uuid5
from pydantic import Field, StringConstraints, AwareDatetime, model_validator
from .campaign import CampaignName, CampaignObjective
from .campaign_content import Frozen, CampaignRequirement, Hash
from .campaign_review import ApprovalEvidence, Readiness, content_hash
from .test_specification import CampaignTestSpecification

MAX_SNAPSHOT_RECORDS = 1000
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
SNAPSHOT_VERSION = "qa-run-snapshot-v1"
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


class CampaignSnapshot(Frozen):
    id: UUID
    project_id: UUID
    name: CampaignName
    objective: CampaignObjective | None
    status: Literal["APPROVED"]


class QARun(Frozen):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    campaign_id: UUID
    run_number: int = Field(ge=1, strict=True)
    idempotency_key: IdempotencyKey
    note: RunNote | None = None
    snapshot_version: Literal["qa-run-snapshot-v1"] = SNAPSHOT_VERSION
    snapshot_hash: Hash
    campaign_snapshot: CampaignSnapshot
    readiness_at_creation: Readiness
    requirement_count: int = Field(ge=1, le=MAX_SNAPSHOT_RECORDS, strict=True)
    test_count: int = Field(ge=1, le=MAX_SNAPSHOT_RECORDS, strict=True)
    execution_status: RunExecutionStatus = RunExecutionStatus.CREATED
    qa_outcome: QAOutcome = QAOutcome.NOT_EVALUATED
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def snapshot_owner(self):
        if ((self.campaign_snapshot.project_id, self.campaign_snapshot.id) != (self.project_id, self.campaign_id)
                or (self.readiness_at_creation.project_id, self.readiness_at_creation.campaign_id) != (self.project_id, self.campaign_id)
                or self.readiness_at_creation.status != "READY" or self.readiness_at_creation.blocker_codes):
            raise ValueError("Run requires its own READY preparation snapshot")
        return self


def validate_approval(content, approval, kind):
    if (content.review_status != "APPROVED" or content.information_markers
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
    linked_requirement_snapshot_ids: tuple[UUID, ...] = Field(min_length=1, max_length=20)
    execution_status: RunTestExecutionStatus = RunTestExecutionStatus.NOT_STARTED
    qa_result: QAResult = QAResult.NOT_EVALUATED

    @model_validator(mode="after")
    def approved(self):
        validate_approval(self.content, self.approval, "TEST_SPECIFICATION")
        if (self.original_test_specification_id != self.content.id or not self.content.requirement_ids
                or self.content.unresolved_requirement_refs):
            raise ValueError("Invalid test snapshot")
        return self


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def snapshot_fingerprint(campaign, requirements, tests):
    # Run identities, caller intent, wall-clock snapshot/approval timestamps and live
    # readiness counts are excluded. Accepted approval hashes are retained as stable
    # content-version identities (including their original immutable creation time).
    def facts(entry):
        return {"position": entry.position, "content": entry.content.model_dump(mode="json", exclude={"created_at", "updated_at"}),
                "approved_content_hash": entry.approval.content_hash}
    return sha256(canonical_json({"version": SNAPSHOT_VERSION, "campaign": campaign.model_dump(mode="json"),
        "requirements": [facts(r) for r in requirements], "tests": [facts(t) for t in tests]})).hexdigest()


class PreparedQARun(Frozen):
    run: QARun
    requirements: tuple[QARunRequirement, ...] = Field(min_length=1, max_length=MAX_SNAPSHOT_RECORDS)
    tests: tuple[QARunTest, ...] = Field(min_length=1, max_length=MAX_SNAPSHOT_RECORDS)

    @model_validator(mode="after")
    def complete(self):
        run = self.run
        if (run.requirement_count, run.test_count) != (len(self.requirements), len(self.tests)):
            raise ValueError("Incomplete Run snapshot")
        ready = run.readiness_at_creation
        if (ready.approved_requirements, ready.total_requirements, ready.approved_test_specifications) != (len(self.requirements), len(self.requirements), len(self.tests)):
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
        if run.snapshot_hash != snapshot_fingerprint(run.campaign_snapshot, self.requirements, self.tests):
            raise ValueError("Snapshot fingerprint inconsistent")
        if len(canonical_json(self.model_dump(mode="json"))) > MAX_SNAPSHOT_BYTES:
            raise SnapshotSizeError()
        return self


class SnapshotSizeError(Exception):
    pass


def prepare_run(campaign, readiness, command, run_number, requirements, tests):
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
    run = QARun(id=run_id, project_id=campaign.project_id, campaign_id=campaign.id, run_number=run_number,
        **command.model_dump(), campaign_snapshot=campaign_snapshot, readiness_at_creation=readiness,
        requirement_count=len(reqs), test_count=len(specs), snapshot_hash=snapshot_fingerprint(campaign_snapshot, reqs, specs))
    return PreparedQARun(run=run, requirements=reqs, tests=specs)
