"""Two logical projects, identical relative paths, and independent real workspace work."""
from hashlib import sha256
import json
import subprocess
import pytest
from test_repository_workflow import setup, tool_turn, final, values, GUARDED, INITIAL
from qa_sentinel.domain.project import Project
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.artifact import Artifact
from qa_sentinel.domain.event import Event
from qa_sentinel.domain.enums import AgentName as A, ArtifactType as AT, TaskState as S
from qa_sentinel.schemas.mutation import ImplementationProposal
from qa_sentinel.projects import ProjectWorkspaceBinding, ProjectRuntimeRegistry, ProjectBindingError
from qa_sentinel.orchestration.runner import WorkflowRunner, RunnerStoppedError
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.database import create_engine, create_session_factory
from qa_sentinel.persistence.repositories import HistoryRepository
from qa_sentinel.repository.config import RepositoryReadConfig
from qa_sentinel.repository.service import RepositoryReadService
from qa_sentinel.mutation.contracts import MutationConfig
from qa_sentinel.mutation.service import MutationService
from qa_sentinel.execution.command_policy import ExecutionConfig
from qa_sentinel.execution.command_runner import CommandRunner
from qa_sentinel.execution.pytest_runner import PytestRunner
from qa_sentinel.execution.service import TestExecutionService as ExecutionService, PytestTestResultProvider


def research(expected):
    def respond(call):
        evidence=json.loads(call["input"][0]["content"])["repository_results"]
        assert evidence[-1]["result"]["data"]["content"]==expected
        output=values()[A.RESEARCHER].model_dump(mode="json")
        output["findings"][0]["evidence"]=[evidence[-1]["evidence_ref"]]
        return final(output)
    return respond


def proposal(expected, marker):
    def respond(call):
        data=json.loads(call["input"][0]["content"])
        assert "repository_results" not in data
        source,=data["source_files"]
        assert source["content"]==expected
        assert source["sha256"]==sha256(expected.encode()).hexdigest()
        return ImplementationProposal(implementation_status="COMPLETED", implementation_summary="Division",
            plan_steps=[dict(step_id="step-1",status="COMPLETED")],mutations=[dict(path="calculator.py",
                operation="MODIFY",expected_sha256=source["sha256"],content=GUARDED+marker,reason="Accepted plan")],
            tests_added_or_modified=[],assumptions=[],known_issues=[],deviations=[])
    return respond


def runner(h, *, binding=None, reader=None, mutation=None, provider=None, factory=None):
    return WorkflowRunner(factory or h.factory,h.runtime,provider or h.provider,
        repository_service=reader or h.reader,mutation_service=mutation or h.mutation,
        workspace_binding=binding or h.runner.workspace_binding)


def test_two_projects_real_read_mutation_pytest_evidence_and_reopen(migrated_factory,tmp_path,mock_openai):
    factory,engine,_=migrated_factory
    other="def add(a, b):\n    return sum((a, b))\n# Project B source\n"
    mock=mock_openai([tool_turn("LIST_FILES","."),tool_turn(),research(INITIAL),final(values()[A.PLANNER],A.PLANNER),
        proposal(INITIAL,"# Project A result\n"),values()[A.REVIEWER],
        tool_turn("SEARCH_TEXT",".",query="sum"),tool_turn(),research(other),final(values()[A.PLANNER],A.PLANNER),
        proposal(other,"# Project B result\n"),values()[A.REVIEWER]])
    a=setup(factory,tmp_path/"a",mock,real_implementation=True,project=Project(key="calculator-a",name="Calculator A"))
    b=setup(factory,tmp_path/"b",mock,real_implementation=True,project=Project(key="calculator-b",name="Calculator B"))
    (b.root/"calculator.py").write_bytes(other.encode())
    registry=ProjectRuntimeRegistry([a.runner.workspace_binding,b.runner.workspace_binding])
    # Same process, provider mock queue and model configuration; explicit per-project composition.
    for h in (a,b):
        assert runner(h,binding=registry.resolve(h.task.project_id)).run(h.task.id).state==S.DONE
    assert (a.root/"calculator.py").read_bytes()==(GUARDED+"# Project A result\n").encode()
    assert (b.root/"calculator.py").read_bytes()==(GUARDED+"# Project B result\n").encode()
    fresh=create_engine(str(engine.url))
    try:
        reopened=create_session_factory(fresh)
        with UnitOfWork(reopened) as uow:
            assert [p.key for p in uow.projects.list()]==["calculator-a","calculator-b"]
            for h,source in ((a,INITIAL),(b,other)):
                assert uow.tasks.get(h.task.id).project_id==h.task.project_id
                artifacts=uow.artifacts.list_by_task(h.task.id)
                reads=[x for x in artifacts if x.artifact_type==AT.REPOSITORY_EVIDENCE and x.content["request"]["arguments"]["tool"]=="READ_FILE"]
                assert reads[0].content["result"]["data"]["content"]==source
                assert all(x.task_id==h.task.id for x in artifacts)
                run,=uow.history.list_test_runs(h.task.id)
                assert run.passed_count==3 and run.outcome.value=="PASS"
                assert uow.artifacts.get(run.implementation_artifact_id).task_id==h.task.id
        count=len(mock.calls)
        assert runner(a,factory=reopened).run(a.task.id).state==S.DONE
        assert len(mock.calls)==count
        with pytest.raises(RunnerStoppedError,match="PROJECT_BINDING_MISMATCH"):
            runner(a,factory=reopened,binding=b.runner.workspace_binding).run(a.task.id)
    finally:
        fresh.dispose()


