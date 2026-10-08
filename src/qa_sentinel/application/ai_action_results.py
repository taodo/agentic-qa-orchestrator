"""Read-only action output facts; distributions describe immutable creation content."""
from typing import Literal
from uuid import UUID
from pydantic import Field
from .models import View


class RevisedRequirement(View):
    id: UUID
    key: str
    logical_key: str
    version: int = Field(ge=2, le=10)
    review_status: Literal["READY_FOR_REVIEW", "NEEDS_CLARIFICATION"]


class ActionOutput(View):
    generated_count: int = Field(ge=0, le=100)
    ready_for_review_count: int = Field(ge=0, le=100)
    needs_clarification_count: int = Field(ge=0, le=100)
    inherited_clarification_count: int | None = None
    revised_requirement: RevisedRequirement | None = None
