"""Invocation/artifact transaction boundary; agents receive no persistence handles."""
from dataclasses import dataclass
from qa_sentinel.projects import ProjectWorkspaceGuard
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
from qa_sentinel.models.base import ModelResponse, ModelMetadata, ModelError
from qa_sentinel.schemas.mutation import ImplementationProposal
from qa_sentinel.mutation.contracts import MutationFailure, MutationReconciliationRequired
from .implementation_execution import ControlledImplementationExecution
from .repository_execution import ControlledRepositoryExecution, RepositoryLoopFailure, RepositoryReconciliationRequired
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
    def __init__(self, session_factory, runtime: AgentRuntime, *, mutation_service=None, repository_service=None,
                 workspace_binding=None):
        self.session_factory = session_factory
        self.runtime = runtime
        self.project_guard = ProjectWorkspaceGuard(session_factory, workspace_binding,
            reader=repository_service, mutation=mutation_service)
        self.implementation = ControlledImplementationExecution(session_factory, mutation_service)
        self.repository = ControlledRepositoryExecution(session_factory, repository_service)

    def repository_enabled(self, agent):
        return getattr(self.runtime, "repository_turns", lambda role: False)(agent)

    def resume_repository(self, invocation_id, context):
        with UnitOfWork(self.session_factory) as uow:
            invocation = uow.invocations.get(invocation_id)
            task = None if invocation is None else uow.tasks.get(invocation.task_id)
            if (invocation is None or task is None or invocation.status != AgentInvocationStatus.STARTED or
                task.current_invocation_id != invocation_id or STATE_AGENTS.get(task.state) != invocation.agent or
                type(context) is not CONTEXT_TYPES[invocation.agent] or context.task_id != task.id or
                context.attempt != invocation.attempt or not self.repository_enabled(invocation.agent)):
                raise RepositoryReconciliationRequired("REPOSITORY_INVOCATION_REQUIRES_RECONCILIATION")
        self.project_guard.check(task)
        return self._execute_started(invocation, invocation.agent, context)

    @staticmethod
    def _event(uow, invocation, event_type, artifact=None, metadata=None, schema_correction_planned=False,
               escalation_decision_id=None, mutation_result=None, proposal_artifact_id=None, workspace_identity=None,
               repository_evidence_refs=None):
        uow.history.append_event(Event(task_id=invocation.task_id, event_type=event_type,
            actor=dict(type="ORCHESTRATOR", id="qa-sentinel"),
            correlation=dict(invocation_id=invocation.id, artifact_id=None if artifact is None else artifact.id),
            payload=dict(agent=invocation.agent.value, status=invocation.status.value,
                **({"escalation_decision_id": str(escalation_decision_id)} if escalation_decision_id else {}),
                **({"model_metadata": metadata.model_dump(mode="json")} if metadata is not None else {}),
                **({"repository_evidence_refs": repository_evidence_refs} if repository_evidence_refs is not None else {}),
                **({"schema_correction_planned": True} if schema_correction_planned else {}))))
        if mutation_result is not None:
            uow.history.append_event(Event(task_id=invocation.task_id, event_type="MUTATION_APPLIED" if mutation_result.success else "MUTATION_FAILED",
                actor=dict(type="ORCHESTRATOR", id="qa-sentinel"),
                correlation=dict(invocation_id=invocation.id, artifact_id=proposal_artifact_id),
                payload=dict(result=mutation_result.model_dump(mode="json"), workspace_identity=workspace_identity)))

    def execute(self, agent: AgentName, context: AgentContext) -> AgentExecution:
        with UnitOfWork(self.session_factory) as uow:
            task = uow.tasks.get(context.task_id)
            if task is None:
                raise KeyError(context.task_id)
        self.project_guard.check(task)
        agent = AgentName(agent)
        if type(context) is not CONTEXT_TYPES[agent]:
            raise ValueError("Execution requires the role's typed context")
        now = datetime.now(timezone.utc)
        controlled = agent == AgentName.IMPLEMENTER and getattr(self.runtime, "implementation_proposals", lambda: False)()
        describe = getattr(self.runtime, "describe", None)
        model, effort = ("fake", "none") if describe is None else describe(agent, context)
        invocation = AgentInvocation(task_id=context.task_id, agent=agent, model=model,
            reasoning_effort=effort, attempt=context.attempt, status="STARTED", started_at=now,
            input_context_refs=context.evidence_refs)
        with UnitOfWork(self.session_factory) as uow:
            task = uow.tasks.get(context.task_id)
            if task is None:
                raise KeyError(context.task_id)
            if STATE_AGENTS.get(task.state) != agent:
                raise ValueError("Agent does not match the current task stage")
            if controlled:
                self.implementation.validate_plan(uow, context)
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
            escalation_id = getattr(context, "escalation_decision_id", None)
            self._event(uow, invocation, "AGENT_STARTED", escalation_decision_id=escalation_id)
            uow.commit()
        return self._execute_started(invocation, agent, context)

    def _execute_started(self, invocation, agent, context):
        controlled = agent == AgentName.IMPLEMENTER and getattr(self.runtime, "implementation_proposals", lambda: False)()
        repository = self.repository_enabled(agent)
        escalation_id = getattr(context, "escalation_decision_id", None)
        metadata = None
        proposal_artifact = None
        application = None
        try:
            if controlled:
                context = self.implementation.source_context(invocation, context)
            output = self.repository.run(invocation, context, self.runtime) if repository else self.runtime.run(agent, context)
            if isinstance(output, ModelResponse):
                metadata = ModelMetadata.model_validate(output.metadata.model_dump())
                output = output.parsed_output
            expected = ImplementationProposal if controlled else OUTPUT_TYPES[agent]
            if type(output) is not expected:
                raise SchemaOutputError()
            # Revalidate even typed outputs: model_copy can bypass contract validation.
            output = expected.model_validate(output.model_dump(mode="json"))
            if controlled:
                if metadata is None:
                    raise MutationFailure("INVALID_MUTATION")
                output, proposal_artifact, application = self.implementation.apply(invocation, context, output, metadata)
        except RepositoryLoopFailure as failure:
            return self._failed(invocation, failure.error_type, failure.code,
                failure.disposition, False, owner="TOOL", tool_id="repository-read")
        except MutationFailure as failure:
            return self._failed(invocation, failure.error_type, failure.code, failure.disposition, False,
                proposal_artifact=getattr(failure, "proposal_artifact", None),
                mutation_result=getattr(failure, "application_result", None), metadata=metadata, owner="TOOL")
        except (SchemaOutputError, ValidationError) as failure:
            return self._failed(invocation, ErrorType.SCHEMA_ERROR, "OUTPUT_SCHEMA_INVALID",
                FailureDisposition.CORRECTABLE, getattr(failure, "changed_input", False))
        except ModelError as failure:
            return self._failed(invocation, failure.error_type, failure.code, failure.disposition,
                failure.changed_input, failure.blocker_reason,
                schema_correction_planned=(failure.error_type == ErrorType.SCHEMA_ERROR and failure.changed_input))
        except AgentError as failure:
            return self._failed(invocation, ErrorType.AGENT_ERROR, "SIMULATED_AGENT_FAILURE",
                                failure.disposition, failure.changed_input, failure.blocker_reason)
        except ScenarioExhaustedError:
            return self._failed(invocation, ErrorType.AGENT_ERROR, "SCENARIO_EXHAUSTED",
                                FailureDisposition.TERMINAL, False)
        # Persistence exceptions deliberately propagate; STARTED is durable, completion is not.
        artifact = Artifact(task_id=invocation.task_id, invocation_id=invocation.id,
            artifact_type=ARTIFACT_TYPES[agent], schema_version="0.1", producer_agent=agent,
            producer_model=invocation.model, content=output.model_dump(mode="json"))
        completed = AgentInvocation(**{**invocation.model_dump(), "status": AgentInvocationStatus.COMPLETED,
                                      "finished_at": datetime.now(timezone.utc)})
        try:
            with UnitOfWork(self.session_factory) as uow:
                uow.artifacts.add(artifact)
                uow.invocations.save(completed)
                self._event(uow, completed, "AGENT_COMPLETED", artifact, metadata,
                    escalation_decision_id=escalation_id, mutation_result=application,
                    proposal_artifact_id=None if proposal_artifact is None else proposal_artifact.id,
                    workspace_identity=None if application is None else self.implementation.service.workspace_identity,
                    repository_evidence_refs=None if not repository else ["artifact:" + str(a.id) for a in
                        sorted((a for a in uow.artifacts.list_by_task(invocation.task_id) if
                            a.invocation_id == invocation.id and a.artifact_type.value == "REPOSITORY_EVIDENCE"),
                            key=lambda a: a.content["call_index"])])
                uow.commit()
        except Exception:
            if application is not None and application.applied:
                raise MutationReconciliationRequired("MUTATION_COMPLETION_REQUIRES_RECONCILIATION") from None
            raise
        return AgentExecution(invocation=completed, output=output, artifact=artifact)

    def _failed(self, invocation, error_type, code, disposition, changed_input, blocker_reason=None,
                schema_correction_planned=False, proposal_artifact=None, mutation_result=None, metadata=None, owner="AGENT",
                tool_id="mutation-service"):
        error = ErrorRecord(task_id=invocation.task_id, error_type=error_type, code=code,
            severity="ERROR", owner=owner, retryable=(disposition == FailureDisposition.TRANSIENT or
                disposition == FailureDisposition.CORRECTABLE and changed_input), blocking=blocker_reason is not None,
            source=dict(actor=dict(type=owner, id=tool_id if owner == "TOOL" else invocation.agent.value),
                        invocation_id=invocation.id),
            message="Deterministic agent execution did not produce an accepted output.",
            evidence_refs=invocation.input_context_refs)
        failed = AgentInvocation(**{**invocation.model_dump(), "finished_at": datetime.now(timezone.utc),
            "status": "BLOCKED" if blocker_reason is not None else "FAILED", "error_id": error.id})
        with UnitOfWork(self.session_factory) as uow:
            if proposal_artifact is not None and uow.artifacts.get(proposal_artifact.id) is None:
                uow.artifacts.add(proposal_artifact)
            uow.history.append_error(error)
            uow.invocations.save(failed)
            self._event(uow, failed, "AGENT_BLOCKED" if blocker_reason is not None else "AGENT_FAILED",
                metadata=metadata, schema_correction_planned=schema_correction_planned,
                mutation_result=mutation_result, proposal_artifact_id=None if proposal_artifact is None else proposal_artifact.id,
                workspace_identity=None if mutation_result is None else self.implementation.service.workspace_identity)
            uow.commit()
        return AgentExecution(invocation=failed, error=error, disposition=disposition,
                              changed_input=changed_input, blocker_reason=blocker_reason)

    def verify_implementation(self, invocation_id):
        with UnitOfWork(self.session_factory) as uow:
            invocation = uow.invocations.get(invocation_id) if invocation_id else None
            if invocation is None:
                return
            events = [e for e in uow.history.list_events(invocation.task_id)
                      if e.correlation.invocation_id == invocation_id]
            evidence = [e for e in events if e.event_type == "MUTATION_APPLIED"]
        if not evidence and any(e.event_type == "MUTATION_RESERVED" for e in events):
            raise MutationReconciliationRequired("MUTATION_EVIDENCE_REQUIRES_RECONCILIATION")
        if evidence:
            if len(evidence) != 1 or self.implementation.service is None:
                raise MutationReconciliationRequired("MUTATION_EVIDENCE_REQUIRES_RECONCILIATION")
            try:
                self.implementation.service.verify_applied(evidence[0].payload["result"]["applied"], evidence[0].payload["workspace_identity"])
            except (MutationFailure, ValidationError, OSError):
                raise MutationReconciliationRequired("MUTATION_WORKSPACE_REQUIRES_RECONCILIATION") from None
