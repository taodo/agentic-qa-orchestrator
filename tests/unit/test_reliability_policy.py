import pytest
from pydantic import ValidationError
from qa_sentinel.domain.enums import ErrorType, TaskState
from qa_sentinel.domain.task import Task
from qa_sentinel.orchestration.reliability_policy import (
    ReliabilityConfig, FailureDisposition as D, RetryDomain as R, RecoveryAction as A,
    RetryRequest, FailureIdentity, InvestigatorContext, BlockerReason,
    evaluate_retry, evaluate_circuit_breaker, can_start_another_defect_cycle,
    evaluate_investigator_escalation, evaluate_blocker, default_disposition,
)


@pytest.mark.parametrize("disposition,attempt,changed,action,code", [
    (D.TRANSIENT, 0, False, A.RETRY, "RETRY_ALLOWED"),
    (D.TRANSIENT, 1, False, A.RETRY, "RETRY_ALLOWED"),
    (D.TRANSIENT, 2, False, A.BLOCK, "RETRY_BUDGET_EXHAUSTED"),
    (D.CORRECTABLE, 0, False, A.DO_NOT_RETRY, "CHANGED_INPUT_REQUIRED"),
    (D.CORRECTABLE, 0, True, A.RETRY, "RETRY_ALLOWED"),
    (D.CORRECTABLE, 2, True, A.BLOCK, "RETRY_BUDGET_EXHAUSTED"),
    (D.STRUCTURAL, 0, False, A.DO_NOT_RETRY, "STRUCTURAL_FAILURE"),
    (D.STRUCTURAL, 0, True, A.DO_NOT_RETRY, "STRUCTURAL_FAILURE"),
    (D.TERMINAL, 0, False, A.FAIL, "TERMINAL_FAILURE"),
    (D.TERMINAL, 0, True, A.FAIL, "TERMINAL_FAILURE"),
])
def test_retry_rules(disposition, attempt, changed, action, code):
    result = evaluate_retry(RetryRequest(domain=R.IMPLEMENTATION, disposition=disposition,
                                        current_attempt=attempt, changed_input=changed))
    assert result.action == action and result.reason_code == code
    assert result.allowed == (action == A.RETRY)
    assert result.requires_changed_input == (disposition == D.CORRECTABLE)
    assert result.current_attempt == attempt and result.max_attempts == 2


def test_config_is_deeply_immutable_and_domains_independent():
    budgets = {d: 2 for d in R}
    budgets[R.IMPLEMENTATION] = 0
    config = ReliabilityConfig(retry_budgets=budgets)
    budgets[R.RESEARCH] = 0
    assert config.retry_budgets[R.RESEARCH] == 2
    with pytest.raises(TypeError):
        config.retry_budgets[R.RESEARCH] = 3
    with pytest.raises(ValidationError):
        config.max_defect_cycles = 4
    assert not evaluate_retry(RetryRequest(domain=R.IMPLEMENTATION, disposition=D.TRANSIENT,
                                          current_attempt=0), config).allowed
    assert evaluate_retry(RetryRequest(domain=R.RESEARCH, disposition=D.TRANSIENT,
                                       current_attempt=0), config).allowed
    assert all(v == 2 for v in ReliabilityConfig().retry_budgets.values())


@pytest.mark.parametrize("kwargs", [
    {"retry_budgets": {}}, {"max_defect_cycles": -1}, {"identical_failure_threshold": 0},
    {"investigator_low_confidence": float("nan")}, {"investigator_escalation_limit": True},
    {"retry_budgets": {**{d: 2 for d in R}, "UNKNOWN": 2}},
])
def test_invalid_config_rejected(kwargs):
    with pytest.raises(ValidationError):
        ReliabilityConfig(**kwargs)


@pytest.mark.parametrize("kwargs", [
    {"domain": "UNKNOWN"}, {"current_attempt": -1}, {"current_attempt": True},
    {"changed_input": "yes"}, {"disposition": "guess from prose"},
])
def test_invalid_retry_request_rejected(kwargs):
    with pytest.raises(ValidationError):
        RetryRequest(**{**dict(domain=R.RESEARCH, disposition=D.TRANSIENT, current_attempt=0), **kwargs})


def test_fingerprint_uses_structured_normalized_identity():
    identity = FailureIdentity(test_name=" test_x ", error_class="AssertionError",
                               component="product", normalized_signature="expected != actual")
    equivalent = FailureIdentity(**identity.model_dump())
    assert identity.fingerprint() == equivalent.fingerprint()
    changed = FailureIdentity(**{**identity.model_dump(), "normalized_signature": "other signature"})
    assert identity.fingerprint() != changed.fingerprint()
    # Field boundaries cannot collide through concatenation.
    assert FailureIdentity(test_name="ab", error_class="c", component="x", normalized_signature="s").fingerprint() != \
           FailureIdentity(test_name="a", error_class="bc", component="x", normalized_signature="s").fingerprint()


