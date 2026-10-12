"""Scoped server-side Test Design pages and fingerprinted human selection.

Selection holds no persisted state and exposes no ID list. At most 10,000 matches
are examined in 100-record keyset batches; approval reserves the existing writer
and revalidates the complete fingerprint before recording any receipt.
"""
from hashlib import sha256
from typing import Literal, Annotated
from uuid import UUID
from pydantic import Field, model_validator
from sqlalchemy import select, func, or_
from qa_sentinel.domain.campaign_content import Frozen, Hash
from qa_sentinel.domain.test_specification import CampaignTestSpecification
from qa_sentinel.domain.campaign_review import approve, content_hash, ApprovalCommand, ReviewError
from qa_sentinel.persistence.models import TestSpecificationRow as Test
from qa_sentinel.persistence.preparation_current import current_test
from qa_sentinel.application.errors import ApplicationError, ApplicationErrorCode as Code

MAX_MATCHES = 10_000
PAGE_SIZES = (10, 20, 50, 100)


class DesignCriteria(Frozen):
    search: str = Field(default="", max_length=200)
    status: Literal["ALL", "READY", "NEEDS_INFO", "DRAFT", "APPROVED"] = "ALL"


class DesignSelection(Frozen):
    criteria: DesignCriteria = Field(default_factory=DesignCriteria)
    ids: tuple[UUID, ...] | None = Field(default=None, min_length=1, max_length=100)

    expected_versions: dict[UUID, Annotated[str, Field(max_length=100)]] = Field(default_factory=dict, max_length=100)

    @model_validator(mode="after")
    def unique_ids(self):
        if self.ids and len(set(self.ids)) != len(self.ids):
            raise ValueError("Duplicate selection")
        if self.ids is not None and set(self.expected_versions) != set(self.ids):
            raise ValueError("Page selection requires displayed versions")
        if self.ids is None and self.expected_versions:
            raise ValueError("Matching selection uses a fingerprint")
        return self


class SelectionSummary(Frozen):
    fingerprint: Hash
    matched: int = Field(ge=0, le=MAX_MATCHES)
    eligible: int = Field(ge=0, le=MAX_MATCHES)


def query(project_id, campaign_id, selection):
    criteria = selection.criteria
    predicates = [Test.project_id == str(project_id), Test.campaign_id == str(campaign_id), current_test()]
    if criteria.search:
        # Literal substring matching, including %, _ and backslash.
        predicates.append(or_(Test.key.icontains(criteria.search, autoescape=True),
                              Test.title.icontains(criteria.search, autoescape=True)))
    statuses = {"READY": ("READY_FOR_REVIEW", "APPROVED"), "NEEDS_INFO": ("NEEDS_CLARIFICATION",),
                "DRAFT": ("DRAFT",), "APPROVED": ("APPROVED",)}
    if criteria.status != "ALL":
        predicates.append(Test.review_status.in_(statuses[criteria.status]))
    if selection.ids is not None:
        predicates.append(Test.id.in_([str(id) for id in selection.ids]))
    return select(Test).where(*predicates)


def approvable(test):
    try:
        approve(test, "TEST_SPECIFICATION", ApprovalCommand(reviewer_label="eligibility-check"))
        return True
    except ReviewError:
        return False


def records(uow, project_id, campaign_id, selection):
    statement = query(project_id, campaign_id, selection)
    after = ""
    seen = 0
    while True:
        rows = list(uow.session.scalars(statement.where(Test.id > after).order_by(Test.id).limit(100)))
        if not rows:
            break
        seen += len(rows)
        if seen > MAX_MATCHES:
            raise ApplicationError(Code.INVALID_LIST_LIMIT)
        yield from uow.test_specifications._specs(rows)
        after = rows[-1].id


def summarize(uow, project_id, campaign_id, selection):
    digest = sha256((str(project_id) + str(campaign_id) + selection.model_dump_json()).encode())
    matched = eligible = 0
    for test in records(uow, project_id, campaign_id, selection):
        if selection.ids is not None and selection.expected_versions[test.id] != f"{content_hash(test)}:{test.review_status}":
            raise ApplicationError(Code.REVIEW_CONFLICT)
        ready = approvable(test)
        digest.update(f"{test.id}:{content_hash(test)}:{test.review_status}:{ready};".encode())
        matched += 1
        eligible += ready
    if selection.ids is not None and matched != len(selection.ids):
        raise ApplicationError(Code.INVALID_INPUT)
    return SelectionSummary(fingerprint=digest.hexdigest(), matched=matched, eligible=eligible)


def design_page(uow, project_id, campaign_id, criteria, page, page_size):
    if type(page_size) is not int or page_size not in PAGE_SIZES or type(page) is not int or not 1 <= page <= 1_000_000:
        raise ApplicationError(Code.INVALID_LIST_LIMIT)
    statement = query(project_id, campaign_id, DesignSelection(criteria=criteria))
    total = uow.session.scalar(select(func.count()).select_from(statement.subquery()))
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    rows = list(uow.session.scalars(statement.order_by(Test.id).offset((page-1)*page_size).limit(page_size)))
    tests = uow.test_specifications._specs(rows)
    return dict(items=[dict(test=t, content_hash=content_hash(t), approvable=approvable(t)) for t in tests],
                total=total, page=page, page_size=page_size, total_pages=pages)


class DesignRow(Frozen):
    test: CampaignTestSpecification
    content_hash: Hash
    approvable: bool


class DesignPage(Frozen):
    items: tuple[DesignRow, ...] = Field(max_length=100)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int
    total_pages: int = Field(ge=1)


class ApprovalResult(Frozen):
    matched: int = Field(ge=0, le=MAX_MATCHES)
    approved: int = Field(ge=0, le=MAX_MATCHES)
    skipped: int = Field(ge=0, le=MAX_MATCHES)
