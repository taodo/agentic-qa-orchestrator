
from uuid import uuid4
import pytest
from qa_sentinel.domain.enums import GateResult as R
from qa_sentinel.schemas.research import ResearchOutput
from qa_sentinel.schemas.plan import PlannerOutput
from qa_sentinel.schemas.implementation import ImplementationOutput
from qa_sentinel.schemas.test_result import TestAnalysisOutput as AnalysisOutput
from qa_sentinel.schemas.investigation import InvestigationOutput
from qa_sentinel.schemas.review import ReviewOutput
from qa_sentinel.orchestration.gates import (
    ResearchGate,PlanGate,ImplementationGate,TestGate as RunGate,
    AnalysisGate,InvestigationGate,ReviewGate,
)
from test_contracts import research,plan,implementation,analysis,investigation,review


def valid_plan():return PlannerOutput.model_validate(plan())


def test_research_complete_blocking_and_incomplete():
    task_id=uuid4()
    data=research();data.update(research_complete=True,unknowns=[])
    obj=ResearchOutput.model_validate(data)
    snapshot=obj.model_dump_json()
    result=ResearchGate.evaluate(task_id,obj)
    assert result.result is R.PASS
    assert result.gate_name=="RESEARCH_GATE"
    assert result.task_id==task_id and result.checks
    assert obj.model_dump_json()==snapshot
    data["research_complete"]=False
    assert ResearchGate.evaluate(task_id,ResearchOutput.model_validate(data)).result is R.FAIL
    data["unknowns"]=[dict(description="Needs information",blocking=True)]
    blocked=ResearchGate.evaluate(task_id,ResearchOutput.model_validate(data))
    assert blocked.result is R.BLOCKED and blocked.blocking_reasons


def test_plan_ready_and_structured_back_to_research_or_blocked():
    task_id=uuid4();data=plan()
    data["open_questions"]=["BLOCKING: this prose is not a routing field"]
    assert PlanGate.evaluate(task_id,PlannerOutput.model_validate(data)).result is R.PASS
    data["decision"]="NEEDS_RESEARCH"
    assert PlanGate.evaluate(task_id,PlannerOutput.model_validate(data)).result is R.FAIL
    data["decision"]="BLOCKED"
    assert PlanGate.evaluate(task_id,PlannerOutput.model_validate(data)).result is R.BLOCKED


@pytest.mark.parametrize("mutation,check",[
    ("duplicate_ac","UNIQUE_CRITERION_IDS"),("duplicate_step","UNIQUE_STEP_IDS"),
    ("unknown_ac","TEST_REFERENCES_EXIST"),("unknown_dependency","DEPENDENCIES_EXIST"),
    ("self_dependency","NO_SELF_DEPENDENCIES"),("empty_steps","STEPS_PRESENT"),
    ("empty_ac","CRITERIA_PRESENT"),
])
def test_plan_invalid_structure(mutation,check):
    data=plan()
    if mutation=="duplicate_ac":data["acceptance_criteria"]*=2
    elif mutation=="duplicate_step":data["implementation_steps"]*=2
    elif mutation=="unknown_ac":data["test_strategy"][0]["acceptance_criteria_refs"]=["unknown"]
    elif mutation=="unknown_dependency":data["implementation_steps"][0]["depends_on"]=["unknown"]
    elif mutation=="self_dependency":data["implementation_steps"][0]["depends_on"]=["step-1"]
    elif mutation=="empty_steps":data["implementation_steps"]=[]
    else:data["acceptance_criteria"]=[]
    gate=PlanGate.evaluate(uuid4(),PlannerOutput.model_validate(data))
    assert gate.result is R.FAIL
    assert any(c.check==check and c.result is R.FAIL for c in gate.checks)


def test_implementation_complete_and_does_not_parse_prose_or_execute_commands():
    data=implementation();data["deviations"]=[]
    data["known_issues"]=["BLOCKING: prose cannot determine workflow"]
    data["commands_executed"]=[dict(command="recorded only",exit_code=99)]
    assert ImplementationGate.evaluate(uuid4(),ImplementationOutput.model_validate(data),valid_plan()).result is R.PASS


@pytest.mark.parametrize("mutation",["missing","extra","replan","blocked_step","skipped","duplicate","failed"])
def test_implementation_insufficient_or_replanning(mutation):
    data=implementation();data["deviations"]=[]
    if mutation=="missing":data["plan_steps"]=[]
    elif mutation=="extra":data["plan_steps"].append(dict(step_id="unknown",status="COMPLETED"))
    elif mutation=="replan":data["deviations"]=[dict(description="Change",requires_replan=True)]
    elif mutation=="blocked_step":data["plan_steps"][0]["status"]="BLOCKED"
    elif mutation=="skipped":data["plan_steps"][0]["status"]="SKIPPED"
    elif mutation=="duplicate":data["plan_steps"]*=2
    else:data["implementation_status"]="FAILED"
    assert ImplementationGate.evaluate(uuid4(),ImplementationOutput.model_validate(data),valid_plan()).result is R.FAIL