@pytest.mark.parametrize("mismatch",["project","reader","mutation","test","test-owner","missing"])
@pytest.mark.parametrize("stage", [S.CREATED, S.IMPLEMENTING, S.TESTING])
def test_cross_project_mismatch_has_zero_model_read_write_or_process_side_effects(migrated_factory,tmp_path,mock_openai,monkeypatch,mismatch,stage):
    factory,_,_=migrated_factory
    mock=mock_openai([])
    a=setup(factory,tmp_path/"a",mock,real_implementation=True)
    b=setup(factory,tmp_path/"b",mock,real_implementation=True)
    with UnitOfWork(factory) as uow:
        task=uow.tasks.get(a.task.id);task.state=stage;uow.tasks.save(task);uow.commit()
    (b.root/"calculator.py").write_bytes(b"private Project B data\n")
    before={p:p.read_bytes() for h in (a,b) for p in h.root.rglob("*") if p.is_file()}
    def forbidden(*args,**kwargs):raise AssertionError("Mismatch must have zero workspace/model side effects")
    for h in (a,b):
        monkeypatch.setattr(h.reader,"execute",forbidden)
        monkeypatch.setattr(h.mutation,"build_snapshots",forbidden)
        monkeypatch.setattr(h.mutation,"apply",forbidden)
    monkeypatch.setattr(subprocess,"Popen",forbidden)
    kwargs={}
    expected={"project":"PROJECT_BINDING_MISMATCH","reader":"REPOSITORY_WORKSPACE_MISMATCH",
        "mutation":"MUTATION_WORKSPACE_MISMATCH","test":"TEST_WORKSPACE_MISMATCH",
        "test-owner":"TEST_PROJECT_BINDING_MISMATCH","missing":"PROJECT_BINDING_MISSING"}[mismatch]
    if mismatch=="project":kwargs["binding"]=b.runner.workspace_binding
    elif mismatch=="reader":kwargs["reader"]=b.reader
    elif mismatch=="mutation":kwargs["mutation"]=b.mutation
    elif mismatch=="test":kwargs["provider"]=b.provider
    elif mismatch=="test-owner":
        service=ExecutionService(factory,a.provider.service.pytest_runner,
            workspace_binding=ProjectWorkspaceBinding(project_id=b.task.project_id,workspace_root=a.root))
        kwargs["provider"]=PytestTestResultProvider(service,a.provider.request)
    selected=runner(a,**kwargs)
    if mismatch=="missing":
        selected=WorkflowRunner(factory,a.runtime,a.provider,repository_service=a.reader,mutation_service=a.mutation)
    with pytest.raises(RunnerStoppedError,match=expected):selected.run(a.task.id)
    assert not mock.calls
    assert {p:p.read_bytes() for p in before}==before
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(a.task.id).state==stage
        assert not uow.invocations.list_by_task(a.task.id)
        assert not uow.artifacts.list_by_task(a.task.id)
        assert not uow.history.list_test_runs(a.task.id)
        assert not uow.history.list_transitions(a.task.id)
        error,=uow.history.list_errors(a.task.id)
        assert error.code==expected and error.error_type.value=="WORKFLOW_ERROR"


