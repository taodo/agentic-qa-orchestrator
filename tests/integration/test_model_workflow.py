import json
import pytest
from qa_sentinel.agents.base import ResearchContext
from qa_sentinel.agents.real import RealAgentRuntime
from qa_sentinel.agents.composite import CompositeAgentRuntime
from qa_sentinel.agents.fake import FakeAgentRuntime
from qa_sentinel.agents.scenarios import division_scenario, DIVISION_REQUIREMENT
from qa_sentinel.domain.enums import AgentName as A, TaskState as S
from qa_sentinel.domain.task import Task
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from qa_sentinel.models.config import RoleModelConfig
from qa_sentinel.models.base import ModelSettings
from qa_sentinel.orchestration.agent_execution import AgentExecutor
from qa_sentinel.orchestration.runner import WorkflowRunner
from qa_sentinel.persistence.database import create_engine, create_session_factory
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.repositories import ArtifactRepository
from qa_sentinel.execution.command_policy import ExecutionConfig, CommandRequest
from qa_sentinel.execution.command_runner import CommandRunner
from qa_sentinel.execution.pytest_runner import PytestRunner
from qa_sentinel.execution.service import TestExecutionService as ExecutionService, PytestTestResultProvider
from pathlib import Path


def setup(factory, root, mock):
    scenario, _ = division_scenario()
    config = RoleModelConfig(researcher=ModelSettings(model="configured-researcher", reasoning_effort="medium"),
                            planner=ModelSettings(model="configured-planner", reasoning_effort="high"))
    real = RealAgentRuntime(OpenAIModelAdapter(client=mock.client), config)
    fake = FakeAgentRuntime(scenario)
    runtime = CompositeAgentRuntime({role: real if role in {A.RESEARCHER, A.PLANNER} else fake for role in A})
    execution = ExecutionService(factory, PytestRunner(CommandRunner(ExecutionConfig(root,
        python_path=(Path(pytest.__file__).resolve().parents[1],)))))
    provider = PytestTestResultProvider(execution, CommandRequest(cwd=str(root), args=("-m", "pytest", "tests", "-q")))
    task = Task(title="Hybrid workflow", requirement=DIVISION_REQUIREMENT)
    with UnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.commit()
    return task, WorkflowRunner(factory, runtime, provider), runtime


def outputs():
    scenario, _ = division_scenario()
    return scenario.responses[A.RESEARCHER][0].output, scenario.responses[A.PLANNER][0].output


def test_hybrid_real_sdk_and_real_pytest_done_with_durable_provenance(migrated_factory, calculator_workspace, mock_openai):
    factory, engine, _ = migrated_factory
    mock = mock_openai(outputs())
    task, runner, _ = setup(factory, calculator_workspace(), mock)
    assert runner.run(task.id).state == S.DONE
    assert [call["model"] for call in mock.calls] == ["configured-researcher", "configured-planner"]
    fresh = create_engine(str(engine.url))
    try:
        with UnitOfWork(create_session_factory(fresh)) as uow:
            assert uow.tasks.get(task.id).state == S.DONE
            invocations = uow.invocations.list_by_task(task.id)
            assert len(invocations) == 4 and all(i.status.value == "COMPLETED" for i in invocations)
            for i in invocations:
                assert i.attempt == 1 and i.finished_at >= i.started_at
                if i.agent in {A.RESEARCHER, A.PLANNER}:
                    assert i.model == ("configured-researcher" if i.agent == A.RESEARCHER else "configured-planner")
                    assert i.reasoning_effort == ("medium" if i.agent == A.RESEARCHER else "high")
                else:
                    assert i.model == "fake" and i.reasoning_effort == "none"
            records = {i.id: i for i in invocations}
            for artifact in uow.artifacts.list_by_task(task.id):
                if artifact.invocation_id:
                    assert artifact.producer_agent == records[artifact.invocation_id].agent
                    assert artifact.producer_model == records[artifact.invocation_id].model
            events = uow.history.list_events(task.id)
            metadata = [e for e in events if "model_metadata" in e.payload]
            assert len(metadata) == 2
            assert all(e.payload["model_metadata"]["total_tokens"] == 30 and
                       e.payload["model_metadata"]["provider_response_id"] == "resp_mock_1" for e in metadata)
            run, = uow.history.list_test_runs(task.id)
            assert run.environment == "local-pytest" and run.outcome.value == "PASS" and run.passed_count == 3
            assert len(uow.history.list_gate_evaluations(task.id)) == 5
            assert len(uow.history.list_transitions(task.id)) == 6
            assert not uow.history.list_errors(task.id)
            persisted = json.dumps([e.model_dump(mode="json") for e in events])
            assert "synthetic-test-credential" not in persisted and "authorization" not in persisted.lower()
            assert "system_instructions" not in persisted and "output_text" not in persisted
    finally:
        fresh.dispose()


