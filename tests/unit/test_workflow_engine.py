from qa_sentinel.domain.project import Project

from datetime import datetime,timezone
from uuid import uuid4
import pytest
from sqlalchemy import select,func
from sqlalchemy.exc import IntegrityError
from qa_sentinel.domain.enums import TaskState as S,GateResult as R
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.gate import GateEvaluation
from qa_sentinel.persistence.models import Base
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.repositories import HistoryRepository
from qa_sentinel.orchestration.workflow_engine import WorkflowEngine
from qa_sentinel.orchestration.errors import (
    InvalidTransitionError,MissingGateError,GateRejectedError,TerminalStateError,ResumeStateError,
)


def seed(factory,state=S.CREATED):
    old=datetime(2020,1,1,tzinfo=timezone.utc)
    task=Task(project_id=uuid4(), title="Task",requirement="Requirement",state=state,created_at=old,updated_at=old)
    with UnitOfWork(factory) as uow:uow.projects.add(Project(id=task.project_id,key="test-"+task.project_id.hex,name="Test owner")); uow.tasks.add(task);uow.commit()
    return task


def gate(task,name,result=R.PASS):
    return GateEvaluation(task_id=task.id,gate_name=name,result=result,
                          checks=[dict(check="CHECK",result=result)])


def snapshot(factory):
    with factory() as session:
        return {name:session.scalar(select(func.count()).select_from(table))
                for name,table in Base.metadata.tables.items()}


def test_start_transition_persists_linked_decision_event_snapshot(factory):
    task=seed(factory);engine=WorkflowEngine(factory)
    transition=engine.transition(task_id=task.id,to_state=S.RESEARCHING,
                                 reason_code="START_RESEARCH",reason_details="Start research")
    with UnitOfWork(factory) as uow:
        saved=uow.tasks.get(task.id)
        assert saved.state is S.RESEARCHING
        assert saved.updated_at>task.updated_at and saved.updated_at.utcoffset().total_seconds()==0
        assert saved.created_at==task.created_at and saved.completed_at is None
        assert uow.history.get_transition(transition.id)==transition
        decision=uow.history.get_decision(transition.decision_id)
        assert decision.decision_source=="ORCHESTRATOR"
        assert decision.reason_code=="START_RESEARCH"
        event=uow.history.list_events(task.id)[0]
        assert event.event_type=="STATE_TRANSITIONED"
        assert event.actor.type.value=="ORCHESTRATOR" and event.actor.id=="qa-sentinel"
        assert event.correlation.decision_id==decision.id
        assert event.payload==dict(from_state="CREATED",to_state="RESEARCHING",reason_code="START_RESEARCH")
        assert event.timestamp==decision.created_at==transition.created_at==saved.updated_at


@pytest.mark.parametrize("source,destination,name",[
    (S.RESEARCHING,S.PLANNING,"RESEARCH_GATE"),(S.PLANNING,S.IMPLEMENTING,"PLAN_GATE"),
    (S.IMPLEMENTING,S.TESTING,"IMPLEMENTATION_GATE"),(S.TESTING,S.REVIEWING,"TEST_GATE"),
    (S.REVIEWING,S.DONE,"REVIEW_GATE"),
])
def test_each_forward_edge_requires_correct_pass_gate(factory,source,destination,name):
    task=seed(factory,source);engine=WorkflowEngine(factory);before=snapshot(factory)
    with pytest.raises(MissingGateError):
        engine.transition(task_id=task.id,to_state=destination,reason_code="FORWARD",reason_details="Forward")
    for wrong in [gate(task,name,R.FAIL),gate(task,name,R.BLOCKED),gate(task,"WRONG_GATE"),
                  gate(task.model_copy(update={"id":uuid4()}),name)]:
        with pytest.raises(GateRejectedError):
            engine.transition(task_id=task.id,to_state=destination,reason_code="FORWARD",reason_details="Forward",
                              gate_evaluation=wrong)
    assert snapshot(factory)==before
    evidence=gate(task,name)
    transition=engine.transition(task_id=task.id,to_state=destination,reason_code="FORWARD",reason_details="Forward",
                                 gate_evaluation=evidence,evidence_refs=("artifact:1",))
    with UnitOfWork(factory) as uow:
        assert uow.history.get_gate_evaluation(evidence.id)==evidence
        assert transition.gate_evaluation_id==evidence.id
        assert str(evidence.id) in uow.history.get_decision(transition.decision_id).evidence_refs
        assert "artifact:1" in uow.history.get_decision(transition.decision_id).evidence_refs
        saved=uow.tasks.get(task.id)
        assert saved.state is destination
        if destination is S.DONE:assert saved.completed_at==saved.updated_at


