"""Immutable specification snapshots and extracted facts, independent of Tasks."""
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, AwareDatetime, model_validator
from qa_sentinel.models.base import ModelMetadata

Name = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=4000)]
ShortText = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=512)]
Hash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$", strict=True)]
Key = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9_-]{0,63}$", strict=True)]
Line = Annotated[int, Field(ge=1, le=4096, strict=True)]


class Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceType(StrEnum):
    TEXT = "TEXT"
    MARKDOWN = "MARKDOWN"
    PDF = "PDF"


class IngestionStatus(StrEnum):
    INGESTED = "INGESTED"
    REJECTED = "REJECTED"


class ParseError(StrEnum):
    PDF_UNSUPPORTED = "PDF_UNSUPPORTED"
    INVALID_UTF8 = "INVALID_UTF8"
    BINARY_TEXT = "BINARY_TEXT"
    EMPTY_TEXT = "EMPTY_TEXT"
    SOURCE_LINE_LIMIT = "SOURCE_LINE_LIMIT"


class CampaignSource(Frozen):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    campaign_id: UUID
    source_type: SourceType
    name: Name
    content_hash: Hash
    raw_hash: Hash
    normalization_version: Literal["utf8-nfc-lf-v1"] = "utf8-nfc-lf-v1"
    original_bytes: int = Field(ge=0, le=65536, strict=True)
    normalized_chars: int = Field(ge=0, le=65536, strict=True)
    line_count: int = Field(ge=0, le=4096, strict=True)
    status: IngestionStatus
    normalized_text: str | None = Field(default=None, max_length=65536)
    error_code: ParseError | None = None
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def valid_snapshot(self):
        from hashlib import sha256
        if self.status == IngestionStatus.INGESTED:
            if self.source_type == SourceType.PDF or self.normalized_text is None or self.error_code is not None or not self.normalized_text.strip():
                raise ValueError("Invalid ingested snapshot")
            if self.normalized_chars != len(self.normalized_text) or self.line_count != len(self.normalized_text.split("\n")):
                raise ValueError("Source location metadata mismatch")
            if sha256(self.normalized_text.encode("utf-8")).hexdigest() != self.content_hash:
                raise ValueError("Source identity mismatch")
        elif self.normalized_text is not None or self.error_code is None or self.normalized_chars or self.line_count:
            raise ValueError("Rejected source cannot claim parsed text")
        return self


class AcceptanceCriterion(Frozen):
    key: Key
    text: Description


class InformationMarker(Frozen):
    kind: Literal["AMBIGUITY", "MISSING_INFORMATION"]
    description: ShortText


class SourceCitation(Frozen):
    source_id: UUID
    source_hash: Hash
    location_type: Literal["LINES"] = "LINES"
    start_line: Line
    end_line: Line
    excerpt: ShortText

    @model_validator(mode="after")
    def ordered_range(self):
        if self.end_line < self.start_line:
            raise ValueError("Invalid source range")
        return self


class RequirementDraft(Frozen):
    key: Key
    title: Name
    description: Description
    acceptance_criteria: tuple[AcceptanceCriterion, ...] = Field(max_length=20)
    source_references: tuple[SourceCitation, ...] = Field(min_length=1, max_length=8)
    information_markers: tuple[InformationMarker, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def explicit_missing_information(self):
        keys = [item.key for item in self.acceptance_criteria]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate criterion key")
        if not keys and not any(m.kind == "MISSING_INFORMATION" for m in self.information_markers):
            raise ValueError("Missing criteria must be explicit")
        return self


class RequirementReviewStatus(StrEnum):
    DRAFT = "DRAFT"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"


class CampaignRequirement(RequirementDraft):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    campaign_id: UUID
    extraction_id: UUID
    logical_key: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
    review_status: RequirementReviewStatus
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def review_semantics(self):
        if self.information_markers and self.review_status != RequirementReviewStatus.NEEDS_CLARIFICATION:
            raise ValueError("Unresolved information requires clarification")
        return self


class ExtractionStatus(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class RequirementExtraction(Frozen):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    campaign_id: UUID
    source_id: UUID
    source_hash: Hash
    attempt_number: int = Field(default=1, ge=1, le=3, strict=True)
    parent_attempt_id: UUID | None = None
    contract_version: Literal["requirements-v1"] = "requirements-v1"
    agent: Literal["RESEARCHER"] = "RESEARCHER"
    model: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    status: ExtractionStatus = ExtractionStatus.STARTED
    started_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: AwareDatetime | None = None
    error_code: Annotated[str, StringConstraints(pattern=r"^(MODEL_[A-Z_]+|EXTRACTION_INVALID_OUTPUT|EXTRACTION_INVALID_CITATION)$")] | None = None
    metadata: ModelMetadata | None = None

    @model_validator(mode="after")
    def lifecycle(self):
        if (self.attempt_number == 1) != (self.parent_attempt_id is None):
            raise ValueError("Invalid extraction ancestry")
        if self.status == ExtractionStatus.STARTED:
            if self.finished_at is not None or self.error_code is not None or self.metadata is not None:
                raise ValueError("Started extraction cannot claim completion")
        elif self.finished_at is None or ((self.status == ExtractionStatus.FAILED) != (self.error_code is not None)):
            raise ValueError("Invalid extraction completion")
        return self


def validate_citations(source, requirements):
    lines = source.normalized_text.split("\n")
    for requirement in requirements:
        for ref in requirement.source_references:
            if ref.source_id != source.id or ref.source_hash != source.content_hash or ref.end_line > source.line_count:
                raise ValueError("EXTRACTION_INVALID_CITATION")
            if ref.excerpt not in "\n".join(lines[ref.start_line-1:ref.end_line]):
                raise ValueError("EXTRACTION_INVALID_CITATION")


RETRYABLE_EXTRACTION_CODES = frozenset({
    "EXTRACTION_INVALID_CITATION", "EXTRACTION_INVALID_OUTPUT", "MODEL_RATE_LIMIT",
    "MODEL_TIMEOUT", "MODEL_CONNECTION", "MODEL_SERVER_ERROR",
    "MODEL_MALFORMED_RESPONSE", "MODEL_INCOMPLETE_RESPONSE",
})


def extraction_retryable(attempt):
    return attempt.status == "FAILED" and attempt.attempt_number < 3 and attempt.error_code in RETRYABLE_EXTRACTION_CODES


class Clarification(Frozen):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    campaign_id: UUID
    requirement_id: UUID
    source_id: UUID
    request_key: Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
    facts_hash: Hash
    first_fact_line: Line
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