def test_implementation_blocked_overrides_insufficient_work():
    data=implementation();data.update(implementation_status="BLOCKED",plan_steps=[])
    assert ImplementationGate.evaluate(uuid4(),ImplementationOutput.model_validate(data),valid_plan()).result is R.BLOCKED


@pytest.mark.parametrize("execution,outcome,expected",[
    ("COMPLETED","PASS",R.PASS),("COMPLETED","FAIL",R.FAIL),("FAILED","UNKNOWN",R.FAIL),
    ("INCOMPLETE","UNKNOWN",R.BLOCKED),("COMPLETED","UNKNOWN",R.FAIL),
])
def test_test_gate_only_uses_deterministic_run(execution,outcome,expected,bundle):
    original=bundle["test_run"]
    run=type(original).model_validate({**original.model_dump(),"execution_status":execution,"outcome":outcome})
    assert RunGate.evaluate(run.task_id,run).result is expected


def test_analysis_sufficiency_and_contradictions():
    task_id=uuid4();data=analysis()
    assert AnalysisGate.evaluate(task_id,AnalysisOutput.model_validate(data)).result is R.PASS
    data["overall_result"]="PASS"
    assert AnalysisGate.evaluate(task_id,AnalysisOutput.model_validate(data)).result is R.FAIL
    data["failure_groups"]=[]
    assert AnalysisGate.evaluate(task_id,AnalysisOutput.model_validate(data)).result is R.PASS
    data["overall_result"]="FAIL"
    assert AnalysisGate.evaluate(task_id,AnalysisOutput.model_validate(data)).result is R.FAIL
    data["overall_result"]="BLOCKED"
    assert AnalysisGate.evaluate(task_id,AnalysisOutput.model_validate(data)).result is R.BLOCKED


def test_investigation_root_cause_evidence_and_structured_requests():
    task_id=uuid4();data=investigation();data["confidence"]=0.01
    assert InvestigationGate.evaluate(task_id,InvestigationOutput.model_validate(data)).result is R.PASS
    data["root_cause"]=None
    assert InvestigationGate.evaluate(task_id,InvestigationOutput.model_validate(data)).result is R.FAIL
    data=investigation();data["evidence"]=[]
    assert InvestigationGate.evaluate(task_id,InvestigationOutput.model_validate(data)).result is R.FAIL
    data["status"]="INSUFFICIENT_EVIDENCE"
    assert InvestigationGate.evaluate(task_id,InvestigationOutput.model_validate(data)).result is R.BLOCKED
    data["additional_evidence_needed"]=["report:2"]
    assert InvestigationGate.evaluate(task_id,InvestigationOutput.model_validate(data)).result is R.PASS
    data["status"]="ESCALATION_RECOMMENDED"
    assert InvestigationGate.evaluate(task_id,InvestigationOutput.model_validate(data)).result is R.FAIL


def approved_review():
    data=review();data.update(decision="APPROVE",issues=[])
    data["requirement_coverage"][0]["status"]="COVERED"
    return data


def test_review_valid_approval():
    assert ReviewGate.evaluate(uuid4(),ReviewOutput.model_validate(approved_review()),valid_plan()).result is R.PASS


@pytest.mark.parametrize("mutation",["high","blocker","uncovered","unverified","missing","no_evidence","test_gaps","request_changes","duplicate"])
def test_review_rejects_insufficient_approval(mutation):
    data=approved_review()
    if mutation in {"high","blocker"}:data["issues"]=[dict(severity=mutation.upper(),description="Issue",evidence_refs=["report:1"])]
    elif mutation=="uncovered":data["requirement_coverage"][0]["status"]="NOT_COVERED"
    elif mutation=="unverified":data["requirement_coverage"][0]["status"]="UNVERIFIED"
    elif mutation=="missing":data["requirement_coverage"]=[]
    elif mutation=="no_evidence":data["requirement_coverage"][0]["evidence_refs"]=[]
    elif mutation=="test_gaps":data["test_gaps"]=["Missing test"]
    elif mutation=="request_changes":data["decision"]="REQUEST_CHANGES"
    else:data["requirement_coverage"]*=2
    assert ReviewGate.evaluate(uuid4(),ReviewOutput.model_validate(data),valid_plan()).result is R.FAIL


@pytest.mark.parametrize("decision",["NEEDS_EVIDENCE","BLOCKED"])
def test_review_blocked(decision):
    data=approved_review();data["decision"]=decision
    assert ReviewGate.evaluate(uuid4(),ReviewOutput.model_validate(data),valid_plan()).result is R.BLOCKED
