"""Mocked real reasoning + real pytest; fixture harness alone switches prepared code."""
import json
from dataclasses import dataclass
from pathlib import Path
import pytest
from qa_sentinel.agents.real import RealAgentRuntime
from qa_sentinel.agents.composite import CompositeAgentRuntime
from qa_sentinel.agents.fake import FakeAgentRuntime, FakeScenario
from qa_sentinel.agents.scenarios import division_scenario, DIVISION_REQUIREMENT
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.enums import (AgentName as A, TaskState as S, ArtifactType,
                                     CoverageStatus, ReviewDecision, InvestigationActionType)
from qa_sentinel.models.config import RoleModelConfig
from qa_sentinel.models.base import ModelSettings
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from qa_sentinel.orchestration.runner import WorkflowRunner, RunnerStoppedError
from qa_sentinel.orchestration.reliability_policy import ReliabilityConfig
from qa_sentinel.persistence.database import create_engine, create_session_factory
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.repositories import HistoryRepository, ArtifactRepository
from qa_sentinel.execution.command_policy import ExecutionConfig, CommandRequest
from qa_sentinel.execution.command_runner import CommandRunner
from qa_sentinel.execution.pytest_runner import PytestRunner
from qa_sentinel.execution.service import TestExecutionService as ExecutionService, PytestTestResultProvider


def outputs():
    scenario, _ = division_scenario(repair=True)
    return {role: responses[0].output for role, responses in scenario.responses.items()}


class PreparedRetestHarness:
    def __init__(self, provider, prepare, *, repair=True):
        self.provider, self.prepare, self.repair = provider, prepare, repair

    def run(self, context):
        if context.attempt > 1 and self.repair:
            # Explicit synthetic fixture switch outside every agent/runtime.
            self.prepare(failing=False)
        return self.provider.run(context)

    def failure_identity(self, context):
        return self.provider.failure_identity(context)

    def execution_failure(self, run):
        return self.provider.execution_failure(run)


@dataclass
class Harness:
    factory: object
    task: Task
    runner: WorkflowRunner
    runtime: CompositeAgentRuntime
    provider: PreparedRetestHarness
    mock: object


def setup(factory, prepare, mock, *, first_fail=True, repair=True, config=None, conflict=False):
    root = prepare(failing=first_fail)
    scenario, _ = division_scenario(repair=True)
    scenario = FakeScenario(responses=scenario.responses, repeat_last=True)
    models = RoleModelConfig(**{field: ModelSettings(model="real-" + field, reasoning_effort="high")
        for field in ("researcher", "planner", "test_analyzer", "investigator", "investigator_escalated", "reviewer")})
    real = RealAgentRuntime(OpenAIModelAdapter(client=mock.client), models)
    fake = FakeAgentRuntime(scenario)
    runtime = CompositeAgentRuntime({role: fake if role == A.IMPLEMENTER else real for role in A})
    service = ExecutionService(factory, PytestRunner(CommandRunner(ExecutionConfig(root,
        python_path=(Path(pytest.__file__).resolve().parents[1],)))))
    provider = PreparedRetestHarness(PytestTestResultProvider(service,
        CommandRequest(cwd=str(root), args=("-m", "pytest", "tests", "-q"))), prepare, repair=repair)
    task = Task(title="Task 8 failure reasoning", requirement=DIVISION_REQUIREMENT)
    with UnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.commit()
    runner = WorkflowRunner(factory, runtime, provider, reliability_config=config,
                            investigation_evidence_conflict=conflict)
    return Harness(factory, task, runner, runtime, provider, mock)


def advance(harness, stage):
    for _ in range(30):
        task = harness.runner._task(harness.task.id)
        if task.state == stage:
            return task
        assert task.state not in {S.DONE, S.BLOCKED, S.FAILED}
        harness.runner._step(task)
    raise AssertionError("Stage was not reached")


