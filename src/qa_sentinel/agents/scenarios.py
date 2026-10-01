"""Reusable division demonstration. All implementation and test evidence is synthetic."""
from qa_sentinel.domain.enums import AgentName
from qa_sentinel.schemas.research import ResearchOutput
from qa_sentinel.schemas.plan import PlannerOutput
from qa_sentinel.schemas.implementation import ImplementationOutput
from qa_sentinel.schemas.test_result import TestAnalysisOutput
from qa_sentinel.schemas.investigation import InvestigationOutput
from qa_sentinel.schemas.review import ReviewOutput
from qa_sentinel.execution.fake import FakeTestResult
from qa_sentinel.orchestration.reliability_policy import FailureIdentity
from .fake import FakeScenario, FakeResponse

DIVISION_REQUIREMENT = "Add division support and reject division by zero."


def division_scenario(*, repair: bool = False):
    research = ResearchOutput(summary="Simple calculator supports arithmetic operations",
        findings=[dict(summary="Division requires a zero-divisor guard", evidence=["fake:calculator-context"], confidence=1.0)],
        dependencies=[], constraints=["Preserve existing operations"], risks=[], unknowns=[],
        recommendations=["Add division and test the zero-divisor guard"], research_complete=True)
    plan = PlannerOutput(decision="READY_FOR_IMPLEMENTATION", summary="Add guarded division", assumptions=[],
        implementation_steps=[dict(id="step-1", description="Add division and zero-divisor rejection",
                                   files=["calculator.py"], depends_on=[])],
        files_to_create=[], files_to_modify=["calculator.py"],
        acceptance_criteria=[dict(id="AC-1", description="Division returns the quotient", verification="Assert 6 / 2 == 3"),
                             dict(id="AC-2", description="Zero divisor is rejected", verification="Assert zero-divisor error")],
        test_strategy=[dict(description="Verify division and zero-divisor rejection", acceptance_criteria_refs=["AC-1", "AC-2"])],
        risks=[], rollback_considerations=[], open_questions=[])
    implementation = ImplementationOutput(implementation_status="COMPLETED",
        plan_steps=[dict(step_id="step-1", status="COMPLETED")],
        changed_files=[dict(path="calculator.py", change_type="MODIFIED", reason="Synthetic division implementation")],
        tests_added_or_modified=["fake:test_division", "fake:test_division_by_zero"],
        commands_executed=[], deviations=[], assumptions=[], known_issues=[])
    analysis = TestAnalysisOutput(overall_result="FAIL", failure_groups=[dict(tests=["test_division_by_zero"],
        classification="LIKELY_PRODUCT_DEFECT", summary="Missing guard", evidence=["fake:division-report"],
        confidence=0.95, requires_investigation=True)])
    investigation = InvestigationOutput(status="ROOT_CAUSE_IDENTIFIED", root_cause="Zero-divisor guard missing",
        evidence=["fake:division-report"], confidence=0.95,
        recommended_action=dict(type="CODE_FIX", description="Add zero-divisor guard"),
        alternative_hypotheses=[], additional_evidence_needed=[])
    review = ReviewOutput(decision="APPROVE", requirement_coverage=[
        dict(acceptance_criterion_id=identifier, status="COVERED", summary="Synthetic test evidence verifies behavior",
             evidence_refs=["fake:division-report"]) for identifier in ("AC-1", "AC-2")],
        issues=[], test_gaps=[], implementation_risks=[], unverified_assumptions=[])
    scenario = FakeScenario(responses={
        AgentName.RESEARCHER: (FakeResponse(output=research),),
        AgentName.PLANNER: (FakeResponse(output=plan),),
        AgentName.IMPLEMENTER: (FakeResponse(output=implementation),) * (2 if repair else 1),
        AgentName.TEST_ANALYZER: (FakeResponse(output=analysis),),
        AgentName.INVESTIGATOR: (FakeResponse(output=investigation),),
        AgentName.REVIEWER: (FakeResponse(output=review),),
    })
    passed = FakeTestResult(outcome="PASS", passed_count=2)
    failed = FakeTestResult(outcome="FAIL", passed_count=1, failed_count=1,
        failure_identity=FailureIdentity(test_name="test_division_by_zero", error_class="AssertionError",
                                         component="calculator", normalized_signature="zero divisor accepted"))
    return scenario, (failed, passed) if repair else (passed,)