@pytest.mark.parametrize("source,destination,error",[
    (S.RESEARCHING,S.DONE,InvalidTransitionError),(S.DONE,S.RESEARCHING,TerminalStateError),
    (S.FAILED,S.RESEARCHING,TerminalStateError),
])
def test_invalid_and_terminal_requests_leave_everything_unchanged(factory,source,destination,error):
    task=seed(factory,source);before=snapshot(factory)
    with pytest.raises(error):WorkflowEngine(factory).transition(task_id=task.id,to_state=destination,
        reason_code="REQUEST",reason_details="Invalid request")
    assert snapshot(factory)==before
    with UnitOfWork(factory) as uow:assert uow.tasks.get(task.id)==task


def test_block_resume_and_failed_completion_timestamps(factory):
    task=seed(factory);engine=WorkflowEngine(factory)
    with pytest.raises(ResumeStateError):engine.transition(task_id=task.id,to_state=S.BLOCKED,
        reason_code="TASK_BLOCKED",reason_details="Block")
    engine.transition(task_id=task.id,to_state=S.BLOCKED,resume_state=S.RESEARCHING,
                      reason_code="TASK_BLOCKED",reason_details="Block")
    with UnitOfWork(factory) as uow:assert uow.tasks.get(task.id).resume_state is S.RESEARCHING
    with pytest.raises(ResumeStateError):engine.transition(task_id=task.id,to_state=S.PLANNING,
        reason_code="TASK_RESUMED",reason_details="Wrong resume")
    engine.transition(task_id=task.id,to_state=S.RESEARCHING,reason_code="TASK_RESUMED",reason_details="Resume")
    with UnitOfWork(factory) as uow:assert uow.tasks.get(task.id).resume_state is None
    engine.transition(task_id=task.id,to_state=S.BLOCKED,resume_state=S.RESEARCHING,
                      reason_code="TASK_BLOCKED",reason_details="Block again")
    engine.transition(task_id=task.id,to_state=S.FAILED,reason_code="TASK_FAILED",reason_details="Cancel")
    with UnitOfWork(factory) as uow:
        final=uow.tasks.get(task.id)
        assert final.completed_at==final.updated_at and final.resume_state is None
        assert final.created_at==task.created_at


@pytest.mark.parametrize("failure_mode",["after_event_write","commit_foreign_key_failure"])
def test_atomic_rollback_after_all_writes(factory,monkeypatch,failure_mode):
    task=seed(factory,S.RESEARCHING);before=snapshot(factory)
    original=HistoryRepository.append_event
    def failing_append(self,event):
        if failure_mode=="commit_foreign_key_failure":
            original(self,event.model_copy(update={"task_id":uuid4()}))
        else:
            original(self,event)
            raise RuntimeError("injected failure after event insert")
    monkeypatch.setattr(HistoryRepository,"append_event",failing_append)
    error=IntegrityError if failure_mode=="commit_foreign_key_failure" else RuntimeError
    with pytest.raises(error):WorkflowEngine(factory).transition(task_id=task.id,to_state=S.PLANNING,
        reason_code="RESEARCH_GATE_PASSED",reason_details="Sufficient research",
        gate_evaluation=gate(task,"RESEARCH_GATE"))
    assert snapshot(factory)==before
    with UnitOfWork(factory) as uow:assert uow.tasks.get(task.id)==task


