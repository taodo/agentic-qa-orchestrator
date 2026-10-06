from pydantic import BaseModel, ConfigDict
from qa_sentinel.domain.enums import PlannerDecision
from qa_sentinel.domain.types import NonBlank


class ImplementationStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: NonBlank
    description: NonBlank
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
    implementation_steps: tuple[ImplementationStep, ...]
    files_to_create: tuple[NonBlank, ...]
    files_to_modify: tuple[NonBlank, ...]
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    test_strategy: tuple[TestStrategyItem, ...]
    risks: tuple[NonBlank, ...]
    rollback_considerations: tuple[NonBlank, ...]
    open_questions: tuple[NonBlank, ...]
