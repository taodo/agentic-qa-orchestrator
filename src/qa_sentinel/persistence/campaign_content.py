"""Immutable source/requirement snapshots and bounded extraction reservations."""
from sqlalchemy import select, func
from qa_sentinel.domain.campaign_content import CampaignSource, CampaignRequirement, RequirementExtraction, Clarification, validate_citations, extraction_retryable
from .models import CampaignSourceRow, CampaignRequirementRow, RequirementExtractionRow, ClarificationRow, RequirementRevisionRow
from .preparation_current import current_requirement


def source_from(row):
    return CampaignSource.model_validate({name: getattr(row, name) for name in CampaignSource.model_fields})


def extraction_from(row):
    return RequirementExtraction.model_validate({name: getattr(row, "metadata_json" if name == "metadata" else name)
        for name in RequirementExtraction.model_fields})


def requirement_from(row):
    return CampaignRequirement.model_validate({name: getattr(row, name) for name in CampaignRequirement.model_fields})


def row_values(record):
    values = record.model_dump(mode="json")
    for name in ("created_at", "updated_at", "started_at", "finished_at"):
        if name in values: values[name] = getattr(record, name)
    return values


class CampaignContentRepository:
    def __init__(self, session):
        self.session = session

    def source(self, source_id):
        row = self.session.get(CampaignSourceRow, str(source_id))
        return None if row is None else source_from(row)

    def source_by_content(self, source):
        row = self.session.scalar(select(CampaignSourceRow).where(
            CampaignSourceRow.campaign_id == str(source.campaign_id), CampaignSourceRow.source_type == source.source_type.value,
            CampaignSourceRow.content_hash == source.content_hash, CampaignSourceRow.normalization_version == source.normalization_version))
        return None if row is None else source_from(row)

    def add_source(self, source):
        source = CampaignSource.model_validate(source.model_dump())
        self.session.add(CampaignSourceRow(**row_values(source)))
        self.session.flush()

    def extraction_for_source(self, source_id, *, latest=False):
        row = self.session.scalar(select(RequirementExtractionRow).where(RequirementExtractionRow.source_id == str(source_id)).order_by(RequirementExtractionRow.attempt_number.desc() if latest else RequirementExtractionRow.attempt_number).limit(1))
        return None if row is None else extraction_from(row)

    def reserve(self, extraction):
        extraction = RequirementExtraction.model_validate(extraction.model_dump())
        if extraction.status != "STARTED": raise ValueError("Reserve only STARTED")
        source = self.source(extraction.source_id)
        if source is None or source.status != "INGESTED" or source.content_hash != extraction.source_hash:
            raise ValueError("Extraction requires its immutable ingested source")
        if extraction.parent_attempt_id is not None:
            parent = self.attempt(extraction.parent_attempt_id)
            if parent is None or not extraction_retryable(parent) or parent.source_id != extraction.source_id or parent.attempt_number + 1 != extraction.attempt_number:
                raise ValueError("Invalid retry ancestry")
        values = row_values(extraction); values["metadata_json"] = values.pop("metadata")
        self.session.add(RequirementExtractionRow(**values)); self.session.flush()

    def finish(self, extraction, requirements=()):
        extraction = RequirementExtraction.model_validate(extraction.model_dump())
        row = self.session.get(RequirementExtractionRow, str(extraction.id))
        if row is None or row.status != "STARTED" or extraction.status == "STARTED":
            raise ValueError("Extraction cannot be replayed")
        old = extraction_from(row)
        for name in ("id", "project_id", "campaign_id", "source_id", "source_hash", "contract_version", "agent", "model", "started_at", "attempt_number", "parent_attempt_id"):
            if getattr(old, name) != getattr(extraction, name): raise ValueError("Extraction identity is immutable")
        if extraction.status != "SUCCEEDED" and requirements: raise ValueError("Failed extraction cannot produce requirements")
        source = self.source(extraction.source_id)
        prepared = [CampaignRequirement.model_validate(r.model_dump()) for r in requirements]
        if len(prepared) > 100: raise ValueError("Requirement output limit")
        validate_citations(source, prepared)
        for requirement in prepared:
            if requirement.review_status == "APPROVED": raise ValueError("Extraction cannot approve requirements")
            if (requirement.project_id, requirement.campaign_id, requirement.extraction_id) != (old.project_id, old.campaign_id, old.id):
                raise ValueError("Requirement ownership mismatch")
        clarification = self.clarification_for_source(source.id)
        if clarification is not None and extraction.status == "SUCCEEDED":
            previous = self.requirement(clarification.requirement_id)
            version = self.version(previous.id) + 1
            if not self.is_current(previous.id) or version > 10 or len(prepared) != 1 or prepared[0].key != previous.key:
                raise ValueError("Invalid requirement revision")
            if not any(ref.start_line >= clarification.first_fact_line for ref in prepared[0].source_references):
                raise ValueError("EXTRACTION_INVALID_CITATION")
        for requirement in prepared:
            self.session.add(CampaignRequirementRow(**row_values(requirement)))
        if clarification is not None and extraction.status == "SUCCEEDED":
            self.session.add(RequirementRevisionRow(requirement_id=str(prepared[0].id), project_id=str(old.project_id),
                campaign_id=str(old.campaign_id), supersedes_id=str(previous.id), clarification_id=str(clarification.id), version=version))
        row.status, row.finished_at, row.error_code = extraction.status.value, extraction.finished_at, extraction.error_code
        row.metadata_json = None if extraction.metadata is None else extraction.metadata.model_dump(mode="json")
        self.session.flush()

    def requirement(self, requirement_id):
        row = self.session.get(CampaignRequirementRow, str(requirement_id))
        return None if row is None else requirement_from(row)

    @staticmethod
    def _limit(limit):
        if type(limit) is not int or not 1 <= limit <= 200: raise ValueError("Invalid content list limit")
        return limit + 1

    def sources(self, campaign_id, limit):
        columns = [c for c in CampaignSourceRow.__table__.c if c.name != "normalized_text"]
        return list(self.session.execute(select(*columns).where(CampaignSourceRow.campaign_id == str(campaign_id))
            .order_by(func.qa_utc_microseconds(CampaignSourceRow.created_at).desc(), CampaignSourceRow.id)
            .limit(self._limit(limit))).mappings())

    def requirements(self, campaign_id, limit):
        rows = self.session.scalars(select(CampaignRequirementRow).where(CampaignRequirementRow.campaign_id == str(campaign_id), current_requirement())
            .order_by(func.qa_utc_microseconds(CampaignRequirementRow.created_at), CampaignRequirementRow.logical_key)
            .limit(self._limit(limit)))
        return [requirement_from(row) for row in rows]

    def extractions(self, campaign_id, limit):
        rows = self.session.scalars(select(RequirementExtractionRow).where(RequirementExtractionRow.campaign_id == str(campaign_id))
            .order_by(func.qa_utc_microseconds(RequirementExtractionRow.started_at), RequirementExtractionRow.id)
            .limit(self._limit(limit)))
        return [extraction_from(row) for row in rows]


    def attempt(self, id):
        row = self.session.get(RequirementExtractionRow, str(id))
        return None if row is None else extraction_from(row)

    def retry_child(self, parent_id):
        row = self.session.scalar(select(RequirementExtractionRow).where(RequirementExtractionRow.parent_attempt_id == str(parent_id)))
        return None if row is None else extraction_from(row)

    def attempt_history(self, source_id, limit):
        return [extraction_from(r) for r in self.session.scalars(select(RequirementExtractionRow).where(
            RequirementExtractionRow.source_id == str(source_id)).order_by(RequirementExtractionRow.attempt_number.desc()).limit(self._limit(limit)))]

    def latest_attempts(self, source_ids):
        latest = select(RequirementExtractionRow.source_id, func.max(RequirementExtractionRow.attempt_number).label("number")).where(
            RequirementExtractionRow.source_id.in_([str(id) for id in source_ids])).group_by(RequirementExtractionRow.source_id).subquery()
        return {r.source_id: extraction_from(r) for r in self.session.scalars(select(RequirementExtractionRow).join(latest,
            (RequirementExtractionRow.source_id == latest.c.source_id) & (RequirementExtractionRow.attempt_number == latest.c.number)).limit(len(source_ids)))}

    def clarification_targets(self, source_ids):
        rows = self.session.execute(select(ClarificationRow.source_id, ClarificationRow.requirement_id).where(
            ClarificationRow.source_id.in_([str(id) for id in source_ids])).limit(len(source_ids)))
        return {source_id: requirement_id for source_id, requirement_id in rows}

    def clarification_for_source(self, source_id):
        row = self.session.scalar(select(ClarificationRow).where(ClarificationRow.source_id == str(source_id)))
        return None if row is None else Clarification.model_validate({name:getattr(row,name) for name in Clarification.model_fields})

    def clarification_by_key(self, campaign_id, key):
        row = self.session.scalar(select(ClarificationRow).where(ClarificationRow.campaign_id == str(campaign_id), ClarificationRow.request_key == key))
        return None if row is None else Clarification.model_validate({name:getattr(row,name) for name in Clarification.model_fields})

    def add_clarification(self, record):
        self.session.add(ClarificationRow(**row_values(record)))
        self.session.flush()

    def is_current(self, id):
        return self.session.scalar(select(CampaignRequirementRow.id).where(CampaignRequirementRow.id == str(id), current_requirement())) is not None

    def version(self, id):
        row = self.session.get(RequirementRevisionRow, str(id))
        return 1 if row is None else row.version

    def revision_history(self, id):
        # A chain is limited to ten immutable versions, with no body fan-out elsewhere.
        root = str(id)
        for _ in range(10):
            row = self.session.get(RequirementRevisionRow, root)
            if row is None: break
            root = row.supersedes_id
        records = []
        for _ in range(10):
            record = self.requirement(root)
            revision = self.session.get(RequirementRevisionRow, root)
            successor = self.session.scalar(select(RequirementRevisionRow).where(RequirementRevisionRow.supersedes_id == root))
            records.append(dict(requirement=record.model_dump(), version=1 if revision is None else revision.version,
                is_current=successor is None, supersedes_id=None if revision is None else revision.supersedes_id))
            if successor is None: return records
            root = successor.requirement_id
        raise ValueError("Revision chain exceeds bound")

    def active_revision(self, requirement_id):
        return self.session.scalar(select(RequirementExtractionRow.id).join(ClarificationRow, ClarificationRow.source_id == RequirementExtractionRow.source_id).where(
            ClarificationRow.requirement_id == str(requirement_id), RequirementExtractionRow.status == "STARTED").limit(1)) is not None