@pytest.mark.parametrize("count,tripped", [(1, False), (2, False), (3, True), (4, True)])
def test_circuit_boundary(count, tripped):
    result = evaluate_circuit_breaker(count)
    assert result.tripped == tripped and result.threshold == 3
    assert result.recommended_action == (A.BLOCK if tripped else A.DO_NOT_RETRY)
    if tripped:
        assert evaluate_circuit_breaker(count, escalation_available=True).recommended_action == A.ESCALATE


@pytest.mark.parametrize("count,allowed", [(0, True), (2, True), (3, False), (4, False)])
def test_defect_cycle_does_not_mutate_task(count, allowed):
    task = Task(title="Task", requirement="Requirement", defect_cycle=count)
    before = task.model_dump()
    assert can_start_another_defect_cycle(task) == allowed
    assert task.model_dump() == before


@pytest.mark.parametrize("overrides,code", [
    ({"confidence": 0.64}, "LOW_CONFIDENCE"),
    ({"confidence": 0.79, "attempt": 2}, "REPEATED_LOW_CONFIDENCE"),
    ({"alternative_hypotheses": 3}, "MULTIPLE_HYPOTHESES"),
    ({"evidence_conflict": True}, "EVIDENCE_CONFLICT"),
    ({"defect_cycle": 2}, "REPEATED_DEFECT_CYCLE"),
])
def test_escalation_triggers(overrides, code):
    context = InvestigatorContext(**{**dict(confidence=0.9, attempt=1, evidence_refs=("report:1",)), **overrides})
    result = evaluate_investigator_escalation(context)
    assert result.escalate and code in result.reason_codes
    assert (result.source_model, result.target_model) == ("Luna Max", "Sol High")
    assert result.evidence_refs == ("report:1",)
    assert not evaluate_investigator_escalation(
        InvestigatorContext(**{**context.model_dump(), "escalation_count": 1})).escalate


@pytest.mark.parametrize("confidence,attempt", [(0.65, 1), (0.8, 2), (0.9, 1)])
def test_escalation_thresholds_are_strict(confidence, attempt):
    result = evaluate_investigator_escalation(InvestigatorContext(confidence=confidence, attempt=attempt))
    assert not result.escalate and result.reason_codes == ("ESCALATION_NOT_REQUIRED",)


def test_escalation_rules_configurable_and_gate_independent(workflow_outputs):
    from qa_sentinel.orchestration.gates import InvestigationGate
    from uuid import uuid4
    output = workflow_outputs["investigation"].model_copy(update={"confidence": 0.1})
    assert InvestigationGate.evaluate(uuid4(), output).result.value == "PASS"
    config = ReliabilityConfig(investigator_low_confidence=0.1, investigator_repeat_attempt=3,
        investigator_hypothesis_threshold=4, investigator_defect_cycle_threshold=3)
    assert not evaluate_investigator_escalation(InvestigatorContext(
        confidence=0.5, attempt=2, alternative_hypotheses=3, defect_cycle=2), config).escalate


@pytest.mark.parametrize("reason", list(BlockerReason))
def test_blocker_recommends_without_mutating(reason):
    task = Task(title="Task", requirement="Requirement", state=TaskState.RESEARCHING)
    result = evaluate_blocker(reason, task.state, ("evidence:1",))
    assert result.action == A.BLOCK and result.recommended_state == TaskState.BLOCKED
    assert result.resume_state == task.state and result.reason_code == reason.value
    assert task.state == TaskState.RESEARCHING and task.resume_state is None


@pytest.mark.parametrize("state", [TaskState.DONE, TaskState.FAILED, TaskState.BLOCKED])
def test_invalid_blocker_resume(state):
    with pytest.raises(ValueError):
        evaluate_blocker(BlockerReason.EXTERNAL_DEPENDENCY, state)


@pytest.mark.parametrize("error,expected", [
    (ErrorType.AGENT_ERROR, D.STRUCTURAL), (ErrorType.SCHEMA_ERROR, D.CORRECTABLE),
    (ErrorType.TOOL_ERROR, D.CORRECTABLE), (ErrorType.TEST_FAILURE, D.CORRECTABLE),
    (ErrorType.ENVIRONMENT_ERROR, D.TRANSIENT), (ErrorType.POLICY_VIOLATION, D.TERMINAL),
    (ErrorType.WORKFLOW_ERROR, D.STRUCTURAL), (ErrorType.EXTERNAL_BLOCKER, D.STRUCTURAL),
])
def test_error_defaults(error, expected):
    assert default_disposition(error) == expected


def test_error_record_and_explicit_subtypes(bundle):
    assert default_disposition(bundle["error"]) == D.CORRECTABLE
    assert default_disposition(ErrorType.TOOL_ERROR, subtype=D.TRANSIENT) == D.TRANSIENT
    assert default_disposition(ErrorType.AGENT_ERROR, subtype=D.TERMINAL) == D.TERMINAL
    assert default_disposition(ErrorType.TEST_FAILURE, subtype=D.STRUCTURAL) == D.STRUCTURAL
    with pytest.raises(ValueError):
        default_disposition(ErrorType.TEST_FAILURE, subtype=D.TRANSIENT)
    with pytest.raises(ValueError):
        default_disposition(ErrorType.POLICY_VIOLATION, subtype=D.TRANSIENT)