def ordinary_sequence(values):
    return [values[A.RESEARCHER], values[A.PLANNER], values[A.TEST_ANALYZER],
            values[A.INVESTIGATOR], values[A.REVIEWER]]


def test_full_real_reasoning_failure_fix_retest_done_and_reopen(migrated_factory, calculator_workspace, mock_openai):
    factory, engine, _ = migrated_factory
    values = outputs()
    mock = mock_openai(ordinary_sequence(values))
    h = setup(factory, calculator_workspace, mock)
    assert h.runner.run(h.task.id).state == S.DONE
    assert [c["model"] for c in mock.calls] == ["real-" + role for role in
        ("researcher", "planner", "test_analyzer", "investigator", "reviewer")]
    fresh = create_engine(str(engine.url))
    try:
        with UnitOfWork(create_session_factory(fresh)) as uow:
            transitions = uow.history.list_transitions(h.task.id)
            edges = {(t.from_state.value, t.to_state.value) for t in transitions}
            assert len(transitions) == 10
            assert {("TESTING", "ANALYZING"), ("ANALYZING", "INVESTIGATING"),
                    ("INVESTIGATING", "IMPLEMENTING"), ("REVIEWING", "DONE")} <= edges
            runs = sorted(uow.history.list_test_runs(h.task.id), key=lambda r: r.started_at)
            assert [r.outcome.value for r in runs] == ["FAIL", "PASS"]
            assert all(r.environment == "local-pytest" and r.execution_status.value == "COMPLETED" for r in runs)
            assert runs[0].failed_count == 1 and runs[1].failed_count == 0
            assert runs[0].implementation_artifact_id != runs[1].implementation_artifact_id
            invocations = uow.invocations.list_by_task(h.task.id)
            assert len(invocations) == 7
            assert len([i for i in invocations if i.agent == A.IMPLEMENTER and i.model == "fake"]) == 2
            assert all(i.status.value == "COMPLETED" for i in invocations)
            records = {i.id: i for i in invocations}
            for artifact in uow.artifacts.list_by_task(h.task.id):
                if artifact.invocation_id:
                    assert artifact.producer_model == records[artifact.invocation_id].model
                    assert artifact.producer_agent == records[artifact.invocation_id].agent
            events = uow.history.list_events(h.task.id)
            assert sum("model_metadata" in e.payload for e in events) == 5
            assert not any(e.event_type == "MODEL_ESCALATED" for e in events)
            assert not uow.history.list_errors(h.task.id)
            assert uow.tasks.get(h.task.id).defect_cycle == 1
            assert all(c["tools"] == [] and c["tool_choice"] == "none" for c in mock.calls)
    finally:
        fresh.dispose()


