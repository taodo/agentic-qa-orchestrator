"""Detached import/design/generation views and deterministic canonicalization."""
from uuid import UUID,uuid5,NAMESPACE_URL
from datetime import datetime
from typing import Literal
from qa_sentinel.domain.test_specification import (TestImport,ImportFormat,ImportStatus,CampaignTestSpecification,
    TestGeneration,TestMarker,TestProvenance,RequirementVersion)
from qa_sentinel.domain.campaign_content import ExtractionStatus
from qa_sentinel.models.base import ContextSelection
from .models import View
from .ai_action_results import ActionOutput
from .model_usage import UsageTotals,totals,safe_metadata

class TestImportView(View):
    id:UUID
    project_id:UUID
    campaign_id:UUID
    name:str
    format:ImportFormat
    raw_hash:str
    content_hash:str
    contract_version:str
    normalization_version:str
    original_bytes:int
    status:ImportStatus
    error_code:str | None
    test_count:int
    created_at:datetime

class TestImportDetail(TestImportView):
    normalized_text:str | None

class TestSpecificationView(CampaignTestSpecification):pass

class TestGenerationView(View):
    id:UUID
    project_id:UUID
    campaign_id:UUID
    request_hash:str
    contract_version:str
    requirement_versions:tuple[RequirementVersion,...]
    purpose:Literal['TEST_SPEC_GENERATION']='TEST_SPEC_GENERATION'
    agent:str
    configured_model:str
    provider_model:str | None
    status:ExtractionStatus
    started_at:datetime
    finished_at:datetime | None
    error_code:str | None
    usage:UsageTotals
    context_selection:ContextSelection | None

    provider: str | None = None
    output: ActionOutput | None = None


def generation_view(record, *, output=None):
    metadata=None if record.metadata is None else safe_metadata(record.metadata.model_dump(mode='json'))
    fields=record.model_dump(include=set(TestGenerationView.model_fields))
    return TestGenerationView(**fields,output=output,provider=None if metadata is None else metadata["provider"],configured_model=record.model,provider_model=None if metadata is None else metadata['model'],
        usage=totals([metadata]),context_selection=None if record.metadata is None else record.metadata.context_selection)


def markers_union(*groups):
    # Reuse identical typed clarification facts; do not truncate distinct required markers.
    markers={ (m.kind,m.description):m for group in groups for m in group }
    return tuple(markers[key] for key in sorted(markers))


def canonical_spec(owner,case,requirement_ids,unresolved=(),markers=(),start=None,end=None):
    origin='IMPORT' if isinstance(owner,TestImport) else 'AI_GENERATED'
    values=case.model_dump(exclude={'requirement_ids','requirement_refs','information_markers'})
    all_markers=markers_union(case.information_markers,markers)
    return CampaignTestSpecification(**values,id=uuid5(NAMESPACE_URL,f'{owner.id}:{owner.contract_version}:{case.key}'),
        project_id=owner.project_id,campaign_id=owner.campaign_id,logical_key=f'TEST-{owner.id.hex}-{case.key}',
        requirement_ids=tuple(sorted(set(requirement_ids),key=str)),unresolved_requirement_refs=tuple(sorted(set(unresolved))),
        information_markers=all_markers,review_status='NEEDS_CLARIFICATION' if all_markers else 'READY_FOR_REVIEW',
        provenance=TestProvenance(origin=origin,record_id=owner.id,
            content_hash=owner.content_hash if isinstance(owner,TestImport) else owner.request_hash,
            contract_version=owner.contract_version,start_line=start,end_line=end))
