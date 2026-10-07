"""Executor-neutral immutable test design and provenance contracts."""
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4
from pydantic import Field, StringConstraints, AwareDatetime, model_validator
from .campaign_content import Frozen, Name, Description, ShortText, Hash, Key, ExtractionStatus
from qa_sentinel.models.base import ModelMetadata

Ref=Annotated[str,StringConstraints(strict=True,strip_whitespace=True,min_length=1,max_length=128)]
StepText=Annotated[str,StringConstraints(strict=True,strip_whitespace=True,min_length=1,max_length=2000)]

class TestType(StrEnum):
    FUNCTIONAL='FUNCTIONAL'
    REGRESSION='REGRESSION'
    SMOKE='SMOKE'
    NEGATIVE='NEGATIVE'
    BOUNDARY='BOUNDARY'
    INTEGRATION='INTEGRATION'
    API='API'
    WEB='WEB'
    DATA='DATA'
    OTHER='OTHER'

class Priority(StrEnum):
    LOW='LOW'
    MEDIUM='MEDIUM'
    HIGH='HIGH'
    CRITICAL='CRITICAL'

class TestReviewStatus(StrEnum):
    DRAFT='DRAFT'
    NEEDS_CLARIFICATION='NEEDS_CLARIFICATION'
    READY_FOR_REVIEW='READY_FOR_REVIEW'
    APPROVED='APPROVED'

class TestMarker(Frozen):
    kind:Literal['AMBIGUITY','MISSING_INFORMATION','UNRESOLVED_REQUIREMENT','MISSING_TRACEABILITY']
    description:ShortText

class TestStep(Frozen):
    index:int=Field(ge=1,le=20,strict=True)
    action:StepText
    expected:StepText | None

class TestDesign(Frozen):
    key:Key
    title:Name
    test_type:TestType
    priority:Priority
    preconditions:tuple[ShortText,...]=Field(max_length=20)
    steps:tuple[TestStep,...]=Field(min_length=1,max_length=20)
    overall_expected_result:Description | None
    required_evidence:tuple[ShortText,...]=Field(max_length=20)
    information_markers:tuple[TestMarker,...]=Field(max_length=20)

    @model_validator(mode='after')
    def ordered_and_honest(self):
        if [s.index for s in self.steps]!=list(range(1,len(self.steps)+1)):
            raise ValueError('Steps must have contiguous one-based order')
        missing=any(s.expected is None for s in self.steps) or self.overall_expected_result is None or not self.required_evidence
        if missing and not any(m.kind=='MISSING_INFORMATION' for m in self.information_markers):
            raise ValueError('Missing expected behavior/evidence must be explicit')
        return self

class ImportedTest(TestDesign):
    requirement_refs:tuple[Ref,...]=Field(max_length=20)

class GeneratedTest(TestDesign):
    requirement_ids:tuple[UUID,...]=Field(min_length=1,max_length=20)

    @model_validator(mode='after')
    def unique_links(self):
        if len(set(self.requirement_ids))!=len(self.requirement_ids):raise ValueError('Duplicate requirement link')
        return self

class ImportFormat(StrEnum):
    CSV='CSV'
    MARKDOWN='MARKDOWN'
    XLSX='XLSX'

class ImportStatus(StrEnum):
    IMPORTED='IMPORTED'
    REJECTED='REJECTED'

class TestImport(Frozen):
    id:UUID=Field(default_factory=uuid4)
    project_id:UUID
    campaign_id:UUID
    name:Name
    format:ImportFormat
    raw_hash:Hash
    content_hash:Hash
    contract_version:Literal['test-import-v1']='test-import-v1'
    normalization_version:Literal['utf8-nfc-lf-v1']='utf8-nfc-lf-v1'
    original_bytes:int=Field(ge=0,le=65536,strict=True)
    normalized_text:str | None=Field(default=None,max_length=65536)
    status:ImportStatus
    error_code:Literal['XLSX_UNSUPPORTED','IMPORT_INVALID_UTF8','IMPORT_BINARY_TEXT','IMPORT_INVALID_SCHEMA','IMPORT_DUPLICATE_KEY','IMPORT_CASE_LIMIT','IMPORT_LINE_LIMIT'] | None
    test_count:int=Field(ge=0,le=100,strict=True)
    created_at:AwareDatetime=Field(default_factory=lambda:datetime.now(timezone.utc))

    @model_validator(mode='after')
    def honest_result(self):
        from hashlib import sha256
        if self.status==ImportStatus.IMPORTED:
            if self.format==ImportFormat.XLSX or self.normalized_text is None or self.error_code or not self.test_count:
                raise ValueError('Invalid import result')
            if sha256(self.normalized_text.encode('utf-8')).hexdigest()!=self.content_hash:raise ValueError('Import hash mismatch')
        elif self.test_count or self.normalized_text is not None or self.error_code is None:
            raise ValueError('Rejected import cannot contain successful text/tests')
        return self

