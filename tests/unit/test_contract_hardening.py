from uuid import uuid4

import pytest
from pydantic import ValidationError

from qa_sentinel.domain.enums import (
    AgentInvocationStatus, ImplementationStepStatus, ChangeType,
    InvestigationActionType, CoverageStatus, ActorType,
    TestExecutionStatus as ExecutionStatus, TestOutcome as Outcome,
)
from qa_sentinel.domain.invocation import AgentInvocation
from qa_sentinel.domain.references import ActorRef, CorrelationRef, ErrorSource
from qa_sentinel.domain.test_run import TestRun as RunRecord
from qa_sentinel.schemas.plan import ImplementationStep, AcceptanceCriterion, PlannerOutput
from qa_sentinel.schemas.implementation import (
    ImplementationStepResult, ChangedFile, ExecutedCommand, ImplementationOutput,
)
from qa_sentinel.schemas.investigation import InvestigationAction, InvestigationOutput
from qa_sentinel.schemas.review import RequirementCoverage, ReviewOutput
from test_contracts import records, plan, implementation, investigation, review


@pytest.mark.parametrize("status", ["STARTED", "COMPLETED", "BLOCKED", "FAILED"])
@pytest.mark.parametrize("include_finished", [True, False])
def test_invocation_optional_finished_timestamp(status, include_finished):
    data = records()[2].model_dump()
    data["status"] = status
    if not include_finished:
        del data["finished_at"]
    obj = AgentInvocation.model_validate(data)
    assert obj.status is AgentInvocationStatus(status)
    assert (obj.finished_at is not None) is include_finished
    assert AgentInvocation.model_validate_json(obj.model_dump_json()) == obj


def test_started_invocation_explicit_null_finish():
    data = records()[2].model_dump()
    data.update(status="STARTED", finished_at=None)
    assert AgentInvocation.model_validate(data).finished_at is None


def test_invalid_invocation_status():
    data = records()[2].model_dump(); data["status"] = "RUNNING"
    with pytest.raises(ValidationError): AgentInvocation.model_validate(data)


def test_structured_planner_step_and_unresolved_dependency():
    data = plan()
    data["implementation_steps"][0]["depends_on"] = ["external-step"]
    obj = PlannerOutput.model_validate(data)
    step = obj.implementation_steps[0]
    assert step.id == "step-1"
    assert step.description == "Implement behavior"
    assert step.files == ("app.py",)
    assert step.depends_on == ("external-step",)
    assert obj.acceptance_criteria[0].verification == "Assert expected result"
    assert obj.test_strategy[0].acceptance_criteria_refs == ("AC-1",)


@pytest.mark.parametrize("value", ["", "   ", None])
def test_nonblank_verification(value):
    data = plan(); data["acceptance_criteria"][0]["verification"] = value
    with pytest.raises(ValidationError): PlannerOutput.model_validate(data)


def test_verification_required():
    data = plan(); del data["acceptance_criteria"][0]["verification"]
    with pytest.raises(ValidationError): PlannerOutput.model_validate(data)


@pytest.mark.parametrize("status", ["COMPLETED", "BLOCKED", "SKIPPED"])
def test_step_result_canonical_status(status):
    obj = ImplementationStepResult(step_id="step-1", status=status)
    assert obj.status is ImplementationStepStatus(status)


def test_step_result_invalid_status():
    with pytest.raises(ValidationError): ImplementationStepResult(step_id="step-1", status="FAILED")


@pytest.mark.parametrize("change", ["CREATED", "MODIFIED", "DELETED"])
def test_changed_file_canonical_change_type(change):
    obj = ChangedFile(path="app.py", change_type=change, reason="Requested change")
    assert obj.change_type is ChangeType(change)


def test_invalid_change_type():
    with pytest.raises(ValidationError): ChangedFile(path="app.py", change_type="RENAMED", reason="Change")


@pytest.mark.parametrize("exit_code", [-1, 0, 1, 255])
def test_command_integer_exit_code(exit_code):
    obj = ExecutedCommand(command="recorded command", exit_code=exit_code)
    assert obj.exit_code == exit_code


