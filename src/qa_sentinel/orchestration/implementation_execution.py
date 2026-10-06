"""Controlled implementation phases within the existing AgentExecutor lifecycle."""
from hashlib import sha256
import json
from qa_sentinel.domain.artifact import Artifact
from qa_sentinel.domain.event import Event
from qa_sentinel.domain.enums import ArtifactType, AgentName, GateResult
from qa_sentinel.schemas.plan import PlannerOutput
from qa_sentinel.schemas.implementation import ImplementationOutput
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.mutation.contracts import MutationFailure, MutationReconciliationRequired
from .gates import ImplementationGate


def canonical_output(proposal, applied=()):
    reasons = {m.path: m.reason for m in proposal.mutations}
    paths = {f.path for f in applied}
    return ImplementationOutput(implementation_status=proposal.implementation_status,
        plan_steps=proposal.plan_steps, changed_files=[dict(path=f.path,
            change_type="CREATED" if f.operation.value == "CREATE" else "MODIFIED", reason=reasons[f.path]) for f in applied],
        tests_added_or_modified=tuple(p for p in proposal.tests_added_or_modified if p in paths),
        commands_executed=(), deviations=proposal.deviations, assumptions=proposal.assumptions, known_issues=proposal.known_issues)


class ControlledImplementationExecution:
    def __init__(self, factory, service):
        self.factory, self.service = factory, service

    @staticmethod
    def validate_plan(uow, context):
        artifact = uow.artifacts.get(context.plan_artifact_id)
        if artifact is None or artifact.task_id != context.task_id or artifact.artifact_type != ArtifactType.PLAN:
            raise ValueError("Controlled implementation requires an accepted same-task plan")
        invocation = uow.invocations.get(artifact.invocation_id) if artifact.invocation_id else None
        gates = {g.id: g for g in uow.history.list_gate_evaluations(context.task_id)}
        accepted = {t.decision_id for t in uow.history.list_transitions(context.task_id)
                    if t.gate_evaluation_id in gates and gates[t.gate_evaluation_id].result == GateResult.PASS}
        approved = any(e.event_type == "STATE_TRANSITIONED" and e.correlation.artifact_id == artifact.id and
                       e.correlation.decision_id in accepted for e in uow.history.list_events(context.task_id))
        if (invocation is None or invocation.status.value != "COMPLETED" or invocation.agent != AgentName.PLANNER or
            not approved or PlannerOutput.model_validate(artifact.content) != context.plan):
            raise ValueError("Controlled implementation requires the exact gate-accepted plan")

    def source_context(self, invocation, context):
        if self.service is None:
            raise MutationFailure("MUTATION_SERVICE_REQUIRED")
        snapshots = self.service.build_snapshots(context.plan)
        with UnitOfWork(self.factory) as uow:
            uow.history.append_event(Event(task_id=invocation.task_id, event_type="IMPLEMENTATION_SOURCE_CAPTURED",
                actor=dict(type="ORCHESTRATOR", id="qa-sentinel"), correlation=dict(invocation_id=invocation.id),
                payload=dict(plan_artifact_id=str(context.plan_artifact_id), workspace_identity=self.service.workspace_identity,
                    sources=[dict(path=s.path, sha256=s.sha256, size_bytes=s.size_bytes) for s in snapshots])))
            uow.commit()
        return context.model_copy(update={"source_files": snapshots})

    def apply(self, invocation, context, proposal, metadata):
        decision = self.service.policy.evaluate(context.plan, context.source_files, proposal)
        if decision.allowed and proposal.mutations:
            preview = canonical_output(proposal)
            if ImplementationGate.evaluate(invocation.task_id, preview, context.plan).result != GateResult.PASS:
                from qa_sentinel.mutation.contracts import PolicyDecision
                decision = PolicyDecision(allowed=False, reason_code="IMPLEMENTATION_GATE_REJECTED",
                                          reason="Proposed work does not satisfy the existing implementation gate.")
        content = proposal.model_dump(mode="json") if decision.allowed else dict(
            proposal_sha256=sha256(json.dumps(proposal.model_dump(mode="json"), sort_keys=True).encode("utf-8")).hexdigest(),
            mutation_count=len(proposal.mutations), rejected_reason=decision.reason_code)
        evidence = Artifact(task_id=invocation.task_id, invocation_id=invocation.id,
            artifact_type=ArtifactType.IMPLEMENTATION_PROPOSAL, schema_version="0.1",
            producer_agent=invocation.agent, producer_model=invocation.model, content=content)
        if not decision.allowed:
            failure = MutationFailure(decision.reason_code)
            failure.proposal_artifact = evidence
            raise failure
        with UnitOfWork(self.factory) as uow:
            uow.artifacts.add(evidence)
            uow.history.append_event(Event(task_id=invocation.task_id, event_type="MUTATION_RESERVED",
                actor=dict(type="ORCHESTRATOR", id="qa-sentinel"),
                correlation=dict(invocation_id=invocation.id, artifact_id=evidence.id),
                payload=dict(plan_artifact_id=str(context.plan_artifact_id), reason_code=decision.reason_code,
                    workspace_identity=self.service.workspace_identity, model_metadata=metadata.model_dump(mode="json"))))
            uow.commit()
        result = self.service.apply(context.plan, context.source_files, proposal)
        if result.rollback == "FAILED":
            # Preserve the uncertain outcome when persistence is available, without
            # resolving STARTED or claiming canonical success.
            try:
                with UnitOfWork(self.factory) as uow:
                    uow.history.append_event(Event(task_id=invocation.task_id,
                        event_type="MUTATION_RECONCILIATION_REQUIRED",
                        actor=dict(type="ORCHESTRATOR", id="qa-sentinel"),
                        correlation=dict(invocation_id=invocation.id, artifact_id=evidence.id),
                        payload=dict(reason_code="MUTATION_ROLLBACK_REQUIRES_RECONCILIATION",
                            result=result.model_dump(mode="json"), workspace_identity=self.service.workspace_identity)))
                    uow.commit()
            except Exception:
                raise MutationReconciliationRequired("MUTATION_ROLLBACK_REQUIRES_RECONCILIATION") from None
            raise MutationReconciliationRequired("MUTATION_ROLLBACK_REQUIRES_RECONCILIATION")
        if not result.success:
            failure = MutationFailure(result.decision.reason_code, application=result.rollback == "SUCCEEDED" or
                                      result.decision.reason_code == "MUTATION_APPLY_FAILED")
            failure.proposal_artifact = evidence
            failure.application_result = result
            raise failure
        return canonical_output(proposal, result.applied), evidence, result
