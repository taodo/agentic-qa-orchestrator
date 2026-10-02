"""Typed, bounded agent inputs and the model-independent runtime boundary."""
from types import MappingProxyType
from typing import Protocol
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from qa_sentinel.domain.enums import AgentName, ArtifactType, TaskState
from qa_sentinel.domain.types import NonBlank, Attempt, Count
from qa_sentinel.domain.test_run import TestRun
from qa_sentinel.schemas.research import ResearchOutput
from qa_sentinel.schemas.plan import PlannerOutput
from qa_sentinel.schemas.implementation import ImplementationOutput
from qa_sentinel.schemas.test_result import TestAnalysisOutput
from qa_sentinel.schemas.investigation import InvestigationOutput
from qa_sentinel.schemas.review import ReviewOutput
from qa_sentinel.models.base import ModelResponse
from qa_sentinel.schemas.mutation import SourceFileSnapshot
from qa_sentinel.schemas.repository import RepositoryEvidence

AgentOutput = ResearchOutput | PlannerOutput | ImplementationOutput | TestAnalysisOutput | InvestigationOutput | ReviewOutput


class RuntimeContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task_id: UUID
    attempt: Attempt
    evidence_refs: tuple[NonBlank, ...] = ()
    schema_correction: bool = False


class ResearchContext(RuntimeContext):
    requirement: NonBlank
    prior_research_ref: UUID | None = None
    repository_evidence: tuple[NonBlank, ...] = ()
    repository_results: tuple[RepositoryEvidence, ...] = ()


class PlanContext(RuntimeContext):
    requirement: NonBlank
    research: ResearchOutput
    research_artifact_id: UUID
    repository_results: tuple[RepositoryEvidence, ...] = ()


class ImplementationContext(RuntimeContext):
    plan: PlannerOutput
    plan_artifact_id: UUID
    previous_implementation_ref: UUID | None = None
    investigation: InvestigationOutput | None = None
    source_files: tuple[SourceFileSnapshot, ...] = ()


class AnalysisContext(RuntimeContext):
    test_run: TestRun
    implementation: ImplementationOutput
    implementation_artifact_id: UUID


class InvestigationContext(AnalysisContext):
    analysis: TestAnalysisOutput
    analysis_artifact_id: UUID
    defect_cycle: Count = 0
    evidence_conflict: bool = Field(default=False, strict=True)
    primary_investigation: InvestigationOutput | None = None
    primary_investigation_artifact_id: UUID | None = None
    escalation_decision_id: UUID | None = None
    escalation_reasons: tuple[NonBlank, ...] = ()
    escalation_target_model: NonBlank | None = None

    @model_validator(mode="after")
    def complete_escalation_context(self):
        fields = (self.primary_investigation, self.primary_investigation_artifact_id, self.escalation_target_model)
        if self.escalation_decision_id is not None:
            if any(value is None for value in fields) or not self.escalation_reasons:
                raise ValueError("Escalation requires primary evidence, decision, target, and reasons")
        elif any(value is not None for value in fields) or self.escalation_reasons:
            raise ValueError("Primary context cannot carry an unreserved escalation")
        return self


class ReviewContext(RuntimeContext):
    requirement: NonBlank
    plan: PlannerOutput
    implementation: ImplementationOutput
    test_run: TestRun
    plan_artifact_id: UUID
    implementation_artifact_id: UUID


class TestContext(RuntimeContext):
    implementation_artifact_id: UUID


AgentContext = ResearchContext | PlanContext | ImplementationContext | AnalysisContext | InvestigationContext | ReviewContext
STATE_AGENTS = MappingProxyType({
    TaskState.RESEARCHING: AgentName.RESEARCHER,
    TaskState.PLANNING: AgentName.PLANNER,
    TaskState.IMPLEMENTING: AgentName.IMPLEMENTER,
    TaskState.ANALYZING: AgentName.TEST_ANALYZER,
    TaskState.INVESTIGATING: AgentName.INVESTIGATOR,
    TaskState.REVIEWING: AgentName.REVIEWER,
})
OUTPUT_TYPES = MappingProxyType({
    AgentName.RESEARCHER: ResearchOutput, AgentName.PLANNER: PlannerOutput,
    AgentName.IMPLEMENTER: ImplementationOutput, AgentName.TEST_ANALYZER: TestAnalysisOutput,
    AgentName.INVESTIGATOR: InvestigationOutput, AgentName.REVIEWER: ReviewOutput,
})
CONTEXT_TYPES = MappingProxyType({
    AgentName.RESEARCHER: ResearchContext, AgentName.PLANNER: PlanContext,
    AgentName.IMPLEMENTER: ImplementationContext, AgentName.TEST_ANALYZER: AnalysisContext,
    AgentName.INVESTIGATOR: InvestigationContext, AgentName.REVIEWER: ReviewContext,
})
ARTIFACT_TYPES = MappingProxyType({
    AgentName.RESEARCHER: ArtifactType.RESEARCH, AgentName.PLANNER: ArtifactType.PLAN,
    AgentName.IMPLEMENTER: ArtifactType.IMPLEMENTATION, AgentName.TEST_ANALYZER: ArtifactType.TEST_ANALYSIS,
    AgentName.INVESTIGATOR: ArtifactType.INVESTIGATION, AgentName.REVIEWER: ArtifactType.REVIEW,
})


class AgentRuntime(Protocol):
    def run(self, agent_name: AgentName, context: AgentContext) -> AgentOutput | ModelResponse: ...
