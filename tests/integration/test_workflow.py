
from datetime import datetime,timezone
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.artifact import Artifact
from qa_sentinel.domain.test_run import TestRun as RunRecord
from qa_sentinel.domain.enums import TaskState as S
from qa_sentinel.persistence.database import create_engine,create_session_factory
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.orchestration.workflow_engine import WorkflowEngine
from qa_sentinel.orchestration.gates import (
    ResearchGate,PlanGate,ImplementationGate,TestGate as RunGate,ReviewGate,
    AnalysisGate,InvestigationGate,
)


def test_complete_workflow_survives_reopening_migrated_sqlite(migrated_factory,workflow_outputs):
    factory,engine,config=migrated_factory
    task=Task(title="Happy path",requirement="Verified behavior")
    with UnitOfWork(factory) as uow:uow.tasks.add(task);uow.commit()
    workflow=WorkflowEngine(factory)
    workflow.transition(task_id=task.id,to_state=S.RESEARCHING,reason_code="START_RESEARCH",reason_details="Start")
    research=workflow_outputs["research"]
    research_artifact=Artifact(task_id=task.id,artifact_type="RESEARCH",schema_version="0.1",
                               producer_agent="RESEARCHER",content=research.model_dump(mode="json"))
    with UnitOfWork(factory) as uow:uow.artifacts.add(research_artifact);uow.commit()
    workflow.transition(task_id=task.id,to_state=S.PLANNING,reason_code="RESEARCH_GATE_PASSED",reason_details="Research sufficient",
                        gate_evaluation=ResearchGate.evaluate(task.id,research),artifact_id=research_artifact.id)
    plan=workflow_outputs["plan"]
    plan_artifact=Artifact(task_id=task.id,artifact_type="PLAN",schema_version="0.1",producer_agent="PLANNER",
                          content=plan.model_dump(mode="json"))
    with UnitOfWork(factory) as uow:uow.artifacts.add(plan_artifact);uow.commit()
    workflow.transition(task_id=task.id,to_state=S.IMPLEMENTING,reason_code="PLAN_READY",reason_details="Plan ready",
                        gate_evaluation=PlanGate.evaluate(task.id,plan),artifact_id=plan_artifact.id)
    implementation=workflow_outputs["implementation"]
    impl=Artifact(task_id=task.id,artifact_type="IMPLEMENTATION",schema_version="0.1",producer_agent="IMPLEMENTER",
                  content=implementation.model_dump(mode="json"))
    with UnitOfWork(factory) as uow:uow.artifacts.add(impl);uow.commit()
    workflow.transition(task_id=task.id,to_state=S.TESTING,reason_code="IMPLEMENTATION_COMPLETE",reason_details="Work complete",
                        gate_evaluation=ImplementationGate.evaluate(task.id,implementation,plan),artifact_id=impl.id)
    now=datetime.now(timezone.utc)
    run=RunRecord(task_id=task.id,implementation_artifact_id=impl.id,execution_status="COMPLETED",outcome="PASS",
                  environment="test",started_at=now,finished_at=now,passed_count=1,failed_count=0,skipped_count=0)
    with UnitOfWork(factory) as uow:uow.history.append_test_run(run);uow.commit()
    workflow.transition(task_id=task.id,to_state=S.REVIEWING,reason_code="TESTS_PASSED",reason_details="Deterministic test pass",
                        gate_evaluation=RunGate.evaluate(task.id,run),test_run_id=run.id,artifact_id=impl.id)
    workflow.transition(task_id=task.id,to_state=S.DONE,reason_code="REVIEW_APPROVED",reason_details="Coverage verified",
                        gate_evaluation=ReviewGate.evaluate(task.id,workflow_outputs["review"],plan),
                        test_run_id=run.id,artifact_id=impl.id)
    fresh=create_engine(str(engine.url))
    try:
        with UnitOfWork(create_session_factory(fresh)) as uow:
            saved=uow.tasks.get(task.id)
            assert saved.state is S.DONE and saved.completed_at==saved.updated_at
            assert saved.created_at==task.created_at
            records=uow.history.list_transitions(task.id)
            assert len(records)==6
            by_source={t.from_state:t for t in records}
            transitions=[by_source[state] for state in
                         [S.CREATED,S.RESEARCHING,S.PLANNING,S.IMPLEMENTING,S.TESTING,S.REVIEWING]]
            assert [(t.from_state,t.to_state) for t in transitions]==list(zip(
                [S.CREATED,S.RESEARCHING,S.PLANNING,S.IMPLEMENTING,S.TESTING,S.REVIEWING],
                [S.RESEARCHING,S.PLANNING,S.IMPLEMENTING,S.TESTING,S.REVIEWING,S.DONE]))
            decisions=uow.history.list_decisions(task.id);events=uow.history.list_events(task.id)
            gates=uow.history.list_gate_evaluations(task.id)
            assert len(decisions)==len(events)==6 and len(gates)==5
            assert {t.decision_id for t in transitions}=={d.id for d in decisions}
            assert {t.gate_evaluation_id for t in transitions if t.gate_evaluation_id}=={g.id for g in gates}
            event=next(e for e in events if e.payload["to_state"]=="REVIEWING")
            assert event.correlation.test_run_id==run.id
            assert event.correlation.artifact_id==impl.id
            assert uow.artifacts.get(impl.id)==impl
    finally:fresh.dispose()