def test_same_state_placeholder_is_explicit_without_retry_counters(factory):
    task=seed(factory,S.IMPLEMENTING);engine=WorkflowEngine(factory)
    with pytest.raises(InvalidTransitionError):engine.transition(task_id=task.id,to_state=S.IMPLEMENTING,
        reason_code="PLACEHOLDER",reason_details="Explicit same state")
    engine.transition(task_id=task.id,to_state=S.IMPLEMENTING,reason_code="PLACEHOLDER",
                      reason_details="Explicit same state",allow_same_state=True)
    with UnitOfWork(factory) as uow:
        saved=uow.tasks.get(task.id)
        assert saved.implementation_attempt==task.implementation_attempt
        assert saved.defect_cycle==task.defect_cycle and saved.review_cycle==task.review_cycle


def test_gate_aggregate_and_context_are_validated(factory):
    task=seed(factory,S.RESEARCHING)
    malformed=GateEvaluation(task_id=task.id,gate_name="RESEARCH_GATE",result="PASS",
                              checks=[dict(check="incomplete",result="FAIL")])
    with pytest.raises(GateRejectedError):WorkflowEngine(factory).transition(task_id=task.id,to_state=S.PLANNING,
        reason_code="RESEARCH_GATE_PASSED",reason_details="Research",gate_evaluation=malformed)
    with pytest.raises(ResumeStateError):WorkflowEngine(factory).transition(task_id=task.id,to_state=S.PLANNING,
        reason_code="RESEARCH_GATE_PASSED",reason_details="Research",resume_state=S.RESEARCHING)


def test_missing_task_and_evidence_reference(factory):
    engine=WorkflowEngine(factory)
    with pytest.raises(KeyError):engine.transition(task_id=uuid4(),to_state=S.RESEARCHING,
        reason_code="START_RESEARCH",reason_details="Start")
    task=seed(factory)
    with pytest.raises(GateRejectedError):engine.transition(task_id=task.id,to_state=S.RESEARCHING,
        reason_code="START_RESEARCH",reason_details="Start",artifact_id=uuid4())
    with UnitOfWork(factory) as uow:assert uow.tasks.get(task.id)==task



def test_optional_nonpass_gate_routes_back_and_is_persisted(factory,workflow_outputs):
    from qa_sentinel.orchestration.gates import PlanGate
    from qa_sentinel.schemas.plan import PlannerOutput
    task=seed(factory,S.PLANNING)
    output=PlannerOutput.model_validate({**workflow_outputs["plan"].model_dump(),"decision":"NEEDS_RESEARCH"})
    evidence=PlanGate.evaluate(task.id,output)
    assert evidence.result is R.FAIL
    transition=WorkflowEngine(factory).transition(task_id=task.id,to_state=S.RESEARCHING,
        reason_code="PLAN_NEEDS_RESEARCH",reason_details="Research requested",gate_evaluation=evidence)
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(task.id).state is S.RESEARCHING
        assert uow.history.get_gate_evaluation(transition.gate_evaluation_id)==evidence


def test_supplied_passing_test_gate_cannot_route_to_failure_analysis(factory):
    task=seed(factory,S.TESTING)
    with pytest.raises(GateRejectedError):WorkflowEngine(factory).transition(task_id=task.id,to_state=S.ANALYZING,
        reason_code="TESTS_FAILED_ANALYSIS_REQUIRED",reason_details="Analyze",gate_evaluation=gate(task,"TEST_GATE"))
    with UnitOfWork(factory) as uow:assert uow.tasks.get(task.id)==task



@pytest.mark.parametrize("source,destination,name",[(S.TESTING,S.REVIEWING,"TEST_GATE"),(S.REVIEWING,S.DONE,"REVIEW_GATE")])
def test_deterministic_test_failure_overrides_supplied_pass_gate(factory,bundle,store_bundle,source,destination,name):
    bundle["task"].state=source
    run=bundle["test_run"]
    bundle["test_run"]=type(run).model_validate({**run.model_dump(),"outcome":"FAIL"})
    with UnitOfWork(factory) as uow:store_bundle(uow,bundle);uow.commit()
    before=snapshot(factory)
    with pytest.raises(GateRejectedError):WorkflowEngine(factory).transition(task_id=bundle["task"].id,
        to_state=destination,reason_code="APPROVE",reason_details="Approve",test_run_id=run.id,
        gate_evaluation=gate(bundle["task"],name))
    assert snapshot(factory)==before
    with UnitOfWork(factory) as uow:assert uow.tasks.get(bundle["task"].id).state is source