def test_explicit_escalation_reservation_survives_reopen_and_selects_second_artifact(
        migrated_factory, calculator_workspace, mock_openai):
    factory, engine, _ = migrated_factory
    values = outputs()
    low = values[A.INVESTIGATOR].model_copy(update={"confidence": 0.1, "root_cause": "Primary hypothesis"})
    selected = values[A.INVESTIGATOR].model_copy(update={"root_cause": "Selected stronger hypothesis"})
    mock = mock_openai([values[A.RESEARCHER], values[A.PLANNER], values[A.TEST_ANALYZER], low, selected, values[A.REVIEWER]])
    h = setup(factory, calculator_workspace, mock)
    task = advance(h, S.INVESTIGATING)
    h.runner._step(task)
    with UnitOfWork(factory) as uow:
        primary, = [a for a in uow.artifacts.list_by_task(task.id) if a.artifact_type == ArtifactType.INVESTIGATION]
        reservation, = [e for e in uow.history.list_events(task.id) if e.event_type == "MODEL_ESCALATED"]
        assert reservation.correlation.artifact_id == primary.id
        assert reservation.payload["target_model"] == "real-investigator_escalated"
        assert reservation.payload["reason_codes"] == ["LOW_CONFIDENCE"]
        assert uow.tasks.get(task.id).state == S.INVESTIGATING
    assert len(mock.calls) == 4
    fresh = create_engine(str(engine.url))
    try:
        fresh_factory = create_session_factory(fresh)
        runner = WorkflowRunner(fresh_factory, h.runtime, h.provider)
        assert runner.run(task.id).state == S.DONE
        with UnitOfWork(fresh_factory) as uow:
            investigations = [a for a in uow.artifacts.list_by_task(task.id) if a.artifact_type == ArtifactType.INVESTIGATION]
            assert len(investigations) == 2 and uow.artifacts.get(primary.id) == primary
            escalated, = [a for a in investigations if a.id != primary.id]
            assert escalated.producer_model == "real-investigator_escalated"
            assert escalated.content["root_cause"] == "Selected stronger hypothesis"
            assert any(e.event_type == "STATE_TRANSITIONED" and e.correlation.artifact_id == escalated.id
                       for e in uow.history.list_events(task.id))
            assert not any(e.event_type == "STATE_TRANSITIONED" and e.correlation.artifact_id == primary.id
                           for e in uow.history.list_events(task.id))
            assert sum(e.event_type == "MODEL_ESCALATED" for e in uow.history.list_events(task.id)) == 1
            second = uow.invocations.get(escalated.invocation_id)
            assert second.attempt == 2 and second.reasoning_effort == "high"
            assert any(e.event_type == "AGENT_COMPLETED" and e.correlation.invocation_id == second.id and
                e.payload["escalation_decision_id"] == str(reservation.correlation.decision_id)
                for e in uow.history.list_events(task.id))
        data = json.loads(mock.calls[4]["input"][0]["content"])
        assert data["escalation"]["primary_investigation"]["root_cause"] == "Primary hypothesis"
        assert len(mock.calls) == 6
    finally:
        fresh.dispose()


@pytest.mark.parametrize("signal", ["hypotheses", "conflict", "defect_cycle", "repeated"])
def test_existing_policy_signals_reserve_explicit_escalation(migrated_factory, calculator_workspace, mock_openai, signal):
    factory, _, _ = migrated_factory
    values = outputs()
    output = values[A.INVESTIGATOR]
    if signal == "hypotheses":
        output = output.model_copy(update={"alternative_hypotheses": ("A", "B", "C")})
    elif signal == "repeated":
        output = output.model_copy(update={"confidence": 0.7})
    mock = mock_openai([values[A.RESEARCHER], values[A.PLANNER], values[A.TEST_ANALYZER], output])
    h = setup(factory, calculator_workspace, mock, conflict=signal == "conflict")
    task = advance(h, S.INVESTIGATING)
    if signal == "defect_cycle":
        with UnitOfWork(factory) as uow:
            changed = uow.tasks.get(task.id)
            changed.defect_cycle = 2
            uow.tasks.save(changed)
            uow.commit()
        task = h.runner._task(task.id)
    if signal == "repeated":
        # A prior failed provider invocation consumes an attempt, not escalation budget.
        from qa_sentinel.orchestration.agent_execution import AgentExecutor
        from qa_sentinel.models.base import ModelError, ProviderErrorCategory
        class Transient:
            def run(self, *args):
                raise ModelError(ProviderErrorCategory.RATE_LIMIT)
        first = AgentExecutor(factory, Transient()).execute(A.INVESTIGATOR, h.runner.build_context(task, A.INVESTIGATOR))
        h.runner._recover(task, A.INVESTIGATOR, first)
        task = h.runner._task(task.id)
    h.runner._step(task)
    expected = {"hypotheses": "MULTIPLE_HYPOTHESES", "conflict": "EVIDENCE_CONFLICT",
                "defect_cycle": "REPEATED_DEFECT_CYCLE", "repeated": "REPEATED_LOW_CONFIDENCE"}[signal]
    with UnitOfWork(factory) as uow:
        event, = [e for e in uow.history.list_events(task.id) if e.event_type == "MODEL_ESCALATED"]
        assert expected in event.payload["reason_codes"]
    assert len(mock.calls) == 4