def test_deterministic_failure_repair_loop(migrated_factory,workflow_outputs):
    factory,engine,config=migrated_factory
    task=Task(title="Repair loop",requirement="Fix defect",state=S.IMPLEMENTING)
    impl=Artifact(task_id=task.id,artifact_type="IMPLEMENTATION",schema_version="0.1",content={"work":"completed"})
    now=datetime.now(timezone.utc)
    run=RunRecord(task_id=task.id,implementation_artifact_id=impl.id,execution_status="COMPLETED",outcome="FAIL",
                  environment="test",started_at=now,finished_at=now,passed_count=0,failed_count=1,skipped_count=0)
    with UnitOfWork(factory) as uow:
        uow.tasks.add(task);uow.artifacts.add(impl);uow.history.append_test_run(run);uow.commit()
    workflow=WorkflowEngine(factory)
    workflow.transition(task_id=task.id,to_state=S.TESTING,reason_code="IMPLEMENTATION_COMPLETE",reason_details="Work complete",
        gate_evaluation=ImplementationGate.evaluate(task.id,workflow_outputs["implementation"],workflow_outputs["plan"]))
    workflow.transition(task_id=task.id,to_state=S.ANALYZING,reason_code="TESTS_FAILED_ANALYSIS_REQUIRED",reason_details="Tests failed",
                        gate_evaluation=RunGate.evaluate(task.id,run),test_run_id=run.id)
    workflow.transition(task_id=task.id,to_state=S.INVESTIGATING,reason_code="ANALYSIS_SUFFICIENT",reason_details="Failures grouped",
                        gate_evaluation=AnalysisGate.evaluate(task.id,workflow_outputs["analysis"]))
    workflow.transition(task_id=task.id,to_state=S.IMPLEMENTING,reason_code="ROOT_CAUSE_IDENTIFIED",reason_details="Code fix required",
                        gate_evaluation=InvestigationGate.evaluate(task.id,workflow_outputs["investigation"]))
    with UnitOfWork(factory) as uow:
        saved=uow.tasks.get(task.id)
        assert saved.state is S.IMPLEMENTING
        assert saved.implementation_attempt==saved.defect_cycle==saved.review_cycle==0
        records=uow.history.list_transitions(task.id)
        assert len(records)==4
        by_source={t.from_state:t for t in records}
        history=[by_source[state] for state in [S.IMPLEMENTING,S.TESTING,S.ANALYZING,S.INVESTIGATING]]
        assert [t.to_state for t in history]==[S.TESTING,S.ANALYZING,S.INVESTIGATING,S.IMPLEMENTING]
        assert len(uow.history.list_decisions(task.id))==len(uow.history.list_events(task.id))==4
        assert len(uow.history.list_gate_evaluations(task.id))==4
        assert uow.history.get_test_run(run.id).outcome.value=="FAIL"
