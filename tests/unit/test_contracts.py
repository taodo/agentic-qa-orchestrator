from datetime import datetime, timezone
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError
from qa_sentinel.domain.enums import TaskState, AgentName, ErrorType, ErrorOwner
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.artifact import Artifact
from qa_sentinel.domain.invocation import AgentInvocation
from qa_sentinel.domain.decision import DecisionRecord
from qa_sentinel.domain.error import ErrorRecord
from qa_sentinel.domain.gate import GateEvaluation
from qa_sentinel.domain.transition import Transition
from qa_sentinel.domain.event import Event
from qa_sentinel.domain.audit import AuditRecord
from qa_sentinel.domain.test_run import TestRun as RunRecord
from qa_sentinel.schemas.research import ResearchOutput
from qa_sentinel.schemas.plan import PlannerOutput
from qa_sentinel.schemas.implementation import ImplementationOutput
from qa_sentinel.schemas.test_result import TestAnalysisOutput as AnalysisOutput
from qa_sentinel.schemas.investigation import InvestigationOutput
from qa_sentinel.schemas.review import ReviewOutput


def research():
    return dict(summary="Research", findings=[dict(summary="Finding", evidence=["doc:1"], confidence=0.8)], dependencies=[], constraints=[], risks=[], unknowns=[dict(description="Unknown", blocking=True)], recommendations=[], research_complete=False)


def plan():
    return dict(decision="READY_FOR_IMPLEMENTATION", summary="Plan", assumptions=[], implementation_steps=[dict(id="step-1", description="Implement behavior", files=["app.py"], depends_on=[])], files_to_create=[], files_to_modify=[], acceptance_criteria=[dict(id="AC-1", description="Expected behavior", verification="Assert expected result")], test_strategy=[dict(description="Test behavior", acceptance_criteria_refs=["AC-1"])], risks=[], rollback_considerations=[], open_questions=[])


def implementation():
    return dict(implementation_status="COMPLETED", plan_steps=[dict(step_id="step-1", status="COMPLETED")], changed_files=[dict(path="app.py", change_type="MODIFIED", reason="Implement behavior")], tests_added_or_modified=[], commands_executed=[dict(command="recorded command", exit_code=0)], deviations=[dict(description="Changed approach", requires_replan=True)], assumptions=[], known_issues=[])


def analysis():
    return dict(overall_result="FAIL", failure_groups=[dict(tests=["test_example"], classification="LIKELY_PRODUCT_DEFECT", summary="Mismatch", evidence=["report:1"], confidence=0.9, requires_investigation=True)])


def investigation():
    return dict(status="ROOT_CAUSE_IDENTIFIED", root_cause="Wrong condition", evidence=["report:1"], confidence=0.9, recommended_action=dict(type="CODE_FIX", description="Fix condition"), alternative_hypotheses=[], additional_evidence_needed=[])


def review():
    return dict(decision="REQUEST_CHANGES", requirement_coverage=[dict(acceptance_criterion_id="AC-1", status="UNVERIFIED", summary="Reviewed", evidence_refs=["report:1"])], issues=[dict(severity="HIGH", description="Defect", evidence_refs=["report:1"])], test_gaps=[], implementation_risks=[], unverified_assumptions=[])


def test_canonical_states_and_agent_names():
    assert {s.value for s in TaskState} == set("CREATED RESEARCHING PLANNING IMPLEMENTING TESTING ANALYZING INVESTIGATING REVIEWING BLOCKED FAILED DONE".split())
    assert {s.value for s in AgentName} == set("RESEARCHER PLANNER IMPLEMENTER TEST_ANALYZER INVESTIGATOR REVIEWER".split())


@pytest.mark.parametrize("model,factory", [(ResearchOutput,research),(PlannerOutput,plan),(ImplementationOutput,implementation),(AnalysisOutput,analysis),(InvestigationOutput,investigation),(ReviewOutput,review)])
def test_valid_outputs_parse_and_roundtrip(model, factory):
    obj=model.model_validate(factory())
    assert model.model_validate_json(obj.model_dump_json()) == obj


@pytest.mark.parametrize("value", [-0.01,1.01,float("nan"),float("inf")])
@pytest.mark.parametrize("model,factory,nested", [(ResearchOutput,research,"findings"),(AnalysisOutput,analysis,"failure_groups"),(InvestigationOutput,investigation,None)])
def test_confidence_bounds(model,factory,nested,value):
    data=factory()
    target=data[nested][0] if nested else data
    target["confidence"]=value
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize("model,factory,field", [(PlannerOutput,plan,"decision"),(ReviewOutput,review,"decision"),(InvestigationOutput,investigation,"status"),(ImplementationOutput,implementation,"implementation_status")])
def test_invalid_decisions(model,factory,field):
    data=factory(); data[field]="DONE"
    with pytest.raises(ValidationError): model.model_validate(data)


@pytest.mark.parametrize("value", ["", "   "])
def test_acceptance_id_required(value):
    data=plan(); data["acceptance_criteria"][0]["id"]=value
    with pytest.raises(ValidationError): PlannerOutput.model_validate(data)


def test_acceptance_id_missing():
    data=plan(); del data["acceptance_criteria"][0]["id"]
    with pytest.raises(ValidationError): PlannerOutput.model_validate(data)


@pytest.mark.parametrize("flag", [True,False])
def test_deviation_replan_flag(flag):
    data=implementation(); data["deviations"][0]["requires_replan"]=flag
    assert ImplementationOutput.model_validate(data).deviations[0].requires_replan is flag


