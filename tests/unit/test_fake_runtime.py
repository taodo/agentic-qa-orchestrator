from uuid import uuid4
import pytest
from pydantic import ValidationError
from qa_sentinel.agents.base import (
    STATE_AGENTS, ARTIFACT_TYPES, OUTPUT_TYPES, ResearchContext, PlanContext, TestContext as RunContext,
)
from qa_sentinel.agents.fake import (
    FakeAgentRuntime, FakeScenario, FakeResponse, AgentError, SchemaOutputError, ScenarioExhaustedError,
)
from qa_sentinel.agents.scenarios import division_scenario, DIVISION_REQUIREMENT
from qa_sentinel.domain.enums import (
    AgentName as A, TaskState as S, ArtifactType, InvestigationActionType, PlannerDecision, ReviewDecision,
)
from qa_sentinel.domain.task import Task
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.repositories import ArtifactRepository, HistoryRepository
from qa_sentinel.execution.fake import FakeTestResultProvider
from qa_sentinel.orchestration.agent_execution import AgentExecutor
from qa_sentinel.orchestration.runner import WorkflowRunner, planner_target, investigation_target, review_target
from qa_sentinel.orchestration.reliability_policy import FailureDisposition as D


def test_actor_and_artifact_mappings_cover_only_agent_stages():
    assert STATE_AGENTS == {S.RESEARCHING: A.RESEARCHER, S.PLANNING: A.PLANNER, S.IMPLEMENTING: A.IMPLEMENTER,
                           S.ANALYZING: A.TEST_ANALYZER, S.INVESTIGATING: A.INVESTIGATOR, S.REVIEWING: A.REVIEWER}
    assert ARTIFACT_TYPES == {A.RESEARCHER: ArtifactType.RESEARCH, A.PLANNER: ArtifactType.PLAN,
        A.IMPLEMENTER: ArtifactType.IMPLEMENTATION, A.TEST_ANALYZER: ArtifactType.TEST_ANALYSIS,
        A.INVESTIGATOR: ArtifactType.INVESTIGATION, A.REVIEWER: ArtifactType.REVIEW}
    assert set(OUTPUT_TYPES) == set(A)


def test_fake_sequences_are_task_local_and_attempt_driven():
    scenario, _ = division_scenario()
    good = scenario.responses[A.RESEARCHER][0]
    runtime = FakeAgentRuntime(FakeScenario(responses={A.RESEARCHER: (FakeResponse(failure=D.TRANSIENT), good)}))
    task_id = uuid4()
    with pytest.raises(AgentError) as exc:
        runtime.run(A.RESEARCHER, ResearchContext(task_id=task_id, attempt=1, requirement="Requirement"))
    assert exc.value.disposition == D.TRANSIENT
    output = runtime.run(A.RESEARCHER, ResearchContext(task_id=task_id, attempt=2, requirement="Requirement"))
    assert output == good.output and type(output) is OUTPUT_TYPES[A.RESEARCHER]
    # Sharing a runtime does not share mutable scenario cursor state.
    with pytest.raises(AgentError):
        runtime.run(A.RESEARCHER, ResearchContext(task_id=uuid4(), attempt=1, requirement="Requirement"))
    with pytest.raises(ScenarioExhaustedError):
        runtime.run(A.RESEARCHER, ResearchContext(task_id=task_id, attempt=3, requirement="Requirement"))


def test_invalid_raw_and_wrong_typed_output_rejected():
    scenario, _ = division_scenario()
    context = ResearchContext(task_id=uuid4(), attempt=1, requirement="Requirement")
    runtime = FakeAgentRuntime(FakeScenario(responses={A.RESEARCHER: (
        FakeResponse(raw_output={"secret": "do-not-record"}, changed_input=True),)}))
    with pytest.raises(SchemaOutputError) as exc:
        runtime.run(A.RESEARCHER, context)
    assert exc.value.changed_input and "do-not-record" not in str(exc.value)
    wrong = FakeAgentRuntime(FakeScenario(responses={A.RESEARCHER: scenario.responses[A.PLANNER]}))
    with pytest.raises(SchemaOutputError):
        wrong.run(A.RESEARCHER, context)
    with pytest.raises(TypeError):
        FakeAgentRuntime(scenario).run(A.PLANNER, context)


def test_scenario_configuration_rejects_ambiguous_responses():
    with pytest.raises(ValueError):
        FakeResponse()
    with pytest.raises(ValueError):
        FakeResponse(raw_output={}, failure=D.TRANSIENT)
    with pytest.raises(ValueError):
        FakeScenario(responses={A.RESEARCHER: ()})


