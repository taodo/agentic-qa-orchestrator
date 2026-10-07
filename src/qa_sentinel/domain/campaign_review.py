"""Explicit operator approval and derived preparation visibility, never execution."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Annotated, Literal
from uuid import UUID
from pydantic import Field, StringConstraints, AwareDatetime
from .campaign_content import Frozen

ReviewerLabel = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")]
ReviewNote = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1000)]
ObjectKind = Literal["REQUIREMENT", "TEST_SPECIFICATION"]
ReviewStatus = Literal["DRAFT", "NEEDS_CLARIFICATION", "READY_FOR_REVIEW", "APPROVED"]
Coverage = Literal["COVERED", "PARTIAL", "NOT_COVERED"]


class ApprovalCommand(Frozen):
    action: Literal["APPROVE"] = "APPROVE"
    reviewer_label: ReviewerLabel
    note: ReviewNote | None = None


class ApprovalEvidence(Frozen):
    object_id: UUID
    object_kind: ObjectKind
    project_id: UUID
    campaign_id: UUID
    status: Literal["APPROVED"] = "APPROVED"
    reviewer_label: ReviewerLabel
    note: ReviewNote | None = None
    content_hash: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$", strict=True)]
    approved_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReviewState(Frozen):
    project_id: UUID
    campaign_id: UUID
    object_id: UUID
    object_kind: ObjectKind
    review_status: ReviewStatus
    evidence: ApprovalEvidence | None


class RequirementTrace(Frozen):
    requirement_id: UUID
    review_status: ReviewStatus
    linked_test_count: int = Field(ge=0)
    approved_test_count: int = Field(ge=0)
    linked_test_review_states: dict[ReviewStatus, int]
    coverage: Coverage


class TraceLink(Frozen):
    requirement_id: UUID
    test_spec_id: UUID
    test_review_status: ReviewStatus


class Readiness(Frozen):
    project_id: UUID
    campaign_id: UUID
    campaign_preparation_status: Literal["DRAFT", "READY_FOR_REVIEW", "APPROVED"]
    status: Literal["READY", "NOT_READY"]
    total_requirements: int
    approved_requirements: int
    clarification_requirements: int
    total_test_specifications: int
    approved_test_specifications: int
    covered_requirements: int
    partial_requirements: int
    uncovered_requirements: int
    invalid_approved_requirements: int
    invalid_approved_test_specifications: int
    blocker_codes: tuple[Literal["CAMPAIGN_NOT_APPROVED", "NO_REQUIREMENTS", "REQUIREMENTS_NOT_APPROVED",
        "REQUIREMENTS_NEED_CLARIFICATION", "NO_TEST_SPECIFICATIONS", "REQUIREMENT_COVERAGE_GAP",
        "INVALID_REQUIREMENT_APPROVAL", "INVALID_TEST_APPROVAL"], ...]


def content_hash(record):
    # Status/time change on approval; facts, links, identity and provenance do not.
    content = record.model_dump(mode="json", exclude={"review_status", "updated_at"})
    return sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


class ReviewError(ValueError):
    pass


def approve(record, kind, command):
    # Revalidation also rejects model_copy() bypasses of the immutable contract.
    record = type(record).model_validate(record.model_dump())
    if record.review_status != "READY_FOR_REVIEW" or record.information_markers:
        raise ReviewError("REVIEW_NOT_REVIEWABLE")
    if kind == "TEST_SPECIFICATION" and (not record.requirement_ids or record.unresolved_requirement_refs):
        raise ReviewError("REVIEW_NOT_REVIEWABLE")
    return ApprovalEvidence(object_id=record.id, object_kind=kind, project_id=record.project_id,
        campaign_id=record.campaign_id, reviewer_label=command.reviewer_label, note=command.note,
        content_hash=content_hash(record))


def coverage(linked, approved):
    return "COVERED" if approved else "PARTIAL" if linked else "NOT_COVERED"


def assess_readiness(campaign, counts):
    blockers = []
    checks = (
        (campaign.status != "APPROVED", "CAMPAIGN_NOT_APPROVED"),
        (counts["total_requirements"] == 0, "NO_REQUIREMENTS"),
        (counts["approved_requirements"] != counts["total_requirements"], "REQUIREMENTS_NOT_APPROVED"),
        (counts["clarification_requirements"] > 0, "REQUIREMENTS_NEED_CLARIFICATION"),
        (counts["total_test_specifications"] == 0, "NO_TEST_SPECIFICATIONS"),
        (counts["partial_requirements"] + counts["uncovered_requirements"] > 0, "REQUIREMENT_COVERAGE_GAP"),
        (counts["invalid_approved_requirements"] > 0, "INVALID_REQUIREMENT_APPROVAL"),
        (counts["invalid_approved_test_specifications"] > 0, "INVALID_TEST_APPROVAL"),
    )
    for blocked, code in checks:
        if blocked: blockers.append(code)
    return Readiness(project_id=campaign.project_id, campaign_id=campaign.id,
        campaign_preparation_status=campaign.status, status="NOT_READY" if blockers else "READY",
        blocker_codes=tuple(blockers), **counts)
