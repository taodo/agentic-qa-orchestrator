"""Reasoning-only real roles; Implementer proposes without writing files."""
from .base import AgentContext, OUTPUT_TYPES, InvestigationContext
from .prompts import build_request
from qa_sentinel.models.base import ModelAdapter, ModelError, ProviderErrorCategory
from qa_sentinel.models.config import RoleModelConfig
from pydantic import ValidationError
from qa_sentinel.domain.enums import AgentName
from qa_sentinel.schemas.mutation import ImplementationProposal


class RealAgentRuntime:
    def __init__(self, adapter: ModelAdapter, config: RoleModelConfig | None = None):
        self.adapter = adapter
        self.config = config or RoleModelConfig()

    def _settings(self, agent, context=None):
        escalated = type(context) is InvestigationContext and context.escalation_decision_id is not None
        settings = self.config.for_role(agent, escalated=escalated)
        if escalated and settings.model != context.escalation_target_model:
            raise ModelError(ProviderErrorCategory.INVALID_REQUEST)
        return settings

    def investigator_models(self):
        return self.config.investigator.model, self.config.investigator_escalated.model

    def implementation_proposals(self):
        return True

    def describe(self, agent, context=None):
        settings = self._settings(agent, context)
        return settings.model, settings.reasoning_effort or "none"

    def run(self, agent_name, context: AgentContext):
        settings = self._settings(agent_name, context)
        request = build_request(agent_name, context, settings)
        try:
            expected = ImplementationProposal if agent_name == AgentName.IMPLEMENTER else OUTPUT_TYPES[agent_name]
            response = self.adapter.generate(request, expected)
            if type(response.parsed_output) is not expected:
                raise ModelError(ProviderErrorCategory.MALFORMED_RESPONSE)
            output = expected.model_validate(response.parsed_output.model_dump(mode="json"))
            return response.model_copy(update={"parsed_output": output})
        except (ModelError, ValidationError) as failure:
            if isinstance(failure, ValidationError) or failure.category == ProviderErrorCategory.MALFORMED_RESPONSE:
                # One explicit correction adds instructions to the next call; no hidden repair call.
                raise ModelError(ProviderErrorCategory.MALFORMED_RESPONSE,
                                 changed_input=not context.schema_correction) from None
            raise
