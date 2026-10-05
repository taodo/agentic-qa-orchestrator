from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field
from qa_sentinel.domain.enums import PlannerDecision
from qa_sentinel.domain.types import NonBlank


class ImplementationStepKind(StrEnum):
    CODE_CHANGE = "CODE_CHANGE"
    STATIC_REVIEW = "STATIC_REVIEW"
    TEST_EXECUTION = "TEST_EXECUTION"


class ImplementationStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: NonBlank
    description: NonBlank = Field(description="Work performable or source-attestable during IMPLEMENTING; never executable verification")
    # Legacy persisted plans omit kind. Strict provider schemas require it on new output.
    kind: ImplementationStepKind = Field(default_factory=lambda: ImplementationStepKind.CODE_CHANGE,
        description="Declare CODE_CHANGE for source/test-file edits or STATIC_REVIEW for source-based checks; STATIC_REVIEW files alone authorize only source visibility, not writes. TEST_EXECUTION belongs to test_strategy/TESTING and is rejected by PlanGate")
    files: tuple[NonBlank, ...]
    depends_on: tuple[NonBlank, ...]


class AcceptanceCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: NonBlank
    description: NonBlank
    verification: NonBlank

class TestStrategyItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    description: NonBlank
    acceptance_criteria_refs: tuple[NonBlank, ...]

class PlannerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: PlannerDecision
    summary: NonBlank
    assumptions: tuple[NonBlank, ...]
    implementation_steps: tuple[ImplementationStep, ...] = Field(
        description="Required IMPLEMENTING work only: authorized code changes or source-based review. Do not duplicate executable verification here")
    files_to_create: tuple[NonBlank, ...]
    files_to_modify: tuple[NonBlank, ...]
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    test_strategy: tuple[TestStrategyItem, ...] = Field(
        description="Executable verification owned by TESTING through the approved deterministic pytest runner, with acceptance criterion references")
    risks: tuple[NonBlank, ...]
    rollback_considerations: tuple[NonBlank, ...]
    open_questions: tuple[NonBlank, ...]


def modification_paths(plan: PlannerOutput) -> set[str]:
    """Declared write scope shared by prompt projection and deterministic policy.

    Legacy steps load as CODE_CHANGE. Review-only visibility grants no writes;
    explicit files_to_modify or an independent CODE_CHANGE step still may.
    Workspace containment, limits and freshness remain MutationPolicy's job.
    """
    return set(plan.files_to_modify) | {
        path for step in plan.implementation_steps
        if step.kind == ImplementationStepKind.CODE_CHANGE for path in step.files
    }
