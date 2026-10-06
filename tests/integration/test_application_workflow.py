"""Application facade above actual runner, workspace guards and durable evidence."""
from dataclasses import replace
import subprocess
import pytest
from test_repository_workflow import setup, tool_turn, final, values, GUARDED, INITIAL
from test_project_workflow import research, proposal
from qa_sentinel.application import (
    QASentinelApplication, ProjectExecutionResolver, ProjectExecutionBundle, ApplicationError,
)
from qa_sentinel.projects import ProjectRuntimeRegistry, ProjectWorkspaceBinding
from qa_sentinel.agents.scenarios import division_scenario, DIVISION_REQUIREMENT
from qa_sentinel.agents.fake import FakeAgentRuntime
from qa_sentinel.execution.fake import FakeTestResultProvider
from qa_sentinel.domain.enums import AgentName as A, TaskState as S
from qa_sentinel.domain.project import Project
from qa_sentinel.orchestration.workflow_engine import WorkflowEngine
from qa_sentinel.orchestration.runner import WorkflowRunner, RunnerStoppedError
from qa_sentinel.orchestration.repository_execution import RepositoryReconciliationRequired
from qa_sentinel.mutation.contracts import MutationReconciliationRequired
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.database import create_engine, create_session_factory
from qa_sentinel.persistence.repositories import HistoryRepository


def composition(factory, harnesses):
    bundles = [ProjectExecutionBundle(h.runner.workspace_binding, h.runtime, h.provider,
        repository_service=h.reader, mutation_service=h.mutation) for h in harnesses]
    registry = ProjectRuntimeRegistry([bundle.binding for bundle in bundles])
    return QASentinelApplication(factory, ProjectExecutionResolver(registry, bundles)), bundles


def snapshot(factory, task_id):
    with UnitOfWork(factory) as uow:
        return (uow.tasks.get(task_id).model_dump(mode="json"),
                [record.model_dump(mode="json") for record in uow.history.list_events(task_id)],
                [record.model_dump(mode="json") for record in uow.history.list_transitions(task_id)],
                [record.model_dump(mode="json") for record in uow.artifacts.list_by_task(task_id)],
                [record.model_dump(mode="json") for record in uow.invocations.list_by_task(task_id)],
                [record.model_dump(mode="json") for record in uow.history.list_test_runs(task_id)])


def test_two_projects_read_mutate_test_through_facade_and_reopen(migrated_factory, tmp_path, mock_openai, monkeypatch):
    factory, engine, _ = migrated_factory
    other = "def add(a, b):\n    return sum((a, b))\n# Project B source\n"
    mock = mock_openai([tool_turn(), research(INITIAL), final(values()[A.PLANNER], A.PLANNER),
        proposal(INITIAL, "# A\n"), values()[A.REVIEWER],
        tool_turn(), research(other), final(values()[A.PLANNER], A.PLANNER),
        proposal(other, "# B\n"), values()[A.REVIEWER]])
    a = setup(factory, tmp_path / "a", mock, real_implementation=True, project=Project(key="a", name="A"))
    b = setup(factory, tmp_path / "b", mock, real_implementation=True, project=Project(key="b", name="B"))
    (b.root / "calculator.py").write_bytes(other.encode())
    app, _ = composition(factory, [a, b])
    assert app.run_task(a.task.id).state == S.DONE
    assert not app.get_task_artifacts(b.task.id).items
    assert (b.root / "calculator.py").read_bytes() == other.encode()
    assert app.run_task(b.task.id).state == S.DONE
    assert (a.root / "calculator.py").read_bytes() == (GUARDED + "# A\n").encode()
    assert (b.root / "calculator.py").read_bytes() == (GUARDED + "# B\n").encode()
    assert not mock.queue and len(mock.calls) == 10
    before = {h.task.id: snapshot(factory, h.task.id) for h in (a, b)}
    def forbidden(*args, **kwargs):
        raise AssertionError("Read/terminal run cannot call model, reader, mutator or process")
    for h in (a, b):
        monkeypatch.setattr(h.runtime, "run", forbidden)
        monkeypatch.setattr(h.reader, "execute", forbidden)
        monkeypatch.setattr(h.mutation, "build_snapshots", forbidden)
        monkeypatch.setattr(h.mutation, "apply", forbidden)
        monkeypatch.setattr(h.provider, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    for h in (a, b):
        assert app.run_task(h.task.id).state == S.DONE
        detail = app.get_task_detail(h.task.id, project_id=h.task.project_id)
        assert detail.completed_at is not None
        transitions = [entry for entry in app.get_task_timeline(h.task.id, limit=500).items
                       if entry.event_type == "STATE_TRANSITIONED"]
        assert [entry.details["to_state"] for entry in transitions] == [
            "RESEARCHING", "PLANNING", "IMPLEMENTING", "TESTING", "REVIEWING", "DONE"]
        assert app.get_task_test_runs(h.task.id).items[0].passed_count == 3
        assert app.get_task_invocations(h.task.id).total_returned == 4
        assert app.get_task_gate_evaluations(h.task.id).total_returned == 5
        assert app.get_task_decisions(h.task.id).total_returned == 6
        assert app.get_task_errors(h.task.id).total_returned == 0
        artifacts = app.get_task_artifacts(h.task.id)
        assert artifacts.total_returned > 4 and all(item.task_id == h.task.id for item in artifacts.items)
        assert app.get_task_artifacts(h.task.id, limit=1).truncated
        assert app.get_task_invocations(h.task.id, limit=1).truncated
        assert app.get_task_test_runs(h.task.id, limit=1).truncated is False
        assert app.get_task_decisions(h.task.id, limit=1).truncated
        assert app.get_task_gate_evaluations(h.task.id, limit=1).truncated
        assert snapshot(factory, h.task.id) == before[h.task.id]
    fresh = create_engine(str(engine.url))
    try:
        reopened = QASentinelApplication(create_session_factory(fresh), app._resolver)
        for h in (a, b):
            assert reopened.get_task_timeline(h.task.id, limit=500) == app.get_task_timeline(h.task.id, limit=500)
            assert reopened.run_task(h.task.id).state == S.DONE
    finally:
        fresh.dispose()


def fake_app(factory, tmp_path):
    # Host supplies per-project dependencies; callers create through the facade.
    registry = ProjectRuntimeRegistry([])
    app = QASentinelApplication(factory, ProjectExecutionResolver(registry, []))
    p = app.create_project(key="fake", name="Fake target")
    task = app.create_task(project_id=p.id, title="Division", requirement=DIVISION_REQUIREMENT)
    scenario, runs = division_scenario()
    binding = ProjectWorkspaceBinding(project_id=p.id, workspace_root=tmp_path)
    bundle = ProjectExecutionBundle(binding, FakeAgentRuntime(scenario), FakeTestResultProvider(runs))
    app = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([binding]), [bundle]))
    return app, task, bundle


