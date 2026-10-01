"""Single-task deterministic vertical slice. WorkflowEngine owns every state change."""
from uuid import UUID
from qa_sentinel.agents.base import (
    STATE_AGENTS, ARTIFACT_TYPES, OUTPUT_TYPES, ResearchContext, PlanContext,
    ImplementationContext, AnalysisContext, InvestigationContext, ReviewContext, TestContext,
)
from qa_sentinel.agents.fake import ScenarioExhaustedError
from qa_sentinel.execution.base import TestExecutionPendingError
from qa_sentinel.domain.enums import (
    TaskState as S, AgentName, ArtifactType, GateResult as G, ErrorType,
    PlannerDecision, ReviewDecision, InvestigationActionType, InvestigationStatus,
    TestExecutionStatus, TestOutcome,
)
from qa_sentinel.domain.error import ErrorRecord
from qa_sentinel.domain.event import Event
from qa_sentinel.domain.references import CorrelationRef
from qa_sentinel.domain.test_run import TestRun
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from .agent_execution import AgentExecutor, AgentExecution
from .workflow_engine import WorkflowEngine
from .state_machine import can_transition
from .gates import ResearchGate, PlanGate, ImplementationGate, TestGate, AnalysisGate, InvestigationGate, ReviewGate
from .reliability import ReliabilityService
from .reliability_policy import (
    ReliabilityConfig, RetryDomain, RecoveryAction, BlockerReason, FailureDisposition, can_start_another_defect_cycle,
)

RETRY_DOMAINS = {
    AgentName.RESEARCHER: RetryDomain.RESEARCH, AgentName.PLANNER: RetryDomain.PLANNING,
    AgentName.IMPLEMENTER: RetryDomain.IMPLEMENTATION, AgentName.TEST_ANALYZER: RetryDomain.TEST_EXECUTION,
    AgentName.INVESTIGATOR: RetryDomain.INVESTIGATION, AgentName.REVIEWER: RetryDomain.REVIEW,
}


class RunnerStoppedError(RuntimeError):
    """Safe stop at a stage whose canonical graph has no requested stop transition."""


def planner_target(output):
    return {PlannerDecision.READY_FOR_IMPLEMENTATION: S.IMPLEMENTING,
            PlannerDecision.NEEDS_RESEARCH: S.RESEARCHING, PlannerDecision.BLOCKED: S.BLOCKED}[output.decision]


def investigation_target(output):
    return {InvestigationActionType.CODE_FIX: S.IMPLEMENTING, InvestigationActionType.TEST_FIX: S.IMPLEMENTING,
            InvestigationActionType.MORE_RESEARCH: S.RESEARCHING,
            InvestigationActionType.HUMAN_ACTION: S.BLOCKED}[output.recommended_action.type]


def review_target(output):
    return {ReviewDecision.APPROVE: S.DONE, ReviewDecision.REQUEST_CHANGES: S.IMPLEMENTING,
            ReviewDecision.NEEDS_EVIDENCE: S.BLOCKED, ReviewDecision.BLOCKED: S.BLOCKED}[output.decision]


