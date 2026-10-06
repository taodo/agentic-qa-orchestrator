"""Pure structured reliability policies. No persistence, execution, or state changes."""
from enum import StrEnum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator
from qa_sentinel.domain.enums import ErrorType, TaskState
from qa_sentinel.domain.error import ErrorRecord
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.types import NonBlank, Count, Attempt, Confidence


class FailureDisposition(StrEnum):
    TRANSIENT = "TRANSIENT"
    CORRECTABLE = "CORRECTABLE"
    STRUCTURAL = "STRUCTURAL"
    TERMINAL = "TERMINAL"


class RetryDomain(StrEnum):
    SCHEMA_VALIDATION = "SCHEMA_VALIDATION"
    RESEARCH = "RESEARCH"
    PLANNING = "PLANNING"
    IMPLEMENTATION = "IMPLEMENTATION"
    TEST_EXECUTION = "TEST_EXECUTION"
    INVESTIGATION = "INVESTIGATION"
    REVIEW = "REVIEW"


class RecoveryAction(StrEnum):
    RETRY = "RETRY"
    DO_NOT_RETRY = "DO_NOT_RETRY"
    ESCALATE = "ESCALATE"
    BLOCK = "BLOCK"
    FAIL = "FAIL"


class BlockerReason(StrEnum):
    MISSING_CREDENTIAL = "MISSING_CREDENTIAL"
    REQUIREMENT_AMBIGUITY = "REQUIREMENT_AMBIGUITY"
    SECURITY_DECISION = "SECURITY_DECISION"
    DESTRUCTIVE_CHANGE_APPROVAL = "DESTRUCTIVE_CHANGE_APPROVAL"
    EXTERNAL_DEPENDENCY = "EXTERNAL_DEPENDENCY"
    ARCHITECTURE_APPROVAL = "ARCHITECTURE_APPROVAL"
    RECOVERY_BUDGET_EXHAUSTED = "RECOVERY_BUDGET_EXHAUSTED"


class FrozenRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReliabilityConfig(FrozenRecord):
    retry_budgets: Mapping[RetryDomain, Count] = Field(default_factory=lambda: {d: 2 for d in RetryDomain})
    max_defect_cycles: Count = 3
    identical_failure_threshold: Attempt = 3
    investigator_escalation_limit: Count = 1
    investigator_low_confidence: Confidence = 0.65
    investigator_repeat_confidence: Confidence = 0.80
    investigator_repeat_attempt: Attempt = 2
    investigator_hypothesis_threshold: Attempt = 3
    investigator_defect_cycle_threshold: Count = 2
    investigator_primary_model: NonBlank = "Luna Max"
    investigator_escalated_model: NonBlank = "Sol High"

    @model_validator(mode="after")
    def freeze_budgets(self):
        if set(self.retry_budgets) != set(RetryDomain):
            raise ValueError("Configure every retry domain exactly once")
        object.__setattr__(self, "retry_budgets", MappingProxyType(dict(self.retry_budgets)))
        return self


class RetryRequest(FrozenRecord):
    domain: RetryDomain
    disposition: FailureDisposition
    current_attempt: Count
    changed_input: bool = Field(default=False, strict=True)


class RetryDecision(FrozenRecord):
    action: RecoveryAction
    domain: RetryDomain
    allowed: bool
    current_attempt: Count
    max_attempts: Count
    disposition: FailureDisposition
    reason_code: NonBlank
    reason: NonBlank
    requires_changed_input: bool


def evaluate_retry(request: RetryRequest, config: ReliabilityConfig | None = None) -> RetryDecision:
    config = config or ReliabilityConfig()
    limit = config.retry_budgets[request.domain]
    action, code, reason = RecoveryAction.DO_NOT_RETRY, "STRUCTURAL_FAILURE", "Same-operation recovery requires a different route."
    if request.disposition == FailureDisposition.TERMINAL:
        action, code, reason = RecoveryAction.FAIL, "TERMINAL_FAILURE", "Stop automatic recovery for this operation."
    elif request.disposition == FailureDisposition.STRUCTURAL:
        pass
    elif request.current_attempt >= limit:
        action, code, reason = RecoveryAction.BLOCK, "RETRY_BUDGET_EXHAUSTED", "Domain retry budget is exhausted."
    elif request.disposition == FailureDisposition.CORRECTABLE and not request.changed_input:
        code, reason = "CHANGED_INPUT_REQUIRED", "Relevant input or evidence must change before retry."
    else:
        action, code, reason = RecoveryAction.RETRY, "RETRY_ALLOWED", "Structured failure permits retry within the domain budget."
    return RetryDecision(action=action, domain=request.domain, allowed=action == RecoveryAction.RETRY,
                         current_attempt=request.current_attempt, max_attempts=limit,
                         disposition=request.disposition, reason_code=code, reason=reason,
                         requires_changed_input=request.disposition == FailureDisposition.CORRECTABLE)