@pytest.mark.parametrize("model,factory,collection,flag", [(ResearchOutput,research,"unknowns","blocking"),(ImplementationOutput,implementation,"deviations","requires_replan")])
def test_explicit_flags_required(model,factory,collection,flag):
    data=factory(); del data[collection][0][flag]
    with pytest.raises(ValidationError): model.model_validate(data)


def test_invalid_failure_classification():
    data=analysis(); data["failure_groups"][0]["classification"]="PRODUCT_DEFECT"
    with pytest.raises(ValidationError): AnalysisOutput.model_validate(data)


def records():
    task=uuid4(); now=datetime.now(timezone.utc)
    return [
        Task(id=task,title="Task",requirement="Requirement"),
        Artifact(task_id=task,artifact_type="RESEARCH",schema_version="0.1",producer_agent="RESEARCHER",content={"summary":"Evidence"}),
        AgentInvocation(task_id=task,agent="RESEARCHER",model="model-id",reasoning_effort="low",attempt=1,status="COMPLETED",started_at=now,finished_at=now),
        DecisionRecord(task_id=task,decision_type="TRANSITION",decision_source="orchestrator",reason_code="READY",reason_details="Evidence accepted"),
        ErrorRecord(task_id=task,error_type="TEST_FAILURE",code="ASSERTION",severity="ERROR",owner="TEST_TARGET",retryable=False,blocking=True,source=dict(actor=dict(type="TOOL", id="test-runner"), invocation_id=uuid4(), tool="pytest"),message="Assertion failed"),
        GateEvaluation(task_id=task,gate_name="review",result="PASS",checks=[dict(check="evidence",result="PASS")]),
        Transition(task_id=task,from_state="CREATED",to_state="RESEARCHING",trigger="start",decision_id=uuid4()),
        Event(task_id=task,event_type="created",actor=dict(type="ORCHESTRATOR", id="qa-sentinel"),correlation=dict(decision_id=uuid4()),payload={"state":"CREATED"}),
        AuditRecord(task_id=task,actor=dict(type="ORCHESTRATOR", id="qa-sentinel"),action="read",resource="artifact",decision="allow",policy="least_privilege",metadata={}),
        RunRecord(task_id=task,implementation_artifact_id=uuid4(),execution_status="COMPLETED",outcome="PASS",environment="local",started_at=now,finished_at=now,passed_count=1,failed_count=0,skipped_count=0),
    ]


@pytest.mark.parametrize("index",range(10))
def test_domain_json_roundtrip(index):
    obj=records()[index]
    data=obj.model_dump(mode="json")
    json.dumps(data,allow_nan=False)
    assert type(obj).model_validate_json(obj.model_dump_json()) == obj


def test_error_distinguishes_product_and_runtime_failures():
    failure=records()[4]
    runtime=ErrorRecord.model_validate({**failure.model_dump(),"error_type":"WORKFLOW_ERROR","owner":"ORCHESTRATOR"})
    assert failure.error_type is ErrorType.TEST_FAILURE
    assert runtime.error_type is ErrorType.WORKFLOW_ERROR
    assert failure.owner is ErrorOwner.TEST_TARGET
    assert runtime.owner is ErrorOwner.ORCHESTRATOR


@pytest.mark.parametrize("result",["PASS","FAIL","BLOCKED"])
def test_canonical_gate_result(result):
    data=records()[5].model_dump(); data["result"]=result
    assert GateEvaluation.model_validate(data).result.value==result


@pytest.mark.parametrize("field",["result","check"])
def test_invalid_gate_result(field):
    data=records()[5].model_dump()
    if field=="result": data["result"]="APPROVE"
    else: data["checks"]= [dict(check="evidence",result="APPROVE")]
    with pytest.raises(ValidationError): GateEvaluation.model_validate(data)


@pytest.mark.parametrize("field",["passed_count","failed_count","skipped_count"])
@pytest.mark.parametrize("value",[-1,1.5,True])
def test_invalid_counts(field,value):
    data=records()[9].model_dump(); data[field]=value
    with pytest.raises(ValidationError): RunRecord.model_validate(data)


def test_artifact_supersedes_without_mutation():
    original=records()[1]; snapshot=original.model_dump_json()
    replacement=Artifact(task_id=original.task_id,artifact_type=original.artifact_type,schema_version="0.1",content={"summary":"Revised"},supersedes_artifact_id=original.id)
    assert replacement.id != original.id
    assert replacement.supersedes_artifact_id==original.id
    assert original.model_dump_json()==snapshot
    with pytest.raises(ValidationError): original.content={}


@pytest.mark.parametrize("index",range(1,10))
def test_history_fields_frozen(index):
    obj=records()[index]
    with pytest.raises(ValidationError): obj.id=uuid4()


def test_active_task_needs_no_completion_timestamp():
    task=records()[0]
    assert task.state is TaskState.CREATED
    assert task.completed_at is None


@pytest.mark.parametrize("model,factory",[(ResearchOutput,research),(PlannerOutput,plan),(ImplementationOutput,implementation),(AnalysisOutput,analysis),(InvestigationOutput,investigation),(ReviewOutput,review)])
def test_agent_outputs_cannot_request_task_state(model,factory):
    data=factory(); data["state"]="DONE"
    with pytest.raises(ValidationError): model.model_validate(data)
