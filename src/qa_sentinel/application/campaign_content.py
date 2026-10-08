"""Detached content/extraction read models using Phase 1 token semantics."""
from datetime import datetime
from uuid import UUID
from typing import Literal
from qa_sentinel.domain.campaign_content import (SourceType, IngestionStatus, ParseError,
    CampaignRequirement, ExtractionStatus, extraction_retryable, Clarification)
from qa_sentinel.models.base import ContextSelection
from .test_specifications import TestGenerationView,generation_view
from qa_sentinel.domain.test_specification import TestGeneration
from .models import View
from .ai_action_results import ActionOutput
from .model_usage import UsageTotals, UsageGroup, totals, safe_metadata


class CampaignSourceView(View):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    source_type: SourceType
    name: str
    content_hash: str
    raw_hash: str
    normalization_version: str
    original_bytes: int
    normalized_chars: int
    line_count: int
    status: IngestionStatus
    error_code: ParseError | None
    created_at: datetime
    latest_extraction: "ExtractionView | None" = None
    clarification_requirement_id: UUID | None = None


class CampaignSourceDetail(CampaignSourceView):
    normalized_text: str | None


class CampaignRequirementView(CampaignRequirement):
    pass


class ExtractionView(View):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    source_id: UUID
    source_hash: str
    attempt_number: int
    parent_attempt_id: UUID | None
    retryable: bool
    is_latest: bool = True
    contract_version: str
    agent: str
    configured_model: str
    provider_model: str | None
    status: ExtractionStatus
    started_at: datetime
    finished_at: datetime | None
    error_code: str | None
    usage: UsageTotals
    context_selection: ContextSelection | None

    provider: str | None = None
    output: ActionOutput | None = None


def extraction_view(record, *, is_latest=True, output=None):
    metadata = None if record.metadata is None else safe_metadata(record.metadata.model_dump(mode="json"))
    fields = record.model_dump(include=set(ExtractionView.model_fields))
    return ExtractionView(**fields, output=output, provider=None if metadata is None else metadata["provider"], retryable=extraction_retryable(record), is_latest=is_latest, configured_model=record.model,
        provider_model=None if metadata is None else metadata["model"], usage=totals([metadata]),
        context_selection=None if record.metadata is None else record.metadata.context_selection)


class CampaignModelUsage(View):
    project_id: UUID
    campaign_id: UUID
    invocations: tuple[ExtractionView | TestGenerationView, ...]
    usage: UsageTotals
    by_agent: tuple[UsageGroup, ...]
    by_model: tuple[UsageGroup, ...]
    by_stage: tuple[UsageGroup, ...]
    top_invocations: tuple[UUID, ...]
    truncated: bool
    model_groups_truncated: bool
    cost_status: Literal["NOT_CONFIGURED"] = "NOT_CONFIGURED"
    estimated_cost: None = None


def campaign_usage(project_id, campaign_id, records, limit, *, latest_attempt_ids):
    from collections import defaultdict
    truncated = len(records) > limit
    selected = records[:limit]
    values = [None if r.metadata is None else safe_metadata(r.metadata.model_dump(mode="json")) for r in selected]
    models = defaultdict(list)
    for record, metadata in zip(selected, values):
        models[record.model if metadata is None else metadata["model"]].append(metadata)
    groups = sorted((UsageGroup(identity=name, usage=totals(items, incomplete=truncated)) for name, items in models.items()),
        key=lambda g: (-(g.usage.total_tokens.known_sum or 0), g.identity))
    rows = tuple(generation_view(r) if isinstance(r,TestGeneration) else extraction_view(r, is_latest=r.id in latest_attempt_ids) for r in selected)
    agents=defaultdict(list);purposes=defaultdict(list)
    for record,value in zip(selected,values):
        agents[record.agent].append(value)
        purposes["TEST_SPEC_GENERATION" if isinstance(record,TestGeneration) else "REQUIREMENT_EXTRACTION"].append(value)
    usage = totals(values, incomplete=truncated)
    return CampaignModelUsage(project_id=project_id, campaign_id=campaign_id, invocations=rows,
        usage=usage, by_agent=tuple(UsageGroup(identity=name,usage=totals(items,incomplete=truncated)) for name,items in sorted(agents.items())),
        by_stage=tuple(UsageGroup(identity=name,usage=totals(items,incomplete=truncated)) for name,items in sorted(purposes.items())),
        by_model=tuple(groups[:20]), model_groups_truncated=len(groups)>20, truncated=truncated,
        top_invocations=tuple(row.id for row in sorted((r for r in rows if r.usage.total_tokens.known_sum is not None),
            key=lambda r: (-(r.usage.total_tokens.known_sum or 0), str(r.id)))[:10]))


class ClarificationView(Clarification):
    pass


class RequirementHistoryEntry(View):
    requirement: CampaignRequirementView
    version: int
    is_current: bool
    supersedes_id: UUID | None

CampaignSourceView.model_rebuild()
CampaignSourceDetail.model_rebuild()
