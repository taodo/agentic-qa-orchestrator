"""Pure deterministic gates. Structured evidence, never prose, drives checks."""
from uuid import UUID
from qa_sentinel.domain.enums import (
    GateResult as R, PlannerDecision, ImplementationStatus, ImplementationStepStatus,
    TestExecutionStatus, TestOutcome, InvestigationStatus, ReviewDecision,
    ReviewIssueSeverity, CoverageStatus,
)
from qa_sentinel.domain.gate import GateCheck, GateEvaluation
from qa_sentinel.domain.test_run import TestRun
from qa_sentinel.schemas.research import ResearchOutput
from qa_sentinel.schemas.plan import PlannerOutput, ImplementationStepKind
from qa_sentinel.schemas.implementation import ImplementationOutput
from qa_sentinel.schemas.test_result import TestAnalysisOutput
from qa_sentinel.schemas.investigation import InvestigationOutput
from qa_sentinel.schemas.review import ReviewOutput


def _check(name: str, passed: bool, reason: str) -> GateCheck:
    return GateCheck(check=name, result=R.PASS if passed else R.FAIL,
                     reason=None if passed else reason)


def _evaluation(task_id: UUID, name: str, checks: list[GateCheck], *,
                blocked: str | None = None) -> GateEvaluation:
    if blocked is not None:
        checks.append(GateCheck(check="CAN_PROCEED", result=R.BLOCKED, reason=blocked))
    result = R.BLOCKED if blocked else R.FAIL if any(c.result == R.FAIL for c in checks) else R.PASS
    return GateEvaluation(task_id=task_id, gate_name=name, result=result, checks=tuple(checks),
                          blocking_reasons=tuple(c.reason for c in checks if c.result != R.PASS and c.reason))


class ResearchGate:
    @staticmethod
    def evaluate(task_id: UUID, output: ResearchOutput) -> GateEvaluation:
        blocking = any(u.blocking for u in output.unknowns)
        return _evaluation(task_id, "RESEARCH_GATE", [
            _check("RESEARCH_COMPLETE", output.research_complete, "Research is incomplete"),
            _check("NO_BLOCKING_UNKNOWNS", not blocking, "Blocking unknowns exist"),
        ], blocked="Research has blocking unknowns" if blocking else None)


class PlanGate:
    @staticmethod
    def evaluate(task_id: UUID, output: PlannerOutput) -> GateEvaluation:
        ids = [s.id for s in output.implementation_steps]
        ac_ids = [a.id for a in output.acceptance_criteria]
        known = set(ids)
        return _evaluation(task_id, "PLAN_GATE", [
            _check("READY", output.decision == PlannerDecision.READY_FOR_IMPLEMENTATION,
                   "Plan is not ready for implementation"),
            _check("STEPS_PRESENT", bool(ids), "No implementation steps"),
            _check("IMPLEMENTING_STEP_KINDS", all(s.kind in {
                ImplementationStepKind.CODE_CHANGE, ImplementationStepKind.STATIC_REVIEW
            } for s in output.implementation_steps),
                "Executable verification belongs in test_strategy and TESTING, not implementation_steps"),
            _check("CRITERIA_PRESENT", bool(ac_ids), "No acceptance criteria"),
            _check("UNIQUE_STEP_IDS", len(ids) == len(known), "Duplicate step IDs"),
            _check("UNIQUE_CRITERION_IDS", len(ac_ids) == len(set(ac_ids)), "Duplicate criterion IDs"),
            _check("DEPENDENCIES_EXIST", all(d in known for s in output.implementation_steps for d in s.depends_on),
                   "Unknown dependency reference"),
            _check("NO_SELF_DEPENDENCIES", all(s.id not in s.depends_on for s in output.implementation_steps),
                   "Self dependency"),
            _check("TEST_REFERENCES_EXIST", all(ref in set(ac_ids) for item in output.test_strategy
                                                for ref in item.acceptance_criteria_refs),
                   "Unknown test strategy criterion reference"),
        ], blocked="Planner reports BLOCKED" if output.decision == PlannerDecision.BLOCKED else None)


class ImplementationGate:
    @staticmethod
    def evaluate(task_id: UUID, output: ImplementationOutput, plan: PlannerOutput) -> GateEvaluation:
        required = {s.id for s in plan.implementation_steps}
        reported = [s.step_id for s in output.plan_steps]
        return _evaluation(task_id, "IMPLEMENTATION_GATE", [
            _check("IMPLEMENTATION_COMPLETE", output.implementation_status == ImplementationStatus.COMPLETED,
                   "Implementation is not complete"),
            _check("ALL_REQUIRED_STEPS", required <= set(reported), "Required steps missing"),
            _check("NO_EXTRA_STEPS", set(reported) <= required, "Unknown implementation steps"),
            _check("UNIQUE_STEP_RESULTS", len(reported) == len(set(reported)), "Duplicate step results"),
            # Existing contracts cannot associate a justification with a skipped step.
            _check("REQUIRED_WORK_COMPLETE", all(s.status == ImplementationStepStatus.COMPLETED
                                                for s in output.plan_steps if s.step_id in required),
                   "Required work incomplete or skipped without structured justification"),
            _check("NO_REPLAN_DEVIATIONS", not any(d.requires_replan for d in output.deviations),
                   "Deviation requires replanning"),
        ], blocked="Implementer reports BLOCKED" if output.implementation_status == ImplementationStatus.BLOCKED else None)