def test_direct_real_execution_wrong_project_stops_before_start(migrated_factory,tmp_path,mock_openai,monkeypatch):
    factory,_,_=migrated_factory
    mock=mock_openai([])
    a=setup(factory,tmp_path/"a",mock,real_implementation=True)
    b=setup(factory,tmp_path/"b",mock,real_implementation=True)
    implementation=Artifact(task_id=a.task.id,artifact_type="IMPLEMENTATION",schema_version="0.1",content={})
    with UnitOfWork(factory) as uow:
        task=uow.tasks.get(a.task.id);task.state=S.TESTING;uow.tasks.save(task)
        uow.artifacts.add(implementation);uow.commit()
    monkeypatch.setattr(subprocess,"Popen",lambda *a,**k:(_ for _ in ()).throw(AssertionError("No process")))
    with pytest.raises(ProjectBindingError,match="PROJECT_BINDING_MISMATCH"):
        b.provider.service.execute(task_id=a.task.id,implementation_artifact_id=implementation.id,request=b.provider.request)
    with UnitOfWork(factory) as uow:
        assert not uow.history.list_test_runs(a.task.id)
        assert not uow.history.list_events(a.task.id)
        assert uow.tasks.get(a.task.id).state==S.TESTING


def test_durable_repository_result_reopen_and_binding_drift_stop(migrated_factory,tmp_path,mock_openai,monkeypatch):
    factory,engine,_=migrated_factory
    mock=mock_openai([tool_turn(),research(INITIAL),final(values()[A.PLANNER],A.PLANNER)])
    h=setup(factory,tmp_path/"a",mock)
    original=HistoryRepository.append_event
    def pause(self,event):
        if event.event_type=="MODEL_TURN_STARTED" and event.payload["turn_index"]==2:raise RuntimeError("pause")
        original(self,event)
    monkeypatch.setattr(HistoryRepository,"append_event",pause)
    with pytest.raises(RuntimeError,match="pause"):h.runner.run(h.task.id)
    monkeypatch.setattr(HistoryRepository,"append_event",original)
    other=tmp_path/"other";other.mkdir()
    drift=ProjectWorkspaceBinding(project_id=h.task.project_id,workspace_root=other)
    other_reader=RepositoryReadService(RepositoryReadConfig(other))
    fresh=create_engine(str(engine.url))
    try:
        reopened=create_session_factory(fresh)
        with pytest.raises(RunnerStoppedError,match="WORKSPACE_REQUIRES_RECONCILIATION"):
            runner(h,binding=drift,reader=other_reader,factory=reopened).run(h.task.id)
        assert len(mock.calls)==1
        monkeypatch.setattr(h.reader,"execute",lambda *a,**k:(_ for _ in ()).throw(AssertionError("Durable read must be reused")))
        assert runner(h,factory=reopened).run(h.task.id).state==S.DONE
        assert len(mock.calls)==3
    finally:fresh.dispose()


def test_cross_project_artifact_type_attempt_and_foreign_pointer_never_select_b(migrated_factory,tmp_path,mock_openai):
    factory,_,_=migrated_factory
    mock=mock_openai([final(values()[A.RESEARCHER]),final(values()[A.PLANNER],A.PLANNER)])
    a=setup(factory,tmp_path/"a",mock)
    b=setup(factory,tmp_path/"b",mock)
    b.runner._step(b.runner._task(b.task.id));b.runner._step(b.runner._task(b.task.id))
    with UnitOfWork(factory) as uow:
        accepted=WorkflowRunner._artifact(uow,b.task.id,AT.RESEARCH)
        assert WorkflowRunner._artifact(uow,a.task.id,AT.RESEARCH,optional=True) is None
        with pytest.raises(RunnerStoppedError,match="missing"):
            WorkflowRunner._artifact(uow,a.task.id,AT.RESEARCH)
        task=uow.tasks.get(a.task.id);task.current_invocation_id=accepted.invocation_id;uow.tasks.save(task);uow.commit()
    with pytest.raises(RunnerStoppedError,match="CROSS_TASK_INVOCATION"):a.runner.run(a.task.id)
    assert len(mock.calls)==1
