"""Explicit configuration for the two real roles only; contains no credentials."""
from qa_sentinel.domain.enums import AgentName
from .base import FrozenModel, ModelSettings, ModelError, ProviderErrorCategory
from pydantic import Field


class RoleModelConfig(FrozenModel):
    researcher: ModelSettings = Field(default_factory=lambda: ModelSettings(
        model="gpt-5.6-luna", reasoning_effort="medium"))
    planner: ModelSettings = Field(default_factory=lambda: ModelSettings(
        model="gpt-5.6-sol", reasoning_effort="high"))

    def for_role(self, role: AgentName) -> ModelSettings:
        if role == AgentName.RESEARCHER:
            return self.researcher
        if role == AgentName.PLANNER:
            return self.planner
        raise ModelError(ProviderErrorCategory.UNSUPPORTED_ROLE)