def default_disposition(error: ErrorType | ErrorRecord, *, subtype: FailureDisposition | None = None) -> FailureDisposition:
    error_type = ErrorType(error.error_type if isinstance(error, ErrorRecord) else error)
    if subtype is not None:
        subtype = FailureDisposition(subtype)
        allowed = {
            ErrorType.AGENT_ERROR: set(FailureDisposition),
            ErrorType.TOOL_ERROR: {FailureDisposition.TRANSIENT, FailureDisposition.CORRECTABLE},
            ErrorType.TEST_FAILURE: {FailureDisposition.CORRECTABLE, FailureDisposition.STRUCTURAL},
        }
        if error_type not in allowed or subtype not in allowed[error_type]:
            raise ValueError("Disposition override is incompatible with error type")
        return subtype
    return {
        ErrorType.AGENT_ERROR: FailureDisposition.STRUCTURAL,
        ErrorType.SCHEMA_ERROR: FailureDisposition.CORRECTABLE,
        ErrorType.TOOL_ERROR: FailureDisposition.CORRECTABLE,
        ErrorType.TEST_FAILURE: FailureDisposition.CORRECTABLE,
        ErrorType.ENVIRONMENT_ERROR: FailureDisposition.TRANSIENT,
        ErrorType.POLICY_VIOLATION: FailureDisposition.TERMINAL,
        ErrorType.WORKFLOW_ERROR: FailureDisposition.STRUCTURAL,
        ErrorType.EXTERNAL_BLOCKER: FailureDisposition.STRUCTURAL,
    }[error_type]


class FailureIdentity(FrozenRecord):
    test_name: NonBlank
    error_class: NonBlank
    component: NonBlank
    normalized_signature: NonBlank

    def fingerprint(self) -> str:
        # Inputs are already normalized by the caller; only boundary whitespace is stripped.
        data = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return sha256(data.encode("utf-8")).hexdigest()


class CircuitBreakerDecision(FrozenRecord):
    tripped: bool
    occurrence_count: Count
    threshold: Attempt
    reason_code: NonBlank
    recommended_action: RecoveryAction


def evaluate_circuit_breaker(occurrence_count: int, *, escalation_available: bool = False,
                             config: ReliabilityConfig | None = None) -> CircuitBreakerDecision:
    config = config or ReliabilityConfig()
    tripped = occurrence_count >= config.identical_failure_threshold
    return CircuitBreakerDecision(tripped=tripped, occurrence_count=occurrence_count,
        threshold=config.identical_failure_threshold,
        reason_code="CIRCUIT_BREAKER_TRIPPED" if tripped else "CIRCUIT_BREAKER_CLOSED",
        recommended_action=(RecoveryAction.ESCALATE if escalation_available else RecoveryAction.BLOCK)
        if tripped else RecoveryAction.DO_NOT_RETRY)


def can_start_another_defect_cycle(task: Task, config: ReliabilityConfig | None = None) -> bool:
    return task.defect_cycle < (config or ReliabilityConfig()).max_defect_cycles


class InvestigatorContext(FrozenRecord):
    confidence: Confidence
    attempt: Attempt
    alternative_hypotheses: Count = 0
    evidence_conflict: bool = Field(default=False, strict=True)
    defect_cycle: Count = 0
    escalation_count: Count = 0
    evidence_refs: tuple[NonBlank, ...] = ()


class EscalationDecision(FrozenRecord):
    escalate: bool
    source_model: NonBlank
    target_model: NonBlank
    reason_codes: tuple[NonBlank, ...]
    escalation_count: Count
    max_escalations: Count
    evidence_refs: tuple[NonBlank, ...]


def evaluate_investigator_escalation(context: InvestigatorContext,
                                     config: ReliabilityConfig | None = None) -> EscalationDecision:
    config = config or ReliabilityConfig()
    codes = []
    if context.confidence < config.investigator_low_confidence:
        codes.append("LOW_CONFIDENCE")
    if context.attempt >= config.investigator_repeat_attempt and context.confidence < config.investigator_repeat_confidence:
        codes.append("REPEATED_LOW_CONFIDENCE")
    if context.alternative_hypotheses >= config.investigator_hypothesis_threshold:
        codes.append("MULTIPLE_HYPOTHESES")
    if context.evidence_conflict:
        codes.append("EVIDENCE_CONFLICT")
    if context.defect_cycle >= config.investigator_defect_cycle_threshold:
        codes.append("REPEATED_DEFECT_CYCLE")
    exhausted = context.escalation_count >= config.investigator_escalation_limit
    if exhausted:
        codes.append("ESCALATION_BUDGET_EXHAUSTED")
    return EscalationDecision(escalate=bool(codes) and not exhausted,
        source_model=config.investigator_primary_model, target_model=config.investigator_escalated_model,
        reason_codes=tuple(codes or ["ESCALATION_NOT_REQUIRED"]), escalation_count=context.escalation_count,
        max_escalations=config.investigator_escalation_limit, evidence_refs=context.evidence_refs)


class BlockingDecision(FrozenRecord):
    action: RecoveryAction = RecoveryAction.BLOCK
    recommended_state: TaskState = TaskState.BLOCKED
    blocker_reason: BlockerReason
    resume_state: TaskState
    reason_code: NonBlank
    reason: NonBlank
    evidence_refs: tuple[NonBlank, ...] = ()


def evaluate_blocker(reason: BlockerReason, resume_state: TaskState,
                     evidence_refs: tuple[str, ...] = ()) -> BlockingDecision:
    reason, resume_state = BlockerReason(reason), TaskState(resume_state)
    if resume_state in {TaskState.BLOCKED, TaskState.DONE, TaskState.FAILED}:
        raise ValueError("Resume state must be an active nonterminal state")
    return BlockingDecision(blocker_reason=reason, resume_state=resume_state, reason_code=reason.value,
                            reason="External or human resolution is required.", evidence_refs=evidence_refs)