@pytest.mark.parametrize("coverage", ["NOT_COVERED", "UNVERIFIED", "NO_EVIDENCE"])
def test_reviewer_approve_cannot_bypass_coverage_gate(migrated_factory, calculator_workspace, mock_openai, coverage):
    factory, _, _ = migrated_factory
    values = outputs()
    rows = list(values[A.REVIEWER].requirement_coverage)
    rows[0] = rows[0].model_copy(update={"evidence_refs": ()} if coverage == "NO_EVIDENCE" else {"status": CoverageStatus(coverage)})
    review = values[A.REVIEWER].model_copy(update={"requirement_coverage": tuple(rows)})
    mock = mock_openai([values[A.RESEARCHER], values[A.PLANNER], review])
    h = setup(factory, calculator_workspace, mock, first_fail=False)
    result = h.runner.run(h.task.id)
    assert result.state == S.BLOCKED and result.resume_state == S.REVIEWING
    with UnitOfWork(factory) as uow:
        assert any(g.gate_name == "REVIEW_GATE" and g.result.value == "FAIL"
                   for g in uow.history.list_gate_evaluations(h.task.id))
        assert not any(t.to_state == S.DONE for t in uow.history.list_transitions(h.task.id))


def test_reviewer_request_changes_runs_new_fake_implementation_and_real_test(migrated_factory, calculator_workspace, mock_openai):
    factory, _, _ = migrated_factory
    values = outputs()
    request = values[A.REVIEWER].model_copy(update={"decision": ReviewDecision.REQUEST_CHANGES})
    mock = mock_openai([values[A.RESEARCHER], values[A.PLANNER], request, values[A.REVIEWER]])
    h = setup(factory, calculator_workspace, mock, first_fail=False)
    assert h.runner.run(h.task.id).state == S.DONE
    with UnitOfWork(factory) as uow:
        assert any(t.from_state == S.REVIEWING and t.to_state == S.IMPLEMENTING
                   for t in uow.history.list_transitions(h.task.id))
        assert len(uow.history.list_test_runs(h.task.id)) == 2
        assert uow.tasks.get(h.task.id).implementation_attempt == 2
        assert uow.tasks.get(h.task.id).review_cycle == 2


def test_investigator_human_action_blocks_without_repair(migrated_factory, calculator_workspace, mock_openai):
    factory, _, _ = migrated_factory
    values = outputs()
    human = values[A.INVESTIGATOR].model_copy(update={"recommended_action":
        values[A.INVESTIGATOR].recommended_action.model_copy(update={"type": InvestigationActionType.HUMAN_ACTION})})
    mock = mock_openai([values[A.RESEARCHER], values[A.PLANNER], values[A.TEST_ANALYZER], human])
    h = setup(factory, calculator_workspace, mock)
    result = h.runner.run(h.task.id)
    assert result.state == S.BLOCKED and result.resume_state == S.INVESTIGATING
    with UnitOfWork(factory) as uow:
        assert len(uow.history.list_test_runs(h.task.id)) == 1
        assert sum(i.agent == A.IMPLEMENTER for i in uow.invocations.list_by_task(h.task.id)) == 1