def test_fake_test_provider_sequences_without_classifying():
    _, results = division_scenario(repair=True)
    provider = FakeTestResultProvider(results)
    task_id, implementation_id = uuid4(), uuid4()
    first = provider.run(RunContext(task_id=task_id, attempt=1, implementation_artifact_id=implementation_id))
    second = provider.run(RunContext(task_id=task_id, attempt=2, implementation_artifact_id=implementation_id))
    assert first.outcome.value == "FAIL" and second.outcome.value == "PASS"
    assert first.execution_status.value == "COMPLETED" and first.task_id == task_id
    assert first.implementation_artifact_id == implementation_id and first.environment == "fake"
    with pytest.raises(ScenarioExhaustedError):
        provider.run(RunContext(task_id=task_id, attempt=3, implementation_artifact_id=implementation_id))


def test_enum_routes_do_not_read_descriptions():
    scenario, _ = division_scenario(repair=True)
    plan = scenario.responses[A.PLANNER][0].output
    assert [planner_target(plan.model_copy(update={"decision": d})) for d in PlannerDecision] == [S.IMPLEMENTING, S.RESEARCHING, S.BLOCKED]
    investigation = scenario.responses[A.INVESTIGATOR][0].output
    targets = {InvestigationActionType.CODE_FIX: S.IMPLEMENTING, InvestigationActionType.TEST_FIX: S.IMPLEMENTING,
               InvestigationActionType.MORE_RESEARCH: S.RESEARCHING, InvestigationActionType.HUMAN_ACTION: S.BLOCKED}
    for action, target in targets.items():
        changed = investigation.model_copy(update={"recommended_action": investigation.recommended_action.model_copy(
            update={"type": action, "description": "Do something completely unrelated"})})
        assert investigation_target(changed) == target
    review = scenario.responses[A.REVIEWER][0].output
    assert {d: review_target(review.model_copy(update={"decision": d})) for d in ReviewDecision} == {
        ReviewDecision.APPROVE: S.DONE, ReviewDecision.REQUEST_CHANGES: S.IMPLEMENTING,
        ReviewDecision.NEEDS_EVIDENCE: S.BLOCKED, ReviewDecision.BLOCKED: S.BLOCKED}


def test_invocation_completion_links_artifact_and_counters(factory):
    scenario, _ = division_scenario()
    task = Task(title="Division", requirement=DIVISION_REQUIREMENT, state=S.RESEARCHING)
    with UnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.commit()
    context = ResearchContext(task_id=task.id, attempt=1, requirement=task.requirement)
    executor = AgentExecutor(factory, FakeAgentRuntime(scenario))
    result = executor.execute(A.RESEARCHER, context)
    assert result.invocation.status.value == "COMPLETED" and result.invocation.finished_at is not None
    assert result.artifact.invocation_id == result.invocation.id
    assert result.artifact.content == result.output.model_dump(mode="json")
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(task.id).state == S.RESEARCHING
        assert uow.invocations.get(result.invocation.id) == result.invocation
        assert uow.artifacts.get(result.artifact.id) == result.artifact
        assert {e.event_type for e in uow.history.list_events(task.id)} == {"AGENT_STARTED", "AGENT_COMPLETED"}


@pytest.mark.parametrize("failure_point", ["artifact", "completion_event"])
def test_completion_rollback_leaves_started_invocation(factory, monkeypatch, failure_point):
    scenario, _ = division_scenario()
    task = Task(title="Division", requirement=DIVISION_REQUIREMENT, state=S.RESEARCHING)
    with UnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.commit()
    original_add = ArtifactRepository.add
    original_event = HistoryRepository.append_event
    def fail_artifact(self, record):
        original_add(self, record)
        raise RuntimeError("Injected artifact failure")
    def fail_event(self, event):
        original_event(self, event)
        if event.event_type == "AGENT_COMPLETED":
            raise RuntimeError("Injected completion event failure")
    monkeypatch.setattr(ArtifactRepository, "add", fail_artifact if failure_point == "artifact" else original_add)
    monkeypatch.setattr(HistoryRepository, "append_event", fail_event if failure_point == "completion_event" else original_event)
    with pytest.raises(RuntimeError, match="Injected"):
        AgentExecutor(factory, FakeAgentRuntime(scenario)).execute(A.RESEARCHER,
            ResearchContext(task_id=task.id, attempt=1, requirement=task.requirement))
    with UnitOfWork(factory) as uow:
        invocation, = uow.invocations.list_by_task(task.id)
        assert invocation.status.value == "STARTED" and invocation.finished_at is None
        assert not uow.artifacts.list_by_task(task.id)
        assert len(uow.history.list_events(task.id)) == 1