class WorkflowRunner:
    def __init__(self, session_factory, runtime, test_provider, *, max_steps: int = 50,
                 reliability_config: ReliabilityConfig | None = None):
        if type(max_steps) is not int or max_steps < 1:
            raise ValueError("max_steps must be a positive integer")
        self.session_factory = session_factory
        self.executor = AgentExecutor(session_factory, runtime)
        self.test_provider = test_provider
        self.workflow = WorkflowEngine(session_factory)
        self.reliability = ReliabilityService(session_factory, reliability_config)
        self.max_steps = max_steps

    def _task(self, task_id):
        with UnitOfWork(self.session_factory) as uow:
            task = uow.tasks.get(task_id)
            if task is None:
                raise KeyError(task_id)
            return task

    @staticmethod
    def _artifact(uow, task_id, kind, *, optional=False):
        # Accepted means a completed invocation whose output received a PASS gate
        # on an actual WorkflowEngine transition. UUID repository order is not chronology.
        gates = {g.id: g for g in uow.history.list_gate_evaluations(task_id)}
        passed = {t.decision_id for t in uow.history.list_transitions(task_id)
                  if t.gate_evaluation_id in gates and gates[t.gate_evaluation_id].result == G.PASS}
        accepted = {e.correlation.artifact_id for e in uow.history.list_events(task_id)
                    if e.event_type == "STATE_TRANSITIONED" and e.correlation.decision_id in passed}
        invocations = {i.id: i for i in uow.invocations.list_by_task(task_id) if i.status.value == "COMPLETED"}
        artifacts = [a for a in uow.artifacts.list_by_task(task_id)
                     if a.artifact_type == kind and a.id in accepted and a.invocation_id in invocations]
        if not artifacts:
            if optional:
                return None
            raise RunnerStoppedError("Required accepted artifact is missing: " + kind.value)
        return max(artifacts, key=lambda a: invocations[a.invocation_id].attempt)

    @staticmethod
    def _output(artifact):
        return OUTPUT_TYPES[artifact.producer_agent].model_validate(artifact.content)

    @staticmethod
    def _latest_run(uow, task_id, runs):
        if not runs:
            return None
        if len(runs) == 1:
            return runs[0]
        attempts = {e.correlation.test_run_id: e.payload["attempt"]
                    for e in uow.history.list_events(task_id)
                    if e.event_type in {"TEST_RESULT_RECORDED", "TEST_EXECUTION_STARTED"} and "attempt" in e.payload}
        if any(r.id not in attempts for r in runs) or len({attempts[r.id] for r in runs}) != len(runs):
            raise RunnerStoppedError("Test evidence has ambiguous durable attempt ordering")
        return max(runs, key=lambda r: attempts[r.id])

    @staticmethod
    def _run_for(uow, task_id, implementation_id):
        runs = [r for r in uow.history.list_test_runs(task_id) if r.implementation_artifact_id == implementation_id]
        run = WorkflowRunner._latest_run(uow, task_id, runs)
        if run is None:
            raise RunnerStoppedError("Required test evidence is missing")
        return run

    def build_context(self, task, agent):
        with UnitOfWork(self.session_factory) as uow:
            attempt = 1 + sum(i.agent == agent for i in uow.invocations.list_by_task(task.id))
            base = dict(task_id=task.id, attempt=attempt)
            if agent == AgentName.RESEARCHER:
                prior = self._artifact(uow, task.id, ArtifactType.RESEARCH, optional=True)
                refs = () if prior is None else (str(prior.id),)
                return ResearchContext(**base, requirement=task.requirement, evidence_refs=refs,
                                       prior_research_ref=None if prior is None else prior.id)
            if agent == AgentName.PLANNER:
                research = self._artifact(uow, task.id, ArtifactType.RESEARCH)
                return PlanContext(**base, requirement=task.requirement, research=self._output(research),
                    research_artifact_id=research.id, evidence_refs=(str(research.id),))
            implementation = self._artifact(uow, task.id, ArtifactType.IMPLEMENTATION,
                                            optional=agent == AgentName.IMPLEMENTER)
            if agent == AgentName.IMPLEMENTER:
                plan = self._artifact(uow, task.id, ArtifactType.PLAN)
                investigation = self._artifact(uow, task.id, ArtifactType.INVESTIGATION, optional=True)
                refs = tuple(str(a.id) for a in (plan, implementation, investigation) if a is not None)
                return ImplementationContext(**base, plan=self._output(plan), plan_artifact_id=plan.id,
                    previous_implementation_ref=None if implementation is None else implementation.id,
                    investigation=None if investigation is None else self._output(investigation), evidence_refs=refs)
            run = self._run_for(uow, task.id, implementation.id)
            shared = dict(test_run=run, implementation=self._output(implementation),
                          implementation_artifact_id=implementation.id)
            refs = (str(implementation.id), str(run.id))
            if agent == AgentName.TEST_ANALYZER:
                return AnalysisContext(**base, **shared, evidence_refs=refs)
            if agent == AgentName.INVESTIGATOR:
                analysis = self._artifact(uow, task.id, ArtifactType.TEST_ANALYSIS)
                return InvestigationContext(**base, **shared, analysis=self._output(analysis),
                    analysis_artifact_id=analysis.id, evidence_refs=(*refs, str(analysis.id)))
            plan = self._artifact(uow, task.id, ArtifactType.PLAN)
            return ReviewContext(**base, **shared, requirement=task.requirement,
                plan=self._output(plan), plan_artifact_id=plan.id, evidence_refs=(*refs, str(plan.id)))

    def run(self, task_id: UUID):
        for _ in range(self.max_steps):
            task = self._task(task_id)
            if task.state in {S.DONE, S.FAILED, S.BLOCKED}:
                return task
            try:
                self._step(task)
            except RunnerStoppedError:
                self._workflow_error(task.id, "RUNTIME_EVIDENCE_UNAVAILABLE")
                raise
        task = self._task(task_id)
        if task.state not in {S.DONE, S.FAILED, S.BLOCKED}:
            self._workflow_error(task_id, "RUNTIME_STEP_LIMIT")
            self._stop(task, "RUNTIME_STEP_LIMIT", BlockerReason.RECOVERY_BUDGET_EXHAUSTED)
        return self._task(task_id)

    def _step(self, task):
        if task.state == S.CREATED:
            self.workflow.transition(task_id=task.id, to_state=S.RESEARCHING,
                reason_code="START_RESEARCH", reason_details="Start deterministic workflow")
            return
        if task.state == S.TESTING:
            self._testing(task)
            return
        agent = STATE_AGENTS[task.state]
        if agent == AgentName.INVESTIGATOR and self._circuit_tripped(task):
            self._stop(task, "CIRCUIT_BREAKER_TRIPPED", BlockerReason.RECOVERY_BUDGET_EXHAUSTED)
            return
        execution = self._pending(task, agent)
        if execution is None:
            context = self.build_context(task, agent)
            execution = self.executor.execute(agent, context)
        if execution.error is not None:
            self._recover(task, agent, execution)
            return
        self._agent_route(task, agent, execution)

    def _pending(self, task, agent):
        # Reuse a committed output if completion succeeded but its transition did not.
        with UnitOfWork(self.session_factory) as uow:
            invocation = None if task.current_invocation_id is None else uow.invocations.get(task.current_invocation_id)
            if invocation is None or invocation.agent != agent:
                return None
            if invocation.status.value == "STARTED":
                raise RunnerStoppedError("An unfinished invocation requires explicit reconciliation")
            if invocation.status.value != "COMPLETED":
                scheduled = any(e.event_type == "RETRY_SCHEDULED" and e.correlation.invocation_id == invocation.id
                                for e in uow.history.list_events(task.id))
                if not scheduled:
                    raise RunnerStoppedError("Failed invocation has no committed retry reservation")
                return None
            transitioned = any(e.event_type == "STATE_TRANSITIONED" and e.correlation.invocation_id == invocation.id
                               for e in uow.history.list_events(task.id))
            if transitioned:
                return None
            artifacts = [a for a in uow.artifacts.list_by_task(task.id) if a.invocation_id == invocation.id]
            if len(artifacts) != 1:
                raise RunnerStoppedError("Completed invocation has ambiguous output evidence")
            artifact = artifacts[0]
            return AgentExecution(invocation=invocation, artifact=artifact, output=self._output(artifact))

    def _recover(self, task, agent, execution):
        correlation = CorrelationRef(invocation_id=execution.invocation.id)
        if execution.blocker_reason is not None:
            self._stop(task, execution.blocker_reason.value, execution.blocker_reason, correlation=correlation)
            return
        domain = RetryDomain.SCHEMA_VALIDATION if execution.error.error_type == ErrorType.SCHEMA_ERROR else RETRY_DOMAINS[agent]
        decision = self.reliability.retry(task_id=task.id, domain=domain, disposition=execution.disposition,
            changed_input=execution.changed_input, evidence_refs=(str(execution.error.id),), correlation=correlation)
        if not decision.allowed:
            self._stop(task, decision.reason_code, BlockerReason.RECOVERY_BUDGET_EXHAUSTED,
                       correlation=correlation, terminal=decision.action == RecoveryAction.FAIL)

    def _agent_route(self, task, agent, execution):
        output = execution.output
        correlation = CorrelationRef(invocation_id=execution.invocation.id, artifact_id=execution.artifact.id)
        repair = False
        if agent == AgentName.RESEARCHER:
            gate, target = ResearchGate.evaluate(task.id, output), S.PLANNING
        elif agent == AgentName.PLANNER:
            gate, target = PlanGate.evaluate(task.id, output), planner_target(output)
        elif agent == AgentName.IMPLEMENTER:
            with UnitOfWork(self.session_factory) as uow:
                plan = self._output(self._artifact(uow, task.id, ArtifactType.PLAN))
            gate, target = ImplementationGate.evaluate(task.id, output, plan), S.TESTING
        elif agent == AgentName.TEST_ANALYZER:
            gate, target = AnalysisGate.evaluate(task.id, output), S.INVESTIGATING
            # A sufficient PASS/no-failures analysis cannot override a deterministic FAIL run.
            if output.overall_result != G.FAIL:
                self._workflow_error(task.id, "ANALYSIS_CONTRADICTS_TEST_FAILURE")
                self._stop(task, "ANALYSIS_CONTRADICTS_TEST_FAILURE", BlockerReason.REQUIREMENT_AMBIGUITY, gate, correlation)
                return
        elif agent == AgentName.INVESTIGATOR:
            gate, target = InvestigationGate.evaluate(task.id, output), investigation_target(output)
            if output.status != InvestigationStatus.ROOT_CAUSE_IDENTIFIED and target == S.IMPLEMENTING:
                self._stop(task, "INVESTIGATION_NOT_IDENTIFIED", BlockerReason.REQUIREMENT_AMBIGUITY, gate, correlation)
                return
            repair = target == S.IMPLEMENTING
            if repair and not can_start_another_defect_cycle(task, self.reliability.config):
                self._stop(task, "DEFECT_CYCLE_EXHAUSTED", BlockerReason.RECOVERY_BUDGET_EXHAUSTED, gate, correlation)
                return
        else:
            with UnitOfWork(self.session_factory) as uow:
                plan = self._output(self._artifact(uow, task.id, ArtifactType.PLAN))
                implementation = self._artifact(uow, task.id, ArtifactType.IMPLEMENTATION)
                run = self._run_for(uow, task.id, implementation.id)
            gate, target = ReviewGate.evaluate(task.id, output, plan), review_target(output)
            correlation = CorrelationRef(**{**correlation.model_dump(), "test_run_id": run.id})
        if target == S.BLOCKED:
            self._stop(task, "ACTOR_REQUIRES_RESOLUTION", BlockerReason.REQUIREMENT_AMBIGUITY, gate, correlation)
            return
        # NEEDS_RESEARCH and REQUEST_CHANGES are explicit enum routes even with FAIL gates.
        backward = ((agent == AgentName.PLANNER and target == S.RESEARCHING) or
                    (agent == AgentName.REVIEWER and target == S.IMPLEMENTING))
        if gate.result != G.PASS and not backward:
            self._stop(task, "STAGE_GATE_REJECTED", BlockerReason.REQUIREMENT_AMBIGUITY, gate, correlation)
            return
        self.workflow.transition(task_id=task.id, to_state=target, gate_evaluation=gate,
            reason_code="STRUCTURED_STAGE_ROUTE", reason_details="Route selected from typed output and deterministic gate",
            invocation_id=correlation.invocation_id, artifact_id=correlation.artifact_id,
            test_run_id=correlation.test_run_id, increment_defect_cycle=repair)

    def _testing(self, task):
        with UnitOfWork(self.session_factory) as uow:
            implementation = self._artifact(uow, task.id, ArtifactType.IMPLEMENTATION)
            runs = uow.history.list_test_runs(task.id)
            matching = [r for r in runs if r.implementation_artifact_id == implementation.id]
            previous = self._latest_run(uow, task.id, matching)
            retry_reserved = previous is not None and any(
                e.event_type == "RETRY_SCHEDULED" and e.correlation.test_run_id == previous.id
                for e in uow.history.list_events(task.id))
            context = TestContext(task_id=task.id, attempt=len(runs) + 1,
                implementation_artifact_id=implementation.id, evidence_refs=(str(implementation.id),))
        new = previous is None or (retry_reserved and
            (previous.execution_status != TestExecutionStatus.COMPLETED or previous.outcome == TestOutcome.UNKNOWN))
        if new:
            try:
                run = self.test_provider.run(context)
            except ScenarioExhaustedError:
                self._workflow_error(task.id, "TEST_SCENARIO_EXHAUSTED")
                self._stop(task, "TEST_SCENARIO_EXHAUSTED", BlockerReason.EXTERNAL_DEPENDENCY)
                return
            except TestExecutionPendingError:
                self._workflow_error(task.id, "TEST_EXECUTION_RECONCILIATION_REQUIRED")
                self._stop(task, "TEST_EXECUTION_RECONCILIATION_REQUIRED", BlockerReason.EXTERNAL_DEPENDENCY)
                return
            if type(run) is not TestRun:
                raise RunnerStoppedError("Test provider must return a typed TestRun")
            run = TestRun.model_validate(run.model_dump())
            if run.task_id != task.id or run.implementation_artifact_id != implementation.id:
                raise RunnerStoppedError("Test provider returned unrelated evidence")
            with UnitOfWork(self.session_factory) as uow:
                persisted = uow.history.get_test_run(run.id)
                if persisted is None:
                    uow.history.append_test_run(run)
                    uow.history.append_event(Event(task_id=task.id, event_type="TEST_RESULT_RECORDED",
                        actor=dict(type="ORCHESTRATOR", id="qa-sentinel"),
                        correlation=dict(test_run_id=run.id, artifact_id=implementation.id),
                        payload=dict(execution_status=run.execution_status.value, outcome=run.outcome.value,
                                     attempt=context.attempt)))
                elif persisted != run:
                    raise RunnerStoppedError("Provider returned evidence different from its persisted record")
                uow.commit()
        else:
            run = previous
        gate = TestGate.evaluate(task.id, run)
        correlation = CorrelationRef(test_run_id=run.id, artifact_id=implementation.id)
        if run.execution_status != TestExecutionStatus.COMPLETED or run.outcome == TestOutcome.UNKNOWN:
            failure = self.test_provider.execution_failure(run)
            decision = self.reliability.retry(task_id=task.id, domain=RetryDomain.TEST_EXECUTION,
                disposition=FailureDisposition.STRUCTURAL if failure is None else failure.disposition,
                changed_input=False if failure is None else failure.changed_input,
                evidence_refs=(str(run.id),) if failure is None else failure.evidence_refs, correlation=correlation)
            if not decision.allowed:
                self._workflow_error(task.id, "TEST_PROVIDER_INCONCLUSIVE")
                self._stop(task, decision.reason_code, BlockerReason.EXTERNAL_DEPENDENCY, gate, correlation,
                           terminal=decision.action == RecoveryAction.FAIL)
            return
        if new and run.outcome == TestOutcome.FAIL:
            identity = self.test_provider.failure_identity(context)
            if identity is not None:
                self.reliability.record_failure(task_id=task.id, identity=identity, correlation=correlation)
        self.workflow.transition(task_id=task.id, to_state=S.REVIEWING if gate.result == G.PASS else S.ANALYZING,
            gate_evaluation=gate, test_run_id=run.id, artifact_id=implementation.id,
            reason_code="TESTS_PASSED" if gate.result == G.PASS else "TESTS_FAILED",
            reason_details="Deterministic test evidence controls routing")

    def _circuit_tripped(self, task):
        with UnitOfWork(self.session_factory) as uow:
            implementation = self._artifact(uow, task.id, ArtifactType.IMPLEMENTATION)
            run = self._run_for(uow, task.id, implementation.id)
            return any(e.event_type == "CIRCUIT_BREAKER_TRIPPED" and e.correlation.test_run_id == run.id
                       for e in uow.history.list_events(task.id))

    def _workflow_error(self, task_id, code):
        with UnitOfWork(self.session_factory) as uow:
            uow.history.append_error(ErrorRecord(task_id=task_id, error_type="WORKFLOW_ERROR", code=code,
                severity="ERROR", owner="ORCHESTRATOR", retryable=False, blocking=True,
                source=dict(actor=dict(type="ORCHESTRATOR", id="qa-sentinel")),
                message="Runtime stopped because deterministic progression is unavailable."))
            uow.commit()

    def _stop(self, task, code, blocker, gate=None, correlation=None, *, terminal=False):
        correlation = correlation or CorrelationRef()
        if terminal and can_transition(task.state, S.FAILED):
            self.workflow.transition(task_id=task.id, to_state=S.FAILED, gate_evaluation=gate,
                reason_code=code, reason_details="Stop automatic recovery for this operation",
                invocation_id=correlation.invocation_id, artifact_id=correlation.artifact_id,
                test_run_id=correlation.test_run_id)
            return
        self.reliability.block(task_id=task.id, reason=blocker, resume_state=task.state,
                               evidence_refs=(code,), correlation=correlation)
        if not can_transition(task.state, S.BLOCKED, resume_state=task.state):
            self._workflow_error(task.id, "STOP_TRANSITION_UNAVAILABLE")
            raise RunnerStoppedError("Canonical graph has no BLOCKED edge from " + task.state.value)
        self.workflow.transition(task_id=task.id, to_state=S.BLOCKED, resume_state=task.state,
            gate_evaluation=gate, reason_code=code, reason_details="External resolution is required",
            invocation_id=correlation.invocation_id, artifact_id=correlation.artifact_id,
            test_run_id=correlation.test_run_id)