@pytest.mark.parametrize("role", [A.TEST_ANALYZER, A.INVESTIGATOR, A.REVIEWER])
def test_new_role_schema_retry_is_explicit_and_bounded(migrated_factory, calculator_workspace, mock_openai, role):
    factory, _, _ = migrated_factory
    values = outputs()
    sequence = ordinary_sequence(values)
    index = {A.TEST_ANALYZER: 2, A.INVESTIGATOR: 3, A.REVIEWER: 4}[role]
    sequence.insert(index, {"malformed": "synthetic-secret-malformation"})
    mock = mock_openai(sequence)
    h = setup(factory, calculator_workspace, mock)
    assert h.runner.run(h.task.id).state == S.DONE
    assert "OUTPUT_SCHEMA_INVALID" in mock.calls[index + 1]["instructions"]
    assert mock.calls[index]["input"] == mock.calls[index + 1]["input"]
    with UnitOfWork(factory) as uow:
        errors = uow.history.list_errors(h.task.id)
        assert len(errors) == 1 and errors[0].error_type.value == "SCHEMA_ERROR"
        retry, = [e for e in uow.history.list_events(h.task.id) if e.event_type == "RETRY_SCHEDULED"]
        assert retry.payload["domain"] == "SCHEMA_VALIDATION"
        assert sum(i.agent == role for i in uow.invocations.list_by_task(h.task.id)) == 2
        assert all("synthetic-secret-malformation" not in str(a.content) for a in uow.artifacts.list_by_task(h.task.id))


@pytest.mark.parametrize("role", [A.TEST_ANALYZER, A.INVESTIGATOR, A.REVIEWER])
def test_new_role_refusal_persists_sanitized_failure_and_never_artifact(migrated_factory, calculator_workspace, mock_openai, role):
    factory, _, _ = migrated_factory
    values = outputs()
    index = {A.TEST_ANALYZER: 2, A.INVESTIGATOR: 3, A.REVIEWER: 4}[role]
    mock = mock_openai(ordinary_sequence(values)[:index] + ["refusal"])
    h = setup(factory, calculator_workspace, mock)
    if role == A.TEST_ANALYZER:
        with pytest.raises(RunnerStoppedError):
            h.runner.run(h.task.id)
        assert h.runner._task(h.task.id).state == S.ANALYZING
    else:
        assert h.runner.run(h.task.id).state == S.BLOCKED
    with UnitOfWork(factory) as uow:
        assert not any(a.producer_agent == role for a in uow.artifacts.list_by_task(h.task.id))
        assert any(e.code == "MODEL_CONTENT_REFUSAL" for e in uow.history.list_errors(h.task.id))
        persisted = str(uow.history.list_errors(h.task.id)) + str(uow.history.list_events(h.task.id))
        assert "synthetic-sensitive-refusal" not in persisted
    assert len(mock.calls) == index + 1


def test_exhausted_escalation_budget_stops_later_primary_without_another_escalated_call(
        migrated_factory, calculator_workspace, mock_openai):
    factory, _, _ = migrated_factory
    values = outputs()
    low = values[A.INVESTIGATOR].model_copy(update={"confidence": 0.1})
    mock = mock_openai([values[A.RESEARCHER], values[A.PLANNER], values[A.TEST_ANALYZER], low,
        values[A.INVESTIGATOR], values[A.TEST_ANALYZER], low])
    h = setup(factory, calculator_workspace, mock, repair=False)
    result = h.runner.run(h.task.id)
    assert result.state == S.BLOCKED and result.resume_state == S.INVESTIGATING
    assert sum(c["model"] == "real-investigator_escalated" for c in mock.calls) == 1
    with UnitOfWork(factory) as uow:
        assert sum(e.event_type == "MODEL_ESCALATED" for e in uow.history.list_events(h.task.id)) == 1
        assert sum(i.agent == A.INVESTIGATOR for i in uow.invocations.list_by_task(h.task.id)) == 3
        assert any(d.reason_code == "ESCALATION_BUDGET_EXHAUSTED" for d in uow.history.list_decisions(h.task.id))


def test_transient_investigator_exhaustion_reuses_existing_budget(migrated_factory, calculator_workspace, mock_openai):
    factory, _, _ = migrated_factory
    values = outputs()
    mock = mock_openai([values[A.RESEARCHER], values[A.PLANNER], values[A.TEST_ANALYZER], 429, 429, 429])
    h = setup(factory, calculator_workspace, mock)
    assert h.runner.run(h.task.id).state == S.BLOCKED
    with UnitOfWork(factory) as uow:
        retries = [e for e in uow.history.list_events(h.task.id) if e.event_type == "RETRY_SCHEDULED"]
        assert len(retries) == 2 and all(e.payload["domain"] == "INVESTIGATION" for e in retries)
        assert not any(a.artifact_type == ArtifactType.INVESTIGATION for a in uow.artifacts.list_by_task(h.task.id))


