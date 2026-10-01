"""Typed, bounded agent inputs and the model-independent runtime boundary."""
from types import MappingProxyType
from typing import Protocol
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from qa_sentinel.domain.enums import AgentName, ArtifactType, TaskState
from qa_sentinel.domain.types import NonBlank, Attempt
from qa_sentinel.domain.test_run import TestRun
from qa_sentinel.schemas.research import ResearchOutput
from qa_sentinel.schemas.plan import PlannerOutput
from qa_sentinel.schemas.implementation import ImplementationOutput
from qa_sentinel.schemas.test_result import TestAnalysisOutput
from qa_sentinel.schemas.investigation import InvestigationOutput
from qa_sentinel.schemas.review import ReviewOutput

AgentOutput = ResearchOutput | PlannerOutput | ImplementationOutput | TestAnalysisOutput | InvestigationOutput | ReviewOutput


class RuntimeContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task_id: UUID
    attempt: Attempt
    evidence_refs: tuple[NonBlank, ...] = ()


class ResearchContext(RuntimeContext):
    requirement: NonBlank
    prior_research_ref: UUID | None = None


class PlanContext(RuntimeContext):
    requirement: NonBlank
    research: ResearchOutput
    research_artifact_id: UUID


class ImplementationContext(RuntimeContext):
    plan: PlannerOutput
    plan_artifact_id: UUID
    previous_implementation_ref: UUID | None = None
    investigation: InvestigationOutput | None = None


class AnalysisContext(RuntimeContext):
    test_run: TestRun
    implementation: ImplementationOutput
    implementation_artifact_id: UUID


class InvestigationContext(AnalysisContext):
    analysis: TestAnalysisOutput
    analysis_artifact_id: UUID


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
    def run(self, agent_name: AgentName, context: AgentContext) -> AgentOutput: ...
