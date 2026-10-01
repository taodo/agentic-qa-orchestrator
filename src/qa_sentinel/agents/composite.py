"""Explicit role routing outside WorkflowRunner and the model adapter."""
from types import MappingProxyType
from qa_sentinel.domain.enums import AgentName
from qa_sentinel.models.base import ModelError, ProviderErrorCategory


class CompositeAgentRuntime:
    def __init__(self, routes):
        self.routes = MappingProxyType({AgentName(role): runtime for role, runtime in routes.items()})

    def _route(self, role):
        try:
            return self.routes[AgentName(role)]
        except KeyError:
            raise ModelError(ProviderErrorCategory.UNSUPPORTED_ROLE) from None

    def describe(self, role):
        runtime = self._route(role)
        describe = getattr(runtime, "describe", None)
        return ("fake", "none") if describe is None else describe(role)

    def run(self, agent_name, context):
        return self._route(agent_name).run(agent_name, context)