class TestGate:
    @staticmethod
    def evaluate(task_id: UUID, run: TestRun) -> GateEvaluation:
        return _evaluation(task_id, "TEST_GATE", [
            _check("RUN_TASK_MATCHES", run.task_id == task_id, "Test run belongs to another task"),
            _check("EXECUTION_COMPLETED", run.execution_status == TestExecutionStatus.COMPLETED,
                   "Test execution did not complete"),
            _check("TESTS_PASS", run.outcome == TestOutcome.PASS, "Test evidence does not conclude PASS"),
        ], blocked="Test execution incomplete" if run.execution_status == TestExecutionStatus.INCOMPLETE else None)


class AnalysisGate:
    @staticmethod
    def evaluate(task_id: UUID, output: TestAnalysisOutput) -> GateEvaluation:
        consistent = ((output.overall_result == R.PASS and not output.failure_groups) or
                      (output.overall_result == R.FAIL and bool(output.failure_groups)))
        return _evaluation(task_id, "ANALYSIS_GATE", [
            _check("RESULT_GROUPS_CONSISTENT", consistent, "Analysis result and failure groups contradict"),
        ], blocked="Analysis explicitly BLOCKED" if output.overall_result == R.BLOCKED else None)


class InvestigationGate:
    @staticmethod
    def evaluate(task_id: UUID, output: InvestigationOutput) -> GateEvaluation:
        if output.status == InvestigationStatus.ROOT_CAUSE_IDENTIFIED:
            checks = [
                _check("ROOT_CAUSE_PRESENT", bool(output.root_cause), "No root cause"),
                _check("EVIDENCE_PRESENT", bool(output.evidence), "No root cause evidence"),
                _check("ACTION_PRESENT", output.recommended_action is not None, "No recommended action"),
            ]
            return _evaluation(task_id, "INVESTIGATION_GATE", checks)
        if output.status == InvestigationStatus.INSUFFICIENT_EVIDENCE:
            return _evaluation(task_id, "INVESTIGATION_GATE", [
                _check("EVIDENCE_REQUEST_PRESENT", bool(output.additional_evidence_needed),
                       "No structured additional evidence request"),
            ], blocked="Insufficient evidence without an evidence request" if not output.additional_evidence_needed else None)
        return _evaluation(task_id, "INVESTIGATION_GATE", [
            _check("CURRENT_ATTEMPT_SUFFICIENT", False, "Escalation recommended; no escalation policy in Task 3"),
        ])


class ReviewGate:
    @staticmethod
    def evaluate(task_id: UUID, output: ReviewOutput, plan: PlannerOutput) -> GateEvaluation:
        required = {a.id for a in plan.acceptance_criteria}
        coverage_ids = [c.acceptance_criterion_id for c in output.requirement_coverage]
        covered = {c.acceptance_criterion_id for c in output.requirement_coverage if c.status == CoverageStatus.COVERED}
        blocked = output.decision in {ReviewDecision.BLOCKED, ReviewDecision.NEEDS_EVIDENCE}
        return _evaluation(task_id, "REVIEW_GATE", [
            _check("APPROVED", output.decision == ReviewDecision.APPROVE, "Review is not APPROVE"),
            _check("NO_SEVERE_ISSUES", not any(i.severity in {ReviewIssueSeverity.HIGH, ReviewIssueSeverity.BLOCKER}
                                            for i in output.issues), "HIGH or BLOCKER review issue"),
            _check("REQUIRED_CRITERIA_PRESENT", required <= set(coverage_ids), "Required criteria missing"),
            _check("UNIQUE_COVERAGE", len(coverage_ids) == len(set(coverage_ids)), "Duplicate coverage IDs"),
            _check("REQUIRED_CRITERIA_COVERED", required <= covered and all(
                c.status == CoverageStatus.COVERED for c in output.requirement_coverage
                if c.acceptance_criterion_id in required), "Required criterion is not COVERED"),
            _check("COVERAGE_EVIDENCE", all(c.evidence_refs for c in output.requirement_coverage
                                          if c.status == CoverageStatus.COVERED), "Covered criterion lacks evidence"),
            _check("NO_TEST_GAPS", not output.test_gaps, "Review test gaps exist"),
        ], blocked="Review requires evidence or is BLOCKED" if blocked else None)
