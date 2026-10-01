"""Deterministic responses indexed by persisted invocation attempt, without database access."""
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping
from pydantic import ValidationError
from qa_sentinel.domain.enums import AgentName
from qa_sentinel.orchestration.reliability_policy import FailureDisposition, BlockerReason
from .base import AgentOutput, AgentContext, OUTPUT_TYPES, CONTEXT_TYPES


class AgentError(Exception):
    def __init__(self, disposition: FailureDisposition, *, changed_input: bool = False,
                 blocker_reason: BlockerReason | None = None):
        super().__init__("Scenario-driven agent failure")
        if not isinstance(changed_input, bool):
            raise ValueError("changed_input must be a boolean")
        self.disposition = FailureDisposition(disposition)
        self.changed_input = changed_input
        self.blocker_reason = None if blocker_reason is None else BlockerReason(blocker_reason)


class SchemaOutputError(Exception):
    def __init__(self, *, changed_input: bool = False):
        super().__init__("Agent output does not satisfy its structured contract")
        self.changed_input = changed_input


class ScenarioExhaustedError(Exception):
    pass


@dataclass(frozen=True)
class FakeResponse:
    output: AgentOutput | None = None
    raw_output: Mapping | None = None
    failure: FailureDisposition | None = None
    changed_input: bool = False
    blocker_reason: BlockerReason | None = None

    def __post_init__(self):
        if sum(value is not None for value in (self.output, self.raw_output, self.failure)) != 1:
            raise ValueError("Configure exactly one output, raw output, or failure")
        if not isinstance(self.changed_input, bool):
            raise ValueError("changed_input must be a boolean")
        if self.failure is not None:
            object.__setattr__(self, "failure", FailureDisposition(self.failure))
        if self.output is not None and type(self.output) not in OUTPUT_TYPES.values():
            raise ValueError("Successful fake responses require an existing typed agent output")
        if self.blocker_reason is not None:
            object.__setattr__(self, "blocker_reason", BlockerReason(self.blocker_reason))
            if self.failure is None:
                raise ValueError("A blocker requires a failure response")
        if self.raw_output is not None:
            object.__setattr__(self, "raw_output", MappingProxyType(deepcopy(dict(self.raw_output))))


@dataclass(frozen=True)
class FakeScenario:
    responses: Mapping[AgentName, tuple[FakeResponse, ...]]
    repeat_last: bool = False

    def __post_init__(self):
        if not isinstance(self.repeat_last, bool):
            raise ValueError("repeat_last must be a boolean")
        responses = {AgentName(agent): tuple(sequence) for agent, sequence in self.responses.items()}
        if any(not sequence or any(not isinstance(r, FakeResponse) for r in sequence)
               for sequence in responses.values()):
            raise ValueError("Each configured agent needs a nonempty FakeResponse sequence")
        object.__setattr__(self, "responses", MappingProxyType(responses))


class FakeAgentRuntime:
    def __init__(self, scenario: FakeScenario):
        self.scenario = scenario

    def run(self, agent_name: AgentName, context: AgentContext) -> AgentOutput:
        agent_name = AgentName(agent_name)
        if type(context) is not CONTEXT_TYPES[agent_name]:
            raise TypeError("Agent context does not match the configured role")
        sequence = self.scenario.responses.get(agent_name, ())
        index = context.attempt - 1
        if index >= len(sequence):
            if not self.scenario.repeat_last or not sequence:
                raise ScenarioExhaustedError("Configured agent response sequence exhausted")
            index = len(sequence) - 1
        response = sequence[index]
        if response.failure is not None:
            raise AgentError(response.failure, changed_input=response.changed_input,
                             blocker_reason=response.blocker_reason)
        expected = OUTPUT_TYPES[agent_name]
        if response.output is not None and type(response.output) is not expected:
            raise SchemaOutputError(changed_input=response.changed_input)
        data = response.output.model_dump(mode="json") if response.output is not None else dict(response.raw_output)
        try:
            return expected.model_validate(data)
        except ValidationError:
            # Do not persist validation details, which can include raw input/secrets.
            raise SchemaOutputError(changed_input=response.changed_input) from None