def test_block_resume_is_explicit_atomic_engine_transition_then_run(factory, tmp_path, monkeypatch):
    app, task, bundle = fake_app(factory, tmp_path)
    WorkflowEngine(factory).transition(task_id=task.id, to_state=S.BLOCKED, resume_state=S.RESEARCHING,
        reason_code="WAIT", reason_details="Waiting for host")
    calls = []
    original = bundle.runtime.run
    def capture(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(bundle.runtime, "run", capture)
    assert app.run_task(task.id).state == S.BLOCKED and not calls
    before = snapshot(factory, task.id)
    assert app.run_task(task.id).state == S.BLOCKED
    assert snapshot(factory, task.id) == before
    resumed = app.resume_task(task.id)
    assert resumed.state == S.RESEARCHING and resumed.resume_state is None and not calls
    with UnitOfWork(factory) as uow:
        transitions = uow.history.list_transitions(task.id)
        resumed_transition, = [t for t in transitions if t.trigger == "APPLICATION_RESUME"]
        assert resumed_transition.from_state == S.BLOCKED and resumed_transition.to_state == S.RESEARCHING
        assert uow.history.get_decision(resumed_transition.decision_id).reason_code == "APPLICATION_RESUME"
    assert app.run_task(task.id).state == S.DONE and len(calls) == 4


def test_failed_task_remains_terminal(factory, tmp_path, monkeypatch):
    app, task, bundle = fake_app(factory, tmp_path)
    WorkflowEngine(factory).transition(task_id=task.id, to_state=S.BLOCKED, resume_state=S.RESEARCHING,
        reason_code="WAIT", reason_details="Host action")
    WorkflowEngine(factory).transition(task_id=task.id, to_state=S.FAILED, reason_code="STOP", reason_details="Stop")
    def forbidden(*args, **kwargs):
        raise AssertionError("Terminal task must not execute")
    monkeypatch.setattr(bundle.runtime, "run", forbidden)
    assert app.run_task(task.id).state == S.FAILED
    before = snapshot(factory, task.id)
    assert app.run_task(task.id).state == S.FAILED and snapshot(factory, task.id) == before


def test_missing_and_wrong_runtime_mapping(factory, tmp_path):
    app, task, bundle = fake_app(factory, tmp_path)
    empty = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]), []))
    with pytest.raises(ApplicationError) as error:
        empty.run_task(task.id)
    assert error.value.code == "PROJECT_RUNTIME_NOT_CONFIGURED"
    registry = ProjectRuntimeRegistry([bundle.binding])
    missing = QASentinelApplication(factory, ProjectExecutionResolver(registry, []))
    with pytest.raises(ApplicationError) as error:
        missing.run_task(task.id)
    assert error.value.code == "PROJECT_RUNTIME_NOT_CONFIGURED"
    root = tmp_path / "other"
    root.mkdir()
    wrong = replace(bundle, binding=ProjectWorkspaceBinding(project_id=task.project_id, workspace_root=root))
    wrong_app = QASentinelApplication(factory, ProjectExecutionResolver(registry, [wrong]))
    before = snapshot(factory, task.id)
    with pytest.raises(ApplicationError) as error:
        wrong_app.run_task(task.id)
    assert error.value.code == "PROJECT_RUNTIME_MISMATCH"
    assert snapshot(factory, task.id) == before
    with pytest.raises(ApplicationError, match="PROJECT_RUNTIME_MISMATCH"):
        ProjectExecutionResolver(registry, [bundle, bundle])