@pytest.mark.parametrize("exit_code", [1.5, 1.0, "0", True, None])
def test_command_noninteger_exit_code_rejected(exit_code):
    with pytest.raises(ValidationError): ExecutedCommand(command="recorded command", exit_code=exit_code)


@pytest.mark.parametrize("action", ["CODE_FIX", "TEST_FIX", "MORE_RESEARCH", "HUMAN_ACTION"])
def test_investigation_routable_action(action):
    data = investigation(); data["recommended_action"]["type"] = action
    obj = InvestigationOutput.model_validate(data)
    assert obj.recommended_action.type is InvestigationActionType(action)
    assert obj.recommended_action.description == "Fix condition"


def test_invalid_investigation_action():
    data = investigation(); data["recommended_action"]["type"] = "RETRY"
    with pytest.raises(ValidationError): InvestigationOutput.model_validate(data)


@pytest.mark.parametrize("status", ["COVERED", "NOT_COVERED", "UNVERIFIED"])
def test_coverage_status(status):
    data = review(); data["requirement_coverage"][0]["status"] = status
    assert ReviewOutput.model_validate(data).requirement_coverage[0].status is CoverageStatus(status)


@pytest.mark.parametrize("missing", [True, False])
def test_coverage_status_required_and_canonical(missing):
    data = review()
    if missing: del data["requirement_coverage"][0]["status"]
    else: data["requirement_coverage"][0]["status"] = "PASS"
    with pytest.raises(ValidationError): ReviewOutput.model_validate(data)


def test_event_audit_and_error_structured_refs():
    error, event, audit = records()[4], records()[7], records()[8]
    assert isinstance(event.actor, ActorRef)
    assert event.actor.type is ActorType.ORCHESTRATOR
    assert isinstance(event.correlation, CorrelationRef)
    assert event.correlation.decision_id is not None
    assert isinstance(audit.actor, ActorRef)
    assert isinstance(error.source, ErrorSource)
    assert error.source.actor.type is ActorType.TOOL
    assert error.source.invocation_id is not None
    assert error.source.tool == "pytest"


@pytest.mark.parametrize("actor_type", ["ORCHESTRATOR", "AGENT", "TOOL", "HUMAN", "SYSTEM"])
def test_actor_types(actor_type):
    assert ActorRef(type=actor_type, id="actor-1").type is ActorType(actor_type)


@pytest.mark.parametrize("field", ["invocation_id", "artifact_id", "test_run_id", "decision_id"])
def test_partial_correlation_uuid_refs(field):
    identifier = uuid4()
    obj = CorrelationRef.model_validate({field: str(identifier)})
    assert getattr(obj, field) == identifier
    assert CorrelationRef.model_validate_json(obj.model_dump_json()) == obj
    with pytest.raises(ValidationError): CorrelationRef.model_validate({field: "invalid-uuid"})


def test_empty_optional_references():
    assert CorrelationRef().model_dump() == dict(invocation_id=None, artifact_id=None, test_run_id=None, decision_id=None)
    assert ErrorSource().model_dump() == dict(actor=None, invocation_id=None, tool=None)


@pytest.mark.parametrize("index,field,bad", [
    (7,"actor","orchestrator"), (7,"actor",dict(type="UNKNOWN",id="actor")),
    (7,"actor",dict(type="AGENT",id=" ")), (7,"actor",dict(type="AGENT")),
    (7,"correlation",str(uuid4())), (7,"correlation",dict(artifact_id="bad")),
    (8,"actor","orchestrator"), (8,"actor",dict(type="HUMAN",id="")),
    (4,"source","pytest"), (4,"source",dict(tool=" ")),
    (4,"source",dict(invocation_id="bad")), (4,"source",dict(actor="agent")),
])
def test_malformed_structured_refs(index, field, bad):
    obj = records()[index]; data = obj.model_dump(); data[field] = bad
    with pytest.raises(ValidationError): type(obj).model_validate(data)


