"""Atomic approval receipts and bounded SQL-only traceability/readiness queries."""
from sqlalchemy import select, func, case, and_, update
from qa_sentinel.domain.campaign_review import (ApprovalEvidence, ReviewError, ReviewState,
    RequirementTrace, TraceLink, approve, content_hash, coverage)
from .models import (CampaignRequirementRow as Requirement, TestSpecificationRow as Specification,
    TestRequirementLinkRow as Link, RequirementReviewRow, TestSpecificationReviewRow)


class CampaignReviewRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def _types(kind):
        if kind == "REQUIREMENT": return Requirement, RequirementReviewRow
        if kind == "TEST_SPECIFICATION": return Specification, TestSpecificationReviewRow
        raise ValueError("Invalid reviewed object kind")

    def evidence(self, record, kind):
        _, table = self._types(kind)
        row = self.session.get(table, str(record.id))
        evidence = None if row is None else ApprovalEvidence.model_validate({
            "object_kind": kind, **{name: getattr(row, name) for name in ApprovalEvidence.model_fields if name != "object_kind"}})
        if evidence is not None and (evidence.project_id != record.project_id or evidence.campaign_id != record.campaign_id
                or evidence.content_hash != content_hash(record) or record.review_status != "APPROVED"):
            raise ReviewError("REVIEW_EVIDENCE_INVALID")
        if record.review_status == "APPROVED" and evidence is None:
            raise ReviewError("REVIEW_EVIDENCE_INVALID")
        return evidence

    def state(self, record, kind):
        return ReviewState(project_id=record.project_id, campaign_id=record.campaign_id, object_id=record.id,
            object_kind=kind, review_status=record.review_status, evidence=self.evidence(record, kind))

    def approve(self, record, kind, command):
        # Caller reserves the accepted SQLite writer before reading; no external work.
        evidence = self.evidence(record, kind)
        if evidence is not None:
            if (evidence.reviewer_label, evidence.note) != (command.reviewer_label, command.note):
                raise ReviewError("REVIEW_CONFLICT")
            return self.state(record, kind)
        evidence = approve(record, kind, command)
        object_table, review_table = self._types(kind)
        changed = self.session.execute(update(object_table).where(object_table.id == str(record.id),
            object_table.campaign_id == str(record.campaign_id), object_table.project_id == str(record.project_id),
            object_table.review_status == "READY_FOR_REVIEW").values(review_status="APPROVED", updated_at=evidence.approved_at))
        if changed.rowcount != 1: raise ReviewError("REVIEW_CONFLICT")
        values = evidence.model_dump(mode="json", exclude={"object_kind"})
        values["approved_at"] = evidence.approved_at
        self.session.add(review_table(**values))
        self.session.flush()
        return ReviewState(project_id=record.project_id, campaign_id=record.campaign_id, object_id=record.id,
            object_kind=kind, review_status="APPROVED", evidence=evidence)

    @staticmethod
    def _scope(table, project_id, campaign_id):
        return and_(table.project_id == str(project_id), table.campaign_id == str(campaign_id))

    @staticmethod
    def _eligible_spec():
        receipt = select(TestSpecificationReviewRow.object_id).where(TestSpecificationReviewRow.object_id == Specification.id,
            TestSpecificationReviewRow.campaign_id == Specification.campaign_id,
            TestSpecificationReviewRow.project_id == Specification.project_id).correlate(Specification).exists()
        known_link = select(Link.test_spec_id).where(Link.test_spec_id == Specification.id,
            Link.campaign_id == Specification.campaign_id, Link.project_id == Specification.project_id).correlate(Specification).exists()
        return and_(Specification.review_status == "APPROVED", func.json_array_length(Specification.information_markers) == 0,
            func.json_array_length(Specification.unresolved_requirement_refs) == 0,
            func.json_array_length(Specification.required_evidence) > 0, Specification.overall_expected_result.is_not(None),
            receipt, known_link)

    def _coverage(self, project_id, campaign_id):
        grouped = select(Link.requirement_id.label("requirement_id"), func.count().label("linked"),
            func.sum(case((self._eligible_spec(), 1), else_=0)).label("approved")).join(Specification,
                and_(Specification.id == Link.test_spec_id, Specification.project_id == Link.project_id,
                    Specification.campaign_id == Link.campaign_id)).where(self._scope(Link, project_id, campaign_id)).group_by(Link.requirement_id).subquery()
        return select(Requirement.id.label("requirement_id"), Requirement.review_status,
            func.coalesce(grouped.c.linked, 0).label("linked"), func.coalesce(grouped.c.approved, 0).label("approved"))            .outerjoin(grouped, grouped.c.requirement_id == Requirement.id).where(self._scope(Requirement, project_id, campaign_id))

    def traceability(self, project_id, campaign_id, limit):
        if type(limit) is not int or not 1 <= limit <= 200: raise ValueError("Invalid trace limit")
        rows = self.session.execute(self._coverage(project_id, campaign_id).order_by(Requirement.id).limit(limit + 1)).mappings().all()
        ids = [r["requirement_id"] for r in rows[:limit]]
        states = {id: {} for id in ids}
        # At most four persisted statuses per selected requirement, not raw test bodies.
        if ids:
            grouped = self.session.execute(select(Link.requirement_id, Specification.review_status, func.count())
                .join(Specification, Specification.id == Link.test_spec_id)
                .where(self._scope(Link, project_id, campaign_id), Link.requirement_id.in_(ids))
                .group_by(Link.requirement_id, Specification.review_status).limit(limit * 4 + 1)).all()
            if len(grouped) > limit * 4: raise ValueError("Stored review status limit")
            for id, status, count in grouped: states[id][status] = count
        requirements = tuple(RequirementTrace(requirement_id=r["requirement_id"], review_status=r["review_status"],
            linked_test_count=r["linked"], approved_test_count=r["approved"], linked_test_review_states=states[r["requirement_id"]],
            coverage=coverage(r["linked"], r["approved"])) for r in rows[:limit])
        links = self.session.execute(select(Link.requirement_id, Link.test_spec_id, Specification.review_status.label("test_review_status"))
            .join(Specification, Specification.id == Link.test_spec_id).where(self._scope(Link, project_id, campaign_id))
            .order_by(Link.requirement_id, Link.test_spec_id).limit(limit + 1)).mappings().all()
        return requirements, len(rows) > limit, tuple(TraceLink.model_validate(dict(r)) for r in links[:limit]), len(links) > limit

    def readiness_counts(self, project_id, campaign_id):
        def count(table, *conditions):
            return self.session.scalar(select(func.count()).select_from(table).where(self._scope(table, project_id, campaign_id), *conditions))
        req_receipt = select(RequirementReviewRow.object_id).where(RequirementReviewRow.object_id == Requirement.id,
            RequirementReviewRow.project_id == Requirement.project_id, RequirementReviewRow.campaign_id == Requirement.campaign_id).correlate(Requirement).exists()
        valid_req = and_(req_receipt, func.json_array_length(Requirement.information_markers) == 0,
            func.json_array_length(Requirement.acceptance_criteria) > 0, func.json_array_length(Requirement.source_references) > 0)
        req_approved = count(Requirement, Requirement.review_status == "APPROVED")
        test_approved = count(Specification, Specification.review_status == "APPROVED")
        traced = self._coverage(project_id, campaign_id).subquery()
        covered, partial, uncovered = self.session.execute(select(
            func.coalesce(func.sum(case((traced.c.approved > 0, 1), else_=0)), 0),
            func.coalesce(func.sum(case((and_(traced.c.linked > 0, traced.c.approved == 0), 1), else_=0)), 0),
            func.coalesce(func.sum(case((traced.c.linked == 0, 1), else_=0)), 0))).one()
        return dict(total_requirements=count(Requirement), approved_requirements=req_approved,
            clarification_requirements=count(Requirement, Requirement.review_status == "NEEDS_CLARIFICATION"),
            total_test_specifications=count(Specification), approved_test_specifications=test_approved,
            covered_requirements=covered, partial_requirements=partial, uncovered_requirements=uncovered,
            invalid_approved_requirements=req_approved - count(Requirement, Requirement.review_status == "APPROVED", valid_req),
            invalid_approved_test_specifications=test_approved - count(Specification, self._eligible_spec()))
