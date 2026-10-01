"""Invocation/artifact transaction boundary; agents receive no persistence handles."""
from dataclasses import dataclass
from datetime import datetime, timezone
from pydantic import ValidationError
from qa_sentinel.agents.base import (
    AgentRuntime, AgentContext, AgentOutput, OUTPUT_TYPES, ARTIFACT_TYPES, STATE_AGENTS, CONTEXT_TYPES,
)
from qa_sentinel.agents.fake import AgentError, SchemaOutputError, ScenarioExhaustedError
from qa_sentinel.domain.enums import AgentName, AgentInvocationStatus, ErrorType
from qa_sentinel.domain.invocation import AgentInvocation
from qa_sentinel.domain.artifact import Artifact
from qa_sentinel.domain.error import ErrorRecord
from qa_sentinel.domain.event import Event
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from .reliability_policy import FailureDisposition, BlockerReason


@dataclass(frozen=True)
class AgentExecution:
    invocation: AgentInvocation
    output: AgentOutput | None = None
    artifact: Artifact | None = None
    error: ErrorRecord | None = None
    disposition: FailureDisposition | None = None
    changed_input: bool = False
    blocker_reason: BlockerReason | None = None


class AgentExecutor:
    def __init__(self, session_factory, runtime: AgentRuntime):
        self.session_factory = session_factory
        self.runtime = runtime

    @staticmethod
    def _event(uow, invocation, event_type, artifact=None):
        uow.history.append_event(Event(task_id=invocation.task_id, event_type=event_type,
            actor=dict(type="ORCHESTRATOR", id="qa-sentinel"),
            correlation=dict(invocation_id=invocation.id, artifact_id=None if artifact is None else artifact.id),
            payload=dict(agent=invocation.agent.value, status=invocation.status.value)))

    def execute(self, agent: AgentName, context: AgentContext) -> AgentExecution:
        agent = AgentName(agent)
        if type(context) is not CONTEXT_TYPES[agent]:
            raise ValueError("Execution requires the role's typed context")
        now = datetime.now(timezone.utc)
        invocation = AgentInvocation(task_id=context.task_id, agent=agent, model="fake",
            reasoning_effort="none", attempt=context.attempt, status="STARTED", started_at=now,
            input_context_refs=context.evidence_refs)
        with UnitOfWork(self.session_factory) as uow:
            task = uow.tasks.get(context.task_id)
            if task is None:
                raise KeyError(context.task_id)
            if STATE_AGENTS.get(task.state) != agent:
                raise ValueError("Agent does not match the current task stage")
            expected_attempt = 1 + sum(i.agent == agent for i in uow.invocations.list_by_task(task.id))
            if context.attempt != expected_attempt:
                raise ValueError("Invocation attempt does not match durable history")
            active = None if task.current_invocation_id is None else uow.invocations.get(task.current_invocation_id)
            if active is not None and active.status == AgentInvocationStatus.STARTED:
                raise ValueError("An active invocation must be reconciled before executing again")
            uow.invocations.add(invocation)
            task.current_invocation_id = invocation.id
            task.updated_at = now
            if agent == AgentName.IMPLEMENTER:
                task.implementation_attempt += 1
            if agent == AgentName.REVIEWER:
                task.review_cycle += 1
            uow.tasks.save(task)
            self._event(uow, invocation, "AGENT_STARTED")
            uow.commit()
        try:
            output = self.runtime.run(agent, context)
            expected = OUTPUT_TYPES[agent]
            if type(output) is not expected:
                raise SchemaOutputError()
            # Revalidate even typed outputs: model_copy can bypass contract validation.
            output = expected.model_validate(output.model_dump(mode="json"))
        except (SchemaOutputError, ValidationError) as failure:
            return self._failed(invocation, ErrorType.SCHEMA_ERROR, "OUTPUT_SCHEMA_INVALID",
                FailureDisposition.CORRECTABLE, getattr(failure, "changed_input", False))
        except AgentError as failure:
            return self._failed(invocation, ErrorType.AGENT_ERROR, "SIMULATED_AGENT_FAILURE",
                                failure.disposition, failure.changed_input, failure.blocker_reason)
        except ScenarioExhaustedError:
            return self._failed(invocation, ErrorType.AGENT_ERROR, "SCENARIO_EXHAUSTED",
                                FailureDisposition.TERMINAL, False)
        # Persistence exceptions deliberately propagate; STARTED is durable, completion is not.
        artifact = Artifact(task_id=invocation.task_id, invocation_id=invocation.id,
            artifact_type=ARTIFACT_TYPES[agent], schema_version="0.1", producer_agent=agent,
            producer_model="fake", content=output.model_dump(mode="json"))
        completed = AgentInvocation(**{**invocation.model_dump(), "status": AgentInvocationStatus.COMPLETED,
                                      "finished_at": datetime.now(timezone.utc)})
        with UnitOfWork(self.session_factory) as uow:
            uow.artifacts.add(artifact)
            uow.invocations.save(completed)
            self._event(uow, completed, "AGENT_COMPLETED", artifact)
            uow.commit()
        return AgentExecution(invocation=completed, output=output, artifact=artifact)

    def _failed(self, invocation, error_type, code, disposition, changed_input, blocker_reason=None):
        error = ErrorRecord(task_id=invocation.task_id, error_type=error_type, code=code,
            severity="ERROR", owner="AGENT", retryable=(disposition == FailureDisposition.TRANSIENT or
                disposition == FailureDisposition.CORRECTABLE and changed_input), blocking=blocker_reason is not None,
            source=dict(actor=dict(type="AGENT", id=invocation.agent.value), invocation_id=invocation.id),
            message="Deterministic agent execution did not produce an accepted output.",
            evidence_refs=invocation.input_context_refs)
        failed = AgentInvocation(**{**invocation.model_dump(), "finished_at": datetime.now(timezone.utc),
            "status": "BLOCKED" if blocker_reason is not None else "FAILED", "error_id": error.id})
        with UnitOfWork(self.session_factory) as uow:
            uow.history.append_error(error)
            uow.invocations.save(failed)
            self._event(uow, failed, "AGENT_BLOCKED" if blocker_reason is not None else "AGENT_FAILED")
            uow.commit()
        return AgentExecution(invocation=failed, error=error, disposition=disposition,
                              changed_input=changed_input, blocker_reason=blocker_reason)