@pytest.mark.parametrize("execution,outcome", [("COMPLETED","PASS"), ("COMPLETED","FAIL"), ("FAILED","UNKNOWN"), ("INCOMPLETE","UNKNOWN")])
def test_execution_and_outcome_separate(execution, outcome):
    data = records()[9].model_dump(); data.update(execution_status=execution, outcome=outcome)
    obj = RunRecord.model_validate(data)
    assert obj.execution_status is ExecutionStatus(execution)
    assert obj.outcome is Outcome(outcome)
    assert RunRecord.model_validate_json(obj.model_dump_json()) == obj


@pytest.mark.parametrize("field,value", [("execution_status","PASSED"), ("outcome","COMPLETED")])
def test_invalid_execution_or_outcome(field, value):
    data = records()[9].model_dump(); data[field] = value
    with pytest.raises(ValidationError): RunRecord.model_validate(data)


def test_removed_test_run_status_rejected():
    data = records()[9].model_dump(); data["status"] = "PASSED"
    with pytest.raises(ValidationError): RunRecord.model_validate(data)


@pytest.mark.parametrize("model,factory,field,legacy", [
    (PlannerOutput,plan,"implementation_steps",["step-1"]),
    (ImplementationOutput,implementation,"plan_steps",["step-1"]),
    (ImplementationOutput,implementation,"changed_files",["app.py"]),
    (ImplementationOutput,implementation,"commands_executed",["pytest"]),
    (InvestigationOutput,investigation,"recommended_action","Fix code"),
])
def test_legacy_unstructured_fields_rejected(model,factory,field,legacy):
    data = factory(); data[field] = legacy
    with pytest.raises(ValidationError): model.model_validate(data)


@pytest.mark.parametrize("model,data,field", [
    (ImplementationStep, dict(id="step-1",description="Step",files=[],depends_on=[]), "id"),
    (AcceptanceCriterion, dict(id="AC-1",description="Criterion",verification="Assertion"), "verification"),
    (ImplementationStepResult, dict(step_id="step-1",status="COMPLETED"), "step_id"),
    (ChangedFile, dict(path="app.py",change_type="MODIFIED",reason="Change"), "path"),
    (ExecutedCommand, dict(command="recorded",exit_code=0), "command"),
    (InvestigationAction, dict(type="CODE_FIX",description="Fix"), "description"),
    (RequirementCoverage, dict(acceptance_criterion_id="AC-1",status="COVERED",summary="Covered",evidence_refs=[]), "acceptance_criterion_id"),
    (ActorRef, dict(type="SYSTEM",id="system-1"), "id"),
    (CorrelationRef, dict(invocation_id=None), "invocation_id"),
    (ErrorSource, dict(tool="pytest"), "tool"),
])
def test_new_structured_models_frozen_and_extra_fields_rejected(model,data,field):
    obj = model.model_validate(data)
    assert model.model_validate_json(obj.model_dump_json()) == obj
    with pytest.raises(ValidationError): setattr(obj, field, getattr(obj,field))
    with pytest.raises(ValidationError): model.model_validate({**data,"unexpected":True})


@pytest.mark.parametrize("field,value", [("id"," "),("description",""),("files",[" "]),("depends_on",[""])])
def test_step_nonblank_fields(field,value):
    data = dict(id="step-1",description="Step",files=[],depends_on=[]); data[field]=value
    with pytest.raises(ValidationError): ImplementationStep.model_validate(data)


def test_task_remains_mutable_snapshot():
    task = records()[0]; task.title = "Updated snapshot"
    assert task.title == "Updated snapshot"


def test_new_enum_sets_are_exact():
    expected = [
        (AgentInvocationStatus,"STARTED COMPLETED BLOCKED FAILED"),
        (ImplementationStepStatus,"COMPLETED BLOCKED SKIPPED"),
        (ChangeType,"CREATED MODIFIED DELETED"),
        (InvestigationActionType,"CODE_FIX TEST_FIX MORE_RESEARCH HUMAN_ACTION"),
        (CoverageStatus,"COVERED NOT_COVERED UNVERIFIED"),
        (ActorType,"ORCHESTRATOR AGENT TOOL HUMAN SYSTEM"),
        (ExecutionStatus,"COMPLETED INCOMPLETE FAILED"),
        (Outcome,"PASS FAIL UNKNOWN"),
    ]
    for enum, values in expected:
        assert {item.value for item in enum} == set(values.split())