def test_contexts_use_accepted_artifacts_and_have_no_state_or_database(factory):
    scenario, results = division_scenario()
    task = Task(title="Division", requirement=DIVISION_REQUIREMENT)
    with UnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.commit()
    runner = WorkflowRunner(factory, FakeAgentRuntime(scenario), FakeTestResultProvider(results))
    runner._step(task)
    runner._step(runner._task(task.id))
    context = runner.build_context(runner._task(task.id), A.PLANNER)
    assert type(context) is PlanContext and context.research == scenario.responses[A.RESEARCHER][0].output
    assert context.evidence_refs == (str(context.research_artifact_id),)
    assert not hasattr(context, "state") and not hasattr(context, "session")
    with pytest.raises(ValidationError):
        context.attempt = 9


def test_runner_bound_is_validated(factory):
    for bound in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            WorkflowRunner(factory, None, None, max_steps=bound)


def test_executor_rejects_terminal_context_before_invocation(factory):
    scenario, _ = division_scenario()
    task = Task(title="Division", requirement=DIVISION_REQUIREMENT, state=S.DONE)
    with UnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.commit()
    executor = AgentExecutor(factory, FakeAgentRuntime(scenario))
    with pytest.raises(ValueError, match="current task stage"):
        executor.execute(A.RESEARCHER, ResearchContext(task_id=task.id, attempt=1, requirement=task.requirement))
    with UnitOfWork(factory) as uow:
        assert not uow.invocations.list_by_task(task.id)


def test_defect_counter_and_transition_roll_back_together(factory, monkeypatch):
    from qa_sentinel.orchestration.workflow_engine import WorkflowEngine
    from qa_sentinel.orchestration.gates import InvestigationGate
    scenario, _ = division_scenario(repair=True)
    task = Task(title="Division", requirement=DIVISION_REQUIREMENT, state=S.INVESTIGATING)
    with UnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.commit()
    gate = InvestigationGate.evaluate(task.id, scenario.responses[A.INVESTIGATOR][0].output)
    original = HistoryRepository.append_event
    def fail(self, event):
        original(self, event)
        raise RuntimeError("Injected transition event failure")
    engine = WorkflowEngine(factory)
    with monkeypatch.context() as patch:
        patch.setattr(HistoryRepository, "append_event", fail)
        with pytest.raises(RuntimeError):
            engine.transition(task_id=task.id, to_state=S.IMPLEMENTING, gate_evaluation=gate,
                              reason_code="FIX", reason_details="Start repair", increment_defect_cycle=True)
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(task.id) == task
        assert not uow.history.list_transitions(task.id)
        assert not uow.history.list_gate_evaluations(task.id)
    engine.transition(task_id=task.id, to_state=S.IMPLEMENTING, gate_evaluation=gate,
                      reason_code="FIX", reason_details="Start repair", increment_defect_cycle=True)
    with UnitOfWork(factory) as uow:
        saved = uow.tasks.get(task.id)
        assert saved.defect_cycle == 1 and saved.state == S.IMPLEMENTING
        event, = uow.history.list_events(task.id)
        assert event.payload["defect_cycle"] == 1
    with pytest.raises(ValueError, match="Defect cycle increment"):
        engine.transition(task_id=task.id, to_state=S.PLANNING, reason_code="REPLAN", reason_details="Replan",
                          increment_defect_cycle=True)


def test_context_ignores_newer_plan_without_accepted_gate(factory):
    from datetime import datetime, timezone
    from qa_sentinel.domain.invocation import AgentInvocation
    from qa_sentinel.domain.artifact import Artifact
    scenario, results = division_scenario()
    task = Task(title="Division", requirement=DIVISION_REQUIREMENT)
    with UnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.commit()
    runner = WorkflowRunner(factory, FakeAgentRuntime(scenario), FakeTestResultProvider(results))
    final = runner.run(task.id)
    plan = scenario.responses[A.PLANNER][0].output
    now = datetime.now(timezone.utc)
    invocation = AgentInvocation(task_id=task.id, agent=A.PLANNER, model="fake", reasoning_effort="none",
        attempt=2, status="COMPLETED", started_at=now, finished_at=now)
    rejected = Artifact(task_id=task.id, invocation_id=invocation.id, artifact_type=ArtifactType.PLAN,
        schema_version="0.1", producer_agent=A.PLANNER, content=plan.model_dump(mode="json"))
    with UnitOfWork(factory) as uow:
        uow.invocations.add(invocation)
        uow.artifacts.add(rejected)
        uow.commit()
    context = runner.build_context(final, A.IMPLEMENTER)
    assert context.plan_artifact_id != rejected.id