def test_rate_limit_uses_one_durable_retry_then_continues(migrated_factory, calculator_workspace, mock_openai):
    factory, _, _ = migrated_factory
    mock = mock_openai([429, *outputs()])
    task, runner, runtime = setup(factory, calculator_workspace(), mock)
    # First invocation fails; then recreate runner to prove durable budget/context ownership.
    runner._step(task)
    runner._step(runner._task(task.id))
    with UnitOfWork(factory) as uow:
        invocation, = uow.invocations.list_by_task(task.id)
        assert invocation.status.value == "FAILED"
        error, = uow.history.list_errors(task.id)
        assert error.code == "MODEL_RATE_LIMIT" and error.error_type.value == "AGENT_ERROR"
        retry, = [e for e in uow.history.list_events(task.id) if e.event_type == "RETRY_SCHEDULED"]
        assert retry.payload["domain"] == "RESEARCH" and retry.correlation.invocation_id == invocation.id
        assert "synthetic-sensitive" not in str(error)
    assert WorkflowRunner(factory, runtime, runner.test_provider).run(task.id).state == S.DONE
    assert len(mock.calls) == 3


def test_schema_correction_is_changed_input_and_gate_still_runs(migrated_factory, calculator_workspace, mock_openai):
    factory, _, _ = migrated_factory
    research, plan = outputs()
    mock = mock_openai([research, {"summary": "synthetic-secret-malformed"}, plan])
    task, runner, _ = setup(factory, calculator_workspace(), mock)
    assert runner.run(task.id).state == S.DONE
    assert len(mock.calls) == 3
    assert mock.calls[1]["input"] == mock.calls[2]["input"]
    assert "OUTPUT_SCHEMA_INVALID" not in mock.calls[1]["instructions"]
    assert "OUTPUT_SCHEMA_INVALID" in mock.calls[2]["instructions"]
    assert "synthetic-secret-malformed" not in json.dumps(mock.calls[2])
    with UnitOfWork(factory) as uow:
        errors = uow.history.list_errors(task.id)
        assert len(errors) == 1 and errors[0].error_type.value == "SCHEMA_ERROR"
        retries = [e for e in uow.history.list_events(task.id) if e.event_type == "RETRY_SCHEDULED"]
        assert len(retries) == 1 and retries[0].payload["domain"] == "SCHEMA_VALIDATION"
        invocations = sorted([i for i in uow.invocations.list_by_task(task.id) if i.agent == A.PLANNER], key=lambda i: i.attempt)
        assert [i.status.value for i in invocations] == ["FAILED", "COMPLETED"]
        assert all("synthetic-secret-malformed" not in str(a.content) for a in uow.artifacts.list_by_task(task.id))


@pytest.mark.parametrize("responses,expected_calls,code", [
    ([429, 429, 429], 3, "MODEL_RATE_LIMIT"),
    ([401], 1, "MODEL_AUTHENTICATION"),
    (["refusal"], 1, "MODEL_CONTENT_REFUSAL"),
    ([{}, {}], 2, "MODEL_MALFORMED_RESPONSE"),
])
def test_provider_failure_stops_safely_without_artifacts(migrated_factory, calculator_workspace, mock_openai,
                                                       responses, expected_calls, code):
    factory, _, _ = migrated_factory
    mock = mock_openai(responses)
    task, runner, _ = setup(factory, calculator_workspace(), mock)
    result = runner.run(task.id)
    assert result.state == S.BLOCKED and result.resume_state == S.RESEARCHING
    assert len(mock.calls) == expected_calls
    with UnitOfWork(factory) as uow:
        assert not uow.artifacts.list_by_task(task.id)
        errors = uow.history.list_errors(task.id)
        assert len(errors) == expected_calls and all(e.code == code for e in errors)
        retry_count = sum(e.event_type == "RETRY_SCHEDULED" for e in uow.history.list_events(task.id))
        assert retry_count == expected_calls - 1
        assert all(i.finished_at is not None for i in uow.invocations.list_by_task(task.id))


