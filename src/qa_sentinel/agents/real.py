"""Reasoning-only real Researcher/Planner; stateless between invocations."""
from .base import AgentContext, OUTPUT_TYPES
from .prompts import build_request
from qa_sentinel.models.base import ModelAdapter, ModelError, ProviderErrorCategory
from qa_sentinel.models.config import RoleModelConfig
from pydantic import ValidationError


class RealAgentRuntime:
    def __init__(self, adapter: ModelAdapter, config: RoleModelConfig | None = None):
        self.adapter = adapter
        self.config = config or RoleModelConfig()

    def describe(self, agent):
        settings = self.config.for_role(agent)
        return settings.model, settings.reasoning_effort or "none"

    def run(self, agent_name, context: AgentContext):
        settings = self.config.for_role(agent_name)
        request = build_request(agent_name, context, settings)
        try:
            response = self.adapter.generate(request, OUTPUT_TYPES[agent_name])
            expected = OUTPUT_TYPES[agent_name]
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
