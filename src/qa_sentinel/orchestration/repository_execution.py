"""Explicit persisted model turns and read evidence within one agent invocation."""
from hashlib import sha256
from pydantic import ValidationError
from qa_sentinel.domain.enums import AgentName, ArtifactType, ErrorType
from .reliability_policy import FailureDisposition
from qa_sentinel.domain.artifact import Artifact
from qa_sentinel.domain.event import Event
from qa_sentinel.models.base import ModelResponse, ModelMetadata, ModelError
from qa_sentinel.schemas.repository import (ResearchTurn, PlannerTurn, RepositoryEvidence, RepositoryToolResult)
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.agents.fake import SchemaOutputError


class RepositoryReconciliationRequired(RuntimeError):
    pass


class RepositoryLoopFailure(Exception):
    def __init__(self, code, error_type=ErrorType.WORKFLOW_ERROR, disposition=FailureDisposition.STRUCTURAL):
        super().__init__(code)
        self.code = code
        self.error_type, self.disposition = error_type, disposition


class ControlledRepositoryExecution:
    def __init__(self, factory, service):
        self.factory, self.service = factory, service

    def _event(self, invocation, name, payload, artifact=None):
        return Event(task_id=invocation.task_id, event_type=name,
            actor=dict(type="ORCHESTRATOR", id="qa-sentinel"),
            correlation=dict(invocation_id=invocation.id, artifact_id=None if artifact is None else artifact.id),
            payload=payload)

    def _record(self, invocation, name, payload):
        with UnitOfWork(self.factory) as uow:
            uow.history.append_event(self._event(invocation, name, payload))
            uow.commit()

    def has_session(self, invocation):
        with UnitOfWork(self.factory) as uow:
            return any(e.event_type == "REPOSITORY_SESSION_STARTED" and e.correlation.invocation_id == invocation.id
                       for e in uow.history.list_events(invocation.task_id))

    @staticmethod
    def _indexed(events, name):
        selected = [e for e in events if e.event_type == name]
        indices = [e.payload["turn_index"] for e in selected]
        if any(type(i) is not int or i < 1 for i in indices) or len(set(indices)) != len(indices):
            raise RepositoryReconciliationRequired("REPOSITORY_HISTORY_REQUIRES_RECONCILIATION")
        return {e.payload["turn_index"]: e for e in selected}

    def run(self, invocation, context, runtime):
        if self.service is None:
            raise RepositoryLoopFailure("REPOSITORY_SERVICE_REQUIRED")
        if invocation.agent not in {AgentName.RESEARCHER, AgentName.PLANNER} or context.repository_results:
            raise RepositoryLoopFailure("ROLE_OR_CONTEXT_NOT_AUTHORIZED")
        if runtime.describe(invocation.agent, context) != (invocation.model, invocation.reasoning_effort):
            raise RepositoryReconciliationRequired("REPOSITORY_MODEL_REQUIRES_RECONCILIATION")
        identity = dict(context_sha256=sha256(context.model_dump_json().encode("utf-8")).hexdigest(),
                        repository_config_identity=self.service.config.identity)
        with UnitOfWork(self.factory) as uow:
            events = [e for e in uow.history.list_events(invocation.task_id)
                      if e.correlation.invocation_id == invocation.id]
            artifacts = {a.id: a for a in uow.artifacts.list_by_task(invocation.task_id)
                         if a.invocation_id == invocation.id and a.artifact_type == ArtifactType.REPOSITORY_EVIDENCE}
        markers = [e for e in events if e.event_type == "REPOSITORY_SESSION_STARTED"]
        if not markers:
            self._record(invocation, "REPOSITORY_SESSION_STARTED", identity)
        elif len(markers) != 1 or markers[0].payload != identity:
            raise RepositoryReconciliationRequired("REPOSITORY_CONTEXT_REQUIRES_RECONCILIATION")
        try:
            starts = self._indexed(events, "MODEL_TURN_STARTED")
            completed = self._indexed(events, "MODEL_TURN_COMPLETED")
            result_events = self._indexed(events, "REPOSITORY_TOOL_COMPLETED")
            requests = self._indexed(events, "REPOSITORY_TOOL_REQUESTED")
            if (sorted(starts) != list(range(1, len(starts) + 1)) or set(completed) != set(starts) or
                len(starts) > self.service.config.max_tool_calls_per_agent_invocation + 1 or
                not set(result_events) <= set(completed) or not set(requests) <= set(completed) or
                {e.correlation.artifact_id for e in result_events.values()} != set(artifacts)):
                raise RepositoryReconciliationRequired("UNRESOLVED_MODEL_TURN_REQUIRES_RECONCILIATION")
            return self._turns(invocation, context, runtime, completed, requests, result_events, artifacts)
        except (KeyError, ValidationError, TypeError, ValueError):
            raise RepositoryReconciliationRequired("REPOSITORY_HISTORY_REQUIRES_RECONCILIATION") from None

    def _turns(self, invocation, context, runtime, completed, requests, result_events, artifacts):
        evidence = []
        expected = ResearchTurn if invocation.agent == AgentName.RESEARCHER else PlannerTurn
        maximum = self.service.config.max_tool_calls_per_agent_invocation
        for index in range(1, maximum + 2):
            if index in completed:
                event = completed[index]
                turn = expected.model_validate(event.payload["turn"])
                metadata = ModelMetadata.model_validate(event.payload["model_metadata"])
            else:
                self._record(invocation, "MODEL_TURN_STARTED", dict(turn_index=index,
                    model=invocation.model, reasoning_effort=invocation.reasoning_effort))
                metadata = None
                try:
                    response = runtime.run(invocation.agent, context.model_copy(update={"repository_results": tuple(evidence)}))
                    if not isinstance(response, ModelResponse):
                        raise ValueError("Invalid turn envelope")
                    metadata = ModelMetadata.model_validate(response.metadata.model_dump())
                    if type(response.parsed_output) is not expected:
                        raise ValueError("Invalid turn envelope")
                    turn = expected.model_validate(response.parsed_output.model_dump(mode="json"))
                except ModelError as failure:
                    self._record(invocation, "MODEL_TURN_FAILED", dict(turn_index=index, code=failure.code,
                        **({"model_metadata": failure.metadata.model_dump(mode="json")}
                           if failure.metadata is not None else {})))
                    raise
                except (ValueError, ValidationError):
                    self._record(invocation, "MODEL_TURN_FAILED", dict(turn_index=index, code="OUTPUT_SCHEMA_INVALID",
                        **({"model_metadata": metadata.model_dump(mode="json")} if metadata is not None else {})))
                    raise SchemaOutputError() from None
                # Only validated turns and safe scalar metadata are persisted, not SDK responses.
                self._record(invocation, "MODEL_TURN_COMPLETED", dict(turn_index=index,
                    turn=turn.model_dump(mode="json"), model_metadata=metadata.model_dump(mode="json")))
            if turn.kind == "FINAL_OUTPUT":
                if any(i > index for i in completed) or index in result_events or index in requests:
                    raise RepositoryReconciliationRequired("REPOSITORY_HISTORY_REQUIRES_RECONCILIATION")
                return ModelResponse(parsed_output=turn.final_output, metadata=metadata)
            request = turn.tool_request
            if index in requests:
                if requests[index].payload["request"] != request.model_dump(mode="json"):
                    raise RepositoryReconciliationRequired("REPOSITORY_REQUEST_REQUIRES_RECONCILIATION")
            else:
                self._record(invocation, "REPOSITORY_TOOL_REQUESTED", dict(turn_index=index,
                    request=request.model_dump(mode="json")))
            if index in result_events:
                artifact = artifacts[result_events[index].correlation.artifact_id]
                item = RepositoryEvidence.model_validate(artifact.content)
                if item.call_index != index or item.request != request or item.evidence_ref != "artifact:" + str(artifact.id):
                    raise RepositoryReconciliationRequired("REPOSITORY_EVIDENCE_REQUIRES_RECONCILIATION")
            else:
                if index > maximum:
                    result = RepositoryToolResult(request_id=request.request_id, tool=request.tool, status="DENIED",
                        data=None, error_code="TOOL_CALL_BUDGET_EXHAUSTED")
                elif any(e.request.request_id == request.request_id for e in evidence):
                    result = RepositoryToolResult(request_id=request.request_id, tool=request.tool, status="DENIED",
                        data=None, error_code="REQUEST_ID_REUSED")
                else:
                    result = self.service.execute(invocation.agent, request, calls_used=index - 1,
                        bytes_used=sum(e.result.returned_bytes for e in evidence))
                artifact = Artifact(task_id=invocation.task_id, invocation_id=invocation.id,
                    artifact_type=ArtifactType.REPOSITORY_EVIDENCE, schema_version="0.1", content={})
                item = RepositoryEvidence(evidence_ref="artifact:" + str(artifact.id), call_index=index,
                    request=request, result=result)
                artifact = artifact.model_copy(update={"content": item.model_dump(mode="json")})
                with UnitOfWork(self.factory) as uow:
                    uow.artifacts.add(artifact)
                    uow.history.append_event(self._event(invocation, "REPOSITORY_TOOL_COMPLETED",
                        dict(turn_index=index, request_id=str(request.request_id), tool=request.tool.value,
                             status=result.status, error_code=result.error_code, returned_bytes=result.returned_bytes), artifact))
                    uow.commit()
            evidence.append(item)
            if item.result.error_code in {"TOOL_CALL_BUDGET_EXHAUSTED", "TOTAL_BYTES_EXCEEDED"}:
                raise RepositoryLoopFailure(item.result.error_code)
            if item.result.status != "SUCCESS":
                raise RepositoryLoopFailure(item.result.error_code,
                    ErrorType.POLICY_VIOLATION if item.result.status == "DENIED" else ErrorType.TOOL_ERROR,
                    FailureDisposition.TERMINAL if item.result.status == "DENIED" else FailureDisposition.STRUCTURAL)
        raise RepositoryLoopFailure("TOOL_CALL_BUDGET_EXHAUSTED")
