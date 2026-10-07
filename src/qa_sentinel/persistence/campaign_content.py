"""Immutable source/requirement snapshots and single-attempt extraction reservations."""
from sqlalchemy import select, func
from qa_sentinel.domain.campaign_content import CampaignSource, CampaignRequirement, RequirementExtraction, validate_citations
from .models import CampaignSourceRow, CampaignRequirementRow, RequirementExtractionRow


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

    def extraction_for_source(self, source_id):
        row = self.session.scalar(select(RequirementExtractionRow).where(RequirementExtractionRow.source_id == str(source_id)))
        return None if row is None else extraction_from(row)

    def reserve(self, extraction):
        extraction = RequirementExtraction.model_validate(extraction.model_dump())
        if extraction.status != "STARTED": raise ValueError("Reserve only STARTED")
        source = self.source(extraction.source_id)
        if source is None or source.status != "INGESTED" or source.content_hash != extraction.source_hash:
            raise ValueError("Extraction requires its immutable ingested source")
        values = row_values(extraction); values["metadata_json"] = values.pop("metadata")
        self.session.add(RequirementExtractionRow(**values)); self.session.flush()

    def finish(self, extraction, requirements=()):
        extraction = RequirementExtraction.model_validate(extraction.model_dump())
        row = self.session.get(RequirementExtractionRow, str(extraction.id))
        if row is None or row.status != "STARTED" or extraction.status == "STARTED":
            raise ValueError("Extraction cannot be replayed")
        old = extraction_from(row)
        for name in ("id", "project_id", "campaign_id", "source_id", "source_hash", "contract_version", "agent", "model", "started_at"):
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
        for requirement in prepared:
            self.session.add(CampaignRequirementRow(**row_values(requirement)))
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
        rows = self.session.scalars(select(CampaignRequirementRow).where(CampaignRequirementRow.campaign_id == str(campaign_id))
            .order_by(func.qa_utc_microseconds(CampaignRequirementRow.created_at), CampaignRequirementRow.logical_key)
            .limit(self._limit(limit)))
        return [requirement_from(row) for row in rows]

    def extractions(self, campaign_id, limit):
        rows = self.session.scalars(select(RequirementExtractionRow).where(RequirementExtractionRow.campaign_id == str(campaign_id))
            .order_by(func.qa_utc_microseconds(RequirementExtractionRow.started_at), RequirementExtractionRow.id)
            .limit(self._limit(limit)))
        return [extraction_from(row) for row in rows]
