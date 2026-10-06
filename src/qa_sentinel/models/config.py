"""Explicit reasoning-role configuration; models have no external tools."""
from qa_sentinel.domain.enums import AgentName
from .base import FrozenModel, ModelSettings, ModelError, ProviderErrorCategory
from pydantic import Field


class RoleModelConfig(FrozenModel):
    researcher: ModelSettings = Field(default_factory=lambda: ModelSettings(
        model="gpt-5.6-luna", reasoning_effort="medium"))
    planner: ModelSettings = Field(default_factory=lambda: ModelSettings(
        model="gpt-5.6-sol", reasoning_effort="high"))
    implementer: ModelSettings = Field(default_factory=lambda: ModelSettings(
        model="gpt-5.6-luna", reasoning_effort="high"))
    test_analyzer: ModelSettings = Field(default_factory=lambda: ModelSettings(
        model="gpt-5.6-luna", reasoning_effort="medium"))
    investigator: ModelSettings = Field(default_factory=lambda: ModelSettings(
        model="gpt-5.6-luna", reasoning_effort="high"))
    investigator_escalated: ModelSettings = Field(default_factory=lambda: ModelSettings(
        model="gpt-5.6-sol", reasoning_effort="high"))
    reviewer: ModelSettings = Field(default_factory=lambda: ModelSettings(
        model="gpt-5.6-sol", reasoning_effort="high"))

    def for_role(self, role: AgentName, *, escalated: bool = False) -> ModelSettings:
        if role == AgentName.RESEARCHER:
            return self.researcher
        if role == AgentName.PLANNER:
            return self.planner
        if role == AgentName.IMPLEMENTER:
            return self.implementer
        if role == AgentName.TEST_ANALYZER:
            return self.test_analyzer
        if role == AgentName.INVESTIGATOR:
            return self.investigator_escalated if escalated else self.investigator
        if role == AgentName.REVIEWER:
            return self.reviewer
        raise ModelError(ProviderErrorCategory.UNSUPPORTED_ROLE)