def test_escalation_event_rollback_preserves_primary_and_budget(migrated_factory, calculator_workspace, mock_openai, monkeypatch):
    factory, _, _ = migrated_factory
    values = outputs()
    low = values[A.INVESTIGATOR].model_copy(update={"confidence": 0.1})
    mock = mock_openai([values[A.RESEARCHER], values[A.PLANNER], values[A.TEST_ANALYZER], low,
                        values[A.INVESTIGATOR], values[A.REVIEWER]])
    h = setup(factory, calculator_workspace, mock)
    task = advance(h, S.INVESTIGATING)
    original = HistoryRepository.append_event
    def fail(self, event):
        original(self, event)
        if event.event_type == "MODEL_ESCALATED":
            raise RuntimeError("injected escalation commit failure")
    monkeypatch.setattr(HistoryRepository, "append_event", fail)
    with pytest.raises(RuntimeError, match="injected escalation"):
        h.runner._step(task)
    with UnitOfWork(factory) as uow:
        assert not any(e.event_type == "MODEL_ESCALATED" for e in uow.history.list_events(task.id))
        assert len([a for a in uow.artifacts.list_by_task(task.id) if a.artifact_type == ArtifactType.INVESTIGATION]) == 1
    monkeypatch.setattr(HistoryRepository, "append_event", original)
    assert WorkflowRunner(factory, h.runtime, h.provider).run(task.id).state == S.DONE
    assert len(mock.calls) == 6


def test_escalated_completion_rollback_never_falls_back_to_primary(migrated_factory, calculator_workspace, mock_openai, monkeypatch):
    factory, _, _ = migrated_factory
    values = outputs()
    low = values[A.INVESTIGATOR].model_copy(update={"confidence": 0.1})
    mock = mock_openai([values[A.RESEARCHER], values[A.PLANNER], values[A.TEST_ANALYZER], low, values[A.INVESTIGATOR]])
    h = setup(factory, calculator_workspace, mock)
    task = advance(h, S.INVESTIGATING)
    h.runner._step(task)
    original = ArtifactRepository.add
    def fail(self, artifact):
        original(self, artifact)
        if artifact.producer_model == "real-investigator_escalated":
            raise RuntimeError("injected escalated completion failure")
    monkeypatch.setattr(ArtifactRepository, "add", fail)
    with pytest.raises(RuntimeError, match="injected escalated"):
        h.runner._step(h.runner._task(task.id))
    with UnitOfWork(factory) as uow:
        invocations = sorted([i for i in uow.invocations.list_by_task(task.id) if i.agent == A.INVESTIGATOR], key=lambda i: i.attempt)
        assert [i.status.value for i in invocations] == ["COMPLETED", "STARTED"]
        assert sum(e.event_type == "MODEL_ESCALATED" for e in uow.history.list_events(task.id)) == 1
        assert len([a for a in uow.artifacts.list_by_task(task.id) if a.artifact_type == ArtifactType.INVESTIGATION]) == 1
    with pytest.raises(RunnerStoppedError):
        WorkflowRunner(factory, h.runtime, h.provider).run(task.id)
    assert len(mock.calls) == 5


def test_defect_cycle_limit_stops_before_another_repair(migrated_factory, calculator_workspace, mock_openai):
    factory, _, _ = migrated_factory
    mock = mock_openai(ordinary_sequence(outputs())[:-1])
    h = setup(factory, calculator_workspace, mock, config=ReliabilityConfig(max_defect_cycles=0))
    assert h.runner.run(h.task.id).state == S.BLOCKED
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(h.task.id).defect_cycle == 0
        assert sum(i.agent == A.IMPLEMENTER for i in uow.invocations.list_by_task(h.task.id)) == 1