def test_completion_atomicity_preserves_started_without_duplicate_call(factory, mock_openai, monkeypatch):
    research, _ = outputs()
    mock = mock_openai([research])
    task = Task(title="Atomic model", requirement="Research", state=S.RESEARCHING)
    with UnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.commit()
    runtime = RealAgentRuntime(OpenAIModelAdapter(client=mock.client))
    original = ArtifactRepository.add
    def fail_after_insert(self, artifact):
        original(self, artifact)
        raise RuntimeError("injected persistence failure")
    monkeypatch.setattr(ArtifactRepository, "add", fail_after_insert)
    ctx = ResearchContext(task_id=task.id, attempt=1, requirement=task.requirement)
    with pytest.raises(RuntimeError, match="injected persistence"):
        AgentExecutor(factory, runtime).execute(A.RESEARCHER, ctx)
    with UnitOfWork(factory) as uow:
        invocation, = uow.invocations.list_by_task(task.id)
        assert invocation.status.value == "STARTED" and invocation.finished_at is None
        assert not uow.artifacts.list_by_task(task.id)
        assert [e.event_type for e in uow.history.list_events(task.id)] == ["AGENT_STARTED"]
    with pytest.raises(ValueError):
        AgentExecutor(factory, runtime).execute(A.RESEARCHER, ctx.model_copy(update={"attempt": 2}))
    assert len(mock.calls) == 1


def test_missing_credential_is_persisted_without_fake_fallback(factory):
    task = Task(title="No key", requirement="Research", state=S.RESEARCHING)
    with UnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.commit()
    execution = AgentExecutor(factory, RealAgentRuntime(OpenAIModelAdapter())).execute(A.RESEARCHER,
        ResearchContext(task_id=task.id, attempt=1, requirement=task.requirement))
    assert execution.invocation.status.value == "BLOCKED" and execution.invocation.model != "fake"
    assert execution.error.code == "MODEL_CONFIGURATION"
    assert execution.error.error_type.value == "EXTERNAL_BLOCKER"
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(task.id).state == S.RESEARCHING
        assert not uow.artifacts.list_by_task(task.id)


@pytest.mark.parametrize("role", [A.RESEARCHER, A.PLANNER])
def test_valid_model_outputs_cannot_bypass_gates(migrated_factory, calculator_workspace, mock_openai, role):
    factory, _, _ = migrated_factory
    research, plan = outputs()
    if role == A.RESEARCHER:
        sequence = [research.model_copy(update={"research_complete": False})]
    else:
        sequence = [research, plan.model_copy(update={"test_strategy": (
            plan.test_strategy[0].model_copy(update={"acceptance_criteria_refs": ("AC-unseen",)}),)})]
    mock = mock_openai(sequence)
    task, runner, _ = setup(factory, calculator_workspace(), mock)
    stopped = runner.run(task.id)
    assert stopped.state == S.BLOCKED
    assert stopped.resume_state == (S.RESEARCHING if role == A.RESEARCHER else S.PLANNING)
    with UnitOfWork(factory) as uow:
        assert all(i.status.value == "COMPLETED" for i in uow.invocations.list_by_task(task.id))
        assert not uow.history.list_test_runs(task.id)
        assert any(g.result.value == "FAIL" for g in uow.history.list_gate_evaluations(task.id))


def test_schema_correction_survives_runner_recreation(migrated_factory, calculator_workspace, mock_openai):
    factory, _, _ = migrated_factory
    mock = mock_openai([{}, *outputs()])
    task, runner, runtime = setup(factory, calculator_workspace(), mock)
    runner._step(task)
    runner._step(runner._task(task.id))
    fresh = WorkflowRunner(factory, runtime, runner.test_provider)
    ctx = fresh.build_context(fresh._task(task.id), A.RESEARCHER)
    assert ctx.schema_correction and ctx.attempt == 2
    assert fresh.run(task.id).state == S.DONE
    assert "OUTPUT_SCHEMA_INVALID" in mock.calls[1]["instructions"]


def test_model_call_has_no_open_write_transaction_and_cannot_progress_state(migrated_factory, mock_openai):
    factory, engine, _ = migrated_factory
    mock = mock_openai([outputs()[0]])
    task = Task(title="No held transaction", requirement="Research", state=S.RESEARCHING)
    with UnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.commit()
    real = RealAgentRuntime(OpenAIModelAdapter(client=mock.client))
    original = real.adapter.generate
    def during_call(*args):
        fresh = create_engine(str(engine.url))
        try:
            with UnitOfWork(create_session_factory(fresh)) as uow:
                snapshot = uow.tasks.get(task.id)
                assert snapshot.state == S.RESEARCHING
                invocation = uow.invocations.get(snapshot.current_invocation_id)
                assert invocation.status.value == "STARTED"
                unrelated = Task(title="Independent writer", requirement="Control remains orchestration")
                uow.tasks.add(unrelated)
                uow.commit()
        finally:
            fresh.dispose()
        return original(*args)
    real.adapter.generate = during_call
    result = AgentExecutor(factory, real).execute(A.RESEARCHER,
        ResearchContext(task_id=task.id, attempt=1, requirement=task.requirement))
    assert result.invocation.status.value == "COMPLETED"
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(task.id).state == S.RESEARCHING