@pytest.mark.parametrize("component", ["reader", "mutation", "provider"])
def test_wrong_host_service_preserves_guard_stop_and_zero_side_effects(migrated_factory, tmp_path, mock_openai, monkeypatch, component):
    factory, _, _ = migrated_factory
    mock = mock_openai([])
    a = setup(factory, tmp_path / "a", mock, real_implementation=True)
    b = setup(factory, tmp_path / "b", mock, real_implementation=True)
    app, bundles = composition(factory, [a, b])
    field = {"reader": "repository_service", "mutation": "mutation_service", "provider": "test_provider"}[component]
    wrong = replace(bundles[0], **{field: getattr(bundles[1], field)})
    app = QASentinelApplication(factory, ProjectExecutionResolver(
        ProjectRuntimeRegistry([bundles[0].binding, bundles[1].binding]), [wrong, bundles[1]]))
    def forbidden(*args, **kwargs):
        raise AssertionError("Guard must stop before side effects")
    for h in (a, b):
        monkeypatch.setattr(h.runtime, "run", forbidden)
        monkeypatch.setattr(h.reader, "execute", forbidden)
        monkeypatch.setattr(h.mutation, "build_snapshots", forbidden)
        monkeypatch.setattr(h.mutation, "apply", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    with pytest.raises(ApplicationError) as caught:
        app.run_task(a.task.id)
    assert caught.value.code == "TASK_RECONCILIATION_REQUIRED"
    assert app.get_task(a.task.id).state == S.CREATED
    assert not mock.calls and not app.get_task_invocations(a.task.id).items
    assert not app.get_task_artifacts(a.task.id).items
    errors = app.get_task_errors(a.task.id)
    assert errors.total_returned == 0  # Derived assessment does not append recovery evidence.
    assert app.assess_task_reconciliation(a.task.id).status == "MANUAL_ACTION_REQUIRED"
    assert not app.get_task_timeline(b.task.id).items


@pytest.mark.parametrize("failure", [RunnerStoppedError, RepositoryReconciliationRequired, MutationReconciliationRequired])
def test_runtime_stop_mapping_keeps_durable_evidence(factory, tmp_path, monkeypatch, failure):
    app, task, _ = fake_app(factory, tmp_path)
    def stopped(self, task_id):
        WorkflowEngine(factory).transition(task_id=task_id, to_state=S.RESEARCHING,
            reason_code="START", reason_details="Persisted before failure")
        raise failure("synthetic-sensitive-host-detail")
    monkeypatch.setattr(WorkflowRunner, "run", stopped)
    with pytest.raises(ApplicationError) as caught:
        app.run_task(task.id)
    assert caught.value.code == "RUNTIME_STOPPED" and str(caught.value) == "RUNTIME_STOPPED"
    assert app.get_task(task.id).state == S.RESEARCHING
    assert app.get_task_decisions(task.id).items[0].reason_code == "START"
    assert app.get_task_timeline(task.id).items[0].details["to_state"] == "RESEARCHING"


def test_resume_history_failure_rolls_back_atomically(factory, tmp_path, monkeypatch):
    app, task, _ = fake_app(factory, tmp_path)
    WorkflowEngine(factory).transition(task_id=task.id, to_state=S.BLOCKED, resume_state=S.RESEARCHING,
        reason_code="WAIT", reason_details="Waiting")
    before = snapshot(factory, task.id)
    def failure(*args, **kwargs):
        raise RuntimeError("synthetic-sensitive-storage-detail")
    monkeypatch.setattr(HistoryRepository, "append_event", failure)
    with pytest.raises(ApplicationError, match="RUNTIME_STOPPED"):
        app.resume_task(task.id)
    assert snapshot(factory, task.id) == before
