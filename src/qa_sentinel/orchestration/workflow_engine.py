"""Deterministic, explicitly requested state changes with one atomic commit."""
from datetime import datetime, timezone
from types import MappingProxyType
from uuid import UUID
from sqlalchemy.orm import Session, sessionmaker
from qa_sentinel.domain.enums import TaskState as S, GateResult as R, DecisionType, TestExecutionStatus, TestOutcome
from qa_sentinel.domain.gate import GateEvaluation
from qa_sentinel.domain.decision import DecisionRecord
from qa_sentinel.domain.transition import Transition
from qa_sentinel.domain.event import Event
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from .state_machine import validate_transition, TERMINAL_STATES
from .errors import MissingGateError, GateRejectedError, ResumeStateError

REQUIRED_PASS_GATES = MappingProxyType({
    (S.RESEARCHING, S.PLANNING): "RESEARCH_GATE",
    (S.PLANNING, S.IMPLEMENTING): "PLAN_GATE",
    (S.IMPLEMENTING, S.TESTING): "IMPLEMENTATION_GATE",
    (S.TESTING, S.REVIEWING): "TEST_GATE",
    (S.REVIEWING, S.DONE): "REVIEW_GATE",
})
SOURCE_GATES = MappingProxyType({
    S.RESEARCHING: "RESEARCH_GATE", S.PLANNING: "PLAN_GATE",
    S.IMPLEMENTING: "IMPLEMENTATION_GATE", S.TESTING: "TEST_GATE",
    S.ANALYZING: "ANALYSIS_GATE", S.INVESTIGATING: "INVESTIGATION_GATE",
    S.REVIEWING: "REVIEW_GATE",
})


class WorkflowEngine:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory

    def transition(self, *, task_id: UUID, to_state: S, reason_code: str,
                   reason_details: str, trigger: str = "WORKFLOW_REQUEST",
                   gate_evaluation: GateEvaluation | None = None,
                   evidence_refs: tuple[str, ...] = (), resume_state: S | None = None,
                   allow_same_state: bool = False, invocation_id: UUID | None = None,
                   artifact_id: UUID | None = None, test_run_id: UUID | None = None,
                   increment_defect_cycle: bool = False) -> Transition:
        with UnitOfWork(self.session_factory) as uow:
            task = uow.tasks.get(task_id)
            if task is None:
                raise KeyError(task_id)
            from_state = task.state
            if type(increment_defect_cycle) is not bool or (increment_defect_cycle and
                    (from_state, to_state) != (S.INVESTIGATING, S.IMPLEMENTING)):
                raise ValueError("Defect cycle increment requires an INVESTIGATING -> IMPLEMENTING transition")
            if resume_state is not None and to_state != S.BLOCKED:
                raise ResumeStateError("resume_state may only be supplied when entering BLOCKED")
            effective_resume = task.resume_state if from_state == S.BLOCKED else resume_state
            validate_transition(from_state, to_state, resume_state=effective_resume,
                                allow_same_state=allow_same_state)
            required_gate = REQUIRED_PASS_GATES.get((from_state, to_state))
            if required_gate and gate_evaluation is None:
                raise MissingGateError("This transition requires " + required_gate)
            if gate_evaluation is not None:
                expected = SOURCE_GATES.get(from_state)
                if gate_evaluation.task_id != task_id:
                    raise GateRejectedError("Gate evidence belongs to another task")
                if gate_evaluation.gate_name != expected:
                    raise GateRejectedError("Gate does not match the current workflow stage")
                if not gate_evaluation.checks:
                    raise GateRejectedError("Gate has no structured checks")
                if gate_evaluation.result == R.PASS and any(c.result != R.PASS for c in gate_evaluation.checks):
                    raise GateRejectedError("PASS gate contains non-PASS checks")
                if required_gate and gate_evaluation.result != R.PASS:
                    raise GateRejectedError("Required gate did not PASS")
                if (from_state, to_state) == (S.TESTING, S.ANALYZING) and gate_evaluation.result == R.PASS:
                    raise GateRejectedError("Passing tests do not require failure analysis")
            # Check any supplied entity references without reading/parsing their prose.
            for identifier, repository in ((invocation_id, uow.invocations), (artifact_id, uow.artifacts)):
                if identifier is not None:
                    record = repository.get(identifier)
                    if record is None or record.task_id != task_id:
                        raise GateRejectedError("Evidence reference is missing or belongs to another task")
            if test_run_id is not None:
                run = uow.history.get_test_run(test_run_id)
                if run is None or run.task_id != task_id:
                    raise GateRejectedError("Test run evidence is missing or belongs to another task")
                passing = run.execution_status == TestExecutionStatus.COMPLETED and run.outcome == TestOutcome.PASS
                if to_state in {S.REVIEWING, S.DONE} and not passing:
                    raise GateRejectedError("Supplied deterministic test evidence does not PASS")
                if (from_state, to_state) == (S.TESTING, S.ANALYZING) and passing:
                    raise GateRejectedError("Supplied passing test evidence contradicts failure routing")
            now = datetime.now(timezone.utc)
            refs = list(evidence_refs)
            if gate_evaluation is not None:
                refs.append(str(gate_evaluation.id))
            refs.extend(str(identifier) for identifier in (invocation_id, artifact_id, test_run_id)
                        if identifier is not None)
            decision = DecisionRecord(task_id=task_id, decision_type=DecisionType.TRANSITION,
                                      decision_source="ORCHESTRATOR", reason_code=reason_code,
                                      reason_details=reason_details, evidence_refs=tuple(refs), created_at=now)
            transition = Transition(task_id=task_id, from_state=from_state, to_state=to_state,
                                    trigger=trigger, gate_evaluation_id=None if gate_evaluation is None else gate_evaluation.id,
                                    decision_id=decision.id, created_at=now)
            event = Event(task_id=task_id, event_type="STATE_TRANSITIONED", timestamp=now,
                          actor=dict(type="ORCHESTRATOR", id="qa-sentinel"),
                          correlation=dict(decision_id=decision.id, invocation_id=invocation_id,
                                           artifact_id=artifact_id, test_run_id=test_run_id),
                          payload=dict(from_state=from_state.value, to_state=to_state.value,
                                       reason_code=decision.reason_code,
                                       **({"defect_cycle": task.defect_cycle + 1} if increment_defect_cycle else {})))
            if gate_evaluation is not None:
                uow.history.append_gate_evaluation(gate_evaluation)
            uow.history.append_decision(decision)
            uow.history.append_transition(transition)
            task.state = to_state
            if increment_defect_cycle:
                task.defect_cycle += 1
            task.updated_at = now
            if to_state == S.BLOCKED:
                task.resume_state = resume_state
            elif from_state == S.BLOCKED:
                task.resume_state = None
            if to_state in TERMINAL_STATES:
                task.completed_at = now
            uow.tasks.save(task)
            uow.history.append_event(event)
            uow.commit()
            return transition