class RequirementVersion(Frozen):
    id:UUID
    snapshot_hash:Hash

class TestGeneration(Frozen):
    id:UUID=Field(default_factory=uuid4)
    project_id:UUID
    campaign_id:UUID
    request_hash:Hash
    contract_version:Literal['test-specs-v1']='test-specs-v1'
    requirement_versions:tuple[RequirementVersion,...]=Field(min_length=1,max_length=20)
    agent:Literal['PLANNER']='PLANNER'
    model:Ref
    status:ExtractionStatus=ExtractionStatus.STARTED
    started_at:AwareDatetime=Field(default_factory=lambda:datetime.now(timezone.utc))
    finished_at:AwareDatetime | None=None
    error_code:Annotated[str,StringConstraints(pattern=r'^(MODEL_[A-Z_]+|GENERATION_INVALID_OUTPUT|GENERATION_INVALID_LINK)$')] | None=None
    metadata:ModelMetadata | None=None

    @model_validator(mode='after')
    def lifecycle(self):
        ids=[str(r.id) for r in self.requirement_versions]
        if ids!=sorted(set(ids)):raise ValueError('Selection must be canonical and unique')
        if self.status==ExtractionStatus.STARTED:
            if self.finished_at or self.error_code or self.metadata:raise ValueError('Started cannot claim completion')
        elif self.finished_at is None or ((self.status==ExtractionStatus.FAILED)!=(self.error_code is not None)):
            raise ValueError('Invalid generation completion')
        return self

class TestProvenance(Frozen):
    origin:Literal['IMPORT','AI_GENERATED']
    record_id:UUID
    content_hash:Hash
    contract_version:Literal['test-import-v1','test-specs-v1']
    start_line:int | None=Field(default=None,ge=1,le=4096,strict=True)
    end_line:int | None=Field(default=None,ge=1,le=4096,strict=True)

    @model_validator(mode='after')
    def locations(self):
        if self.origin=='IMPORT':
            if self.contract_version!='test-import-v1' or self.start_line is None or self.end_line is None or self.start_line>self.end_line:
                raise ValueError('Import provenance requires ordered line locations')
        elif self.contract_version!='test-specs-v1' or self.start_line is not None or self.end_line is not None:
            raise ValueError('Generation provenance cannot claim imported locations')
        return self

class CampaignTestSpecification(TestDesign):
    id:UUID=Field(default_factory=uuid4)
    project_id:UUID
    campaign_id:UUID
    logical_key:Ref
    requirement_ids:tuple[UUID,...]=Field(max_length=20)
    unresolved_requirement_refs:tuple[Ref,...]=Field(max_length=20)
    provenance:TestProvenance
    review_status:TestReviewStatus
    created_at:AwareDatetime=Field(default_factory=lambda:datetime.now(timezone.utc))
    updated_at:AwareDatetime=Field(default_factory=lambda:datetime.now(timezone.utc))

    @model_validator(mode='after')
    def traceability_review(self):
        if len(set(self.requirement_ids))!=len(self.requirement_ids):raise ValueError('Duplicate link')
        if self.provenance.origin=='AI_GENERATED' and (not self.requirement_ids or self.unresolved_requirement_refs):
            raise ValueError('AI generation requires known links')
        if not self.requirement_ids and not any(m.kind=='MISSING_TRACEABILITY' for m in self.information_markers):
            raise ValueError('Unlinked import requires explicit traceability marker')
        if self.unresolved_requirement_refs and not any(m.kind=='UNRESOLVED_REQUIREMENT' for m in self.information_markers):
            raise ValueError('Unknown references must be explicit')
        if self.information_markers and self.review_status!=TestReviewStatus.NEEDS_CLARIFICATION:
            raise ValueError('Unresolved information requires clarification')
        return self