def test_escalated_transient_retry_stays_on_reserved_model(migrated_factory, calculator_workspace, mock_openai):
    factory, _, _ = migrated_factory
    values = outputs()
    low = values[A.INVESTIGATOR].model_copy(update={"confidence": 0.1})
    mock = mock_openai([values[A.RESEARCHER], values[A.PLANNER], values[A.TEST_ANALYZER], low,
                        429, values[A.INVESTIGATOR], values[A.REVIEWER]])
    h = setup(factory, calculator_workspace, mock)
    assert h.runner.run(h.task.id).state == S.DONE
    with UnitOfWork(factory) as uow:
        invocations = sorted([i for i in uow.invocations.list_by_task(h.task.id) if i.agent == A.INVESTIGATOR], key=lambda i: i.attempt)
        assert [i.status.value for i in invocations] == ["COMPLETED", "FAILED", "COMPLETED"]
        assert [i.model for i in invocations] == ["real-investigator", "real-investigator_escalated", "real-investigator_escalated"]
        assert sum(e.event_type == "MODEL_ESCALATED" for e in uow.history.list_events(h.task.id)) == 1
        assert sum(e.event_type == "RETRY_SCHEDULED" for e in uow.history.list_events(h.task.id)) == 1


def test_invalid_escalated_candidate_cannot_fall_back_or_bypass_investigation_gate(
        migrated_factory, calculator_workspace, mock_openai):
    factory, _, _ = migrated_factory
    values = outputs()
    low = values[A.INVESTIGATOR].model_copy(update={"confidence": 0.1})
    insufficient = values[A.INVESTIGATOR].model_copy(update={"root_cause": None, "evidence": ()})
    mock = mock_openai([values[A.RESEARCHER], values[A.PLANNER], values[A.TEST_ANALYZER], low, insufficient])
    h = setup(factory, calculator_workspace, mock)
    result = h.runner.run(h.task.id)
    assert result.state == S.BLOCKED and result.resume_state == S.INVESTIGATING
    with UnitOfWork(factory) as uow:
        assert any(g.gate_name == "INVESTIGATION_GATE" and g.result.value != "PASS"
                   for g in uow.history.list_gate_evaluations(h.task.id))
        assert sum(i.agent == A.IMPLEMENTER for i in uow.invocations.list_by_task(h.task.id)) == 1
        assert sum(a.artifact_type == ArtifactType.INVESTIGATION for a in uow.artifacts.list_by_task(h.task.id)) == 2
    assert len(mock.calls) == 5


@pytest.mark.parametrize("role", [A.TEST_ANALYZER, A.INVESTIGATOR, A.REVIEWER])
def test_repeated_malformed_new_role_output_stops_after_one_changed_input_retry(
        migrated_factory, calculator_workspace, mock_openai, role):
    factory, _, _ = migrated_factory
    values = outputs()
    index = {A.TEST_ANALYZER: 2, A.INVESTIGATOR: 3, A.REVIEWER: 4}[role]
    mock = mock_openai(ordinary_sequence(values)[:index] + [{}, {}])
    h = setup(factory, calculator_workspace, mock)
    if role == A.TEST_ANALYZER:
        with pytest.raises(RunnerStoppedError):
            h.runner.run(h.task.id)
    else:
        assert h.runner.run(h.task.id).state == S.BLOCKED
    with UnitOfWork(factory) as uow:
        assert sum(i.agent == role for i in uow.invocations.list_by_task(h.task.id)) == 2
        assert sum(e.event_type == "RETRY_SCHEDULED" for e in uow.history.list_events(h.task.id)) == 1
        assert any(d.reason_code == "CHANGED_INPUT_REQUIRED" for d in uow.history.list_decisions(h.task.id))
        assert not any(a.producer_agent == role for a in uow.artifacts.list_by_task(h.task.id))
    assert len(mock.calls) == index + 2
