from dataclasses import replace
import pytest
from qa_sentinel.agents.base import (
    ImplementationContext, AnalysisContext, InvestigationContext, ReviewContext,
)
from qa_sentinel.agents.fake import FakeAgentRuntime, FakeScenario, FakeResponse
from qa_sentinel.agents.scenarios import division_scenario, DIVISION_REQUIREMENT
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.enums import (
    TaskState as S, AgentName as A, ArtifactType, DecisionType, InvestigationActionType,
    PlannerDecision, ReviewDecision,
)
from qa_sentinel.execution.fake import FakeTestResultProvider, FakeTestResult
from qa_sentinel.orchestration.runner import WorkflowRunner, RunnerStoppedError
from qa_sentinel.orchestration.reliability_policy import (
    FailureDisposition as D, ReliabilityConfig, RetryDomain, BlockerReason,
)
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.database import create_engine, create_session_factory


def setup(factory, *, repair=False, responses=None, results=None, repeat_last=False, **runner_options):
    scenario, defaults = division_scenario(repair=repair)
    if responses:
        scenario = FakeScenario(responses={**scenario.responses, **responses}, repeat_last=repeat_last)
    elif repeat_last:
        scenario = replace(scenario, repeat_last=True)
    provider = FakeTestResultProvider(results or defaults, repeat_last=repeat_last)
    task = Task(title="Add division support", requirement=DIVISION_REQUIREMENT)
    with UnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.commit()
    return task, WorkflowRunner(factory, FakeAgentRuntime(scenario), provider, **runner_options)


def path(uow, task_id):
    # Timestamps/UUID order are not used to infer history. Follow source/target links
    # for the unique happy/repair graph in these tests.
    transitions = uow.history.list_transitions(task_id)
    return {(t.from_state, t.to_state) for t in transitions}


def test_happy_path_and_complete_history_survive_reopen(migrated_factory):
    factory, engine, _ = migrated_factory
    task, runner = setup(factory)
    final = runner.run(task.id)
    assert final.state == S.DONE and final.completed_at is not None
    fresh = create_engine(str(engine.url))
    try:
        with UnitOfWork(create_session_factory(fresh)) as uow:
            assert uow.tasks.get(task.id) == final
            invocations = uow.invocations.list_by_task(task.id)
            assert {i.agent for i in invocations} == {A.RESEARCHER, A.PLANNER, A.IMPLEMENTER, A.REVIEWER}
            assert all(i.status.value == "COMPLETED" and i.finished_at >= i.started_at for i in invocations)
            artifacts = uow.artifacts.list_by_task(task.id)
            assert len(artifacts) == 4 and {a.invocation_id for a in artifacts} == {i.id for i in invocations}
            assert all(a.schema_version == "0.1" and a.producer_model == "fake" for a in artifacts)
            run, = uow.history.list_test_runs(task.id)
            assert run.outcome.value == "PASS" and run.execution_status.value == "COMPLETED"
            assert run.implementation_artifact_id == next(a.id for a in artifacts if a.artifact_type == ArtifactType.IMPLEMENTATION)
            assert len(uow.history.list_transitions(task.id)) == 6
            assert len(uow.history.list_decisions(task.id)) == 6
            assert len(uow.history.list_gate_evaluations(task.id)) == 5
            assert len(uow.history.list_events(task.id)) == 15
            assert path(uow, task.id) == set(zip(
                [S.CREATED, S.RESEARCHING, S.PLANNING, S.IMPLEMENTING, S.TESTING, S.REVIEWING],
                [S.RESEARCHING, S.PLANNING, S.IMPLEMENTING, S.TESTING, S.REVIEWING, S.DONE]))
        # Running an already completed task performs no new work.
        assert runner.run(task.id) == final
    finally:
        fresh.dispose()


def test_failure_fix_retest_preserves_all_evidence_and_bounded_contexts(migrated_factory):
    factory, _, _ = migrated_factory
    task, runner = setup(factory, repair=True)
    captured = []
    original = runner.executor.runtime.run
    def capture(agent, context):
        captured.append((agent, context))
        return original(agent, context)
    runner.executor.runtime.run = capture
    final = runner.run(task.id)
    assert final.state == S.DONE and final.defect_cycle == 1 and final.implementation_attempt == 2
    assert [agent for agent, _ in captured] == [A.RESEARCHER, A.PLANNER, A.IMPLEMENTER,
                                              A.TEST_ANALYZER, A.INVESTIGATOR, A.IMPLEMENTER, A.REVIEWER]
    contexts = {type(context): context for _, context in captured}
    assert {ImplementationContext, AnalysisContext, InvestigationContext, ReviewContext} <= set(contexts)
    assert contexts[ImplementationContext].investigation is not None
    assert contexts[ImplementationContext].previous_implementation_ref is not None
    assert contexts[AnalysisContext].test_run.outcome.value == "FAIL"
    assert contexts[ReviewContext].test_run.outcome.value == "PASS"
    assert all(len(context.evidence_refs) <= 3 and not hasattr(context, "state") for _, context in captured)
    with UnitOfWork(factory) as uow:
        invocations = uow.invocations.list_by_task(task.id)
        assert len(invocations) == 7 and sum(i.agent == A.IMPLEMENTER for i in invocations) == 2
        assert sorted(i.attempt for i in invocations if i.agent == A.IMPLEMENTER) == [1, 2]
        artifacts = uow.artifacts.list_by_task(task.id)
        implementations = [a for a in artifacts if a.artifact_type == ArtifactType.IMPLEMENTATION]
        assert len(implementations) == 2 and implementations[0].id != implementations[1].id
        assert {ArtifactType.TEST_ANALYSIS, ArtifactType.INVESTIGATION} <= {a.artifact_type for a in artifacts}
        assert len(uow.history.list_test_runs(task.id)) == 2
        assert len(uow.history.list_transitions(task.id)) == 10
        assert {(S.TESTING, S.ANALYZING), (S.ANALYZING, S.INVESTIGATING), (S.INVESTIGATING, S.IMPLEMENTING)} <= path(uow, task.id)
        fingerprint, = uow.failure_fingerprints.list_by_task(task.id)
        assert fingerprint.occurrence_count == 1
        assert not uow.history.list_errors(task.id)  # Product FAIL is not an infrastructure error.


def test_investigator_human_action_blocks_and_stops(migrated_factory):
    factory, _, _ = migrated_factory
    scenario, _ = division_scenario(repair=True)
    investigation = scenario.responses[A.INVESTIGATOR][0].output
    human = investigation.model_copy(update={"recommended_action": investigation.recommended_action.model_copy(
        update={"type": InvestigationActionType.HUMAN_ACTION, "description": "Need an external decision"})})
    task, runner = setup(factory, repair=True, responses={A.INVESTIGATOR: (FakeResponse(output=human),)})
    final = runner.run(task.id)
    assert final.state == S.BLOCKED and final.resume_state == S.INVESTIGATING
    with UnitOfWork(factory) as uow:
        invocations = uow.invocations.list_by_task(task.id)
        assert len(invocations) == 5 and all(i.agent != A.REVIEWER for i in invocations)
        assert any(d.decision_type == DecisionType.BLOCK for d in uow.history.list_decisions(task.id))
        assert any(e.event_type == "TASK_BLOCKED" for e in uow.history.list_events(task.id))
    assert runner.run(task.id) == final


def test_transient_agent_retry_consumed_once(migrated_factory):
    factory, _, _ = migrated_factory
    scenario, _ = division_scenario()
    task, runner = setup(factory, responses={A.RESEARCHER: (
        FakeResponse(failure=D.TRANSIENT), scenario.responses[A.RESEARCHER][0])})
    assert runner.run(task.id).state == S.DONE
    with UnitOfWork(factory) as uow:
        researchers = sorted([i for i in uow.invocations.list_by_task(task.id) if i.agent == A.RESEARCHER], key=lambda i: i.attempt)
        assert [i.status.value for i in researchers] == ["FAILED", "COMPLETED"]
        error, = uow.history.list_errors(task.id)
        assert error.error_type.value == "AGENT_ERROR" and error.id == researchers[0].error_id
        retry, = [e for e in uow.history.list_events(task.id) if e.event_type == "RETRY_SCHEDULED"]
        assert retry.payload["domain"] == "RESEARCH" and retry.payload["current_attempt"] == 0
        assert retry.correlation.invocation_id == researchers[0].id
        assert uow.history.get_decision(retry.correlation.decision_id).decision_type == DecisionType.RETRY


def test_schema_retry_with_changed_evidence_and_no_raw_payload_persistence(migrated_factory):
    factory, _, _ = migrated_factory
    scenario, _ = division_scenario()
    task, runner = setup(factory, responses={A.PLANNER: (
        FakeResponse(raw_output={"bad": "secret-must-not-persist"}, changed_input=True), scenario.responses[A.PLANNER][0])})
    assert runner.run(task.id).state == S.DONE
    with UnitOfWork(factory) as uow:
        error, = uow.history.list_errors(task.id)
        assert error.error_type.value == "SCHEMA_ERROR"
        assert uow.invocations.get(error.source.invocation_id).status.value == "FAILED"
        retry, = [e for e in uow.history.list_events(task.id) if e.event_type == "RETRY_SCHEDULED"]
        assert retry.payload["domain"] == "SCHEMA_VALIDATION"
        for records in (uow.history.list_errors(task.id), uow.history.list_events(task.id),
                        uow.history.list_decisions(task.id), uow.artifacts.list_by_task(task.id)):
            assert "secret-must-not-persist" not in str([r.model_dump() for r in records])


def test_schema_exhaustion_blocks_without_fourth_invocation(migrated_factory):
    factory, _, _ = migrated_factory
    response = FakeResponse(raw_output={}, changed_input=True)
    task, runner = setup(factory, responses={A.PLANNER: (response, response, response)})
    final = runner.run(task.id)
    assert final.state == S.BLOCKED and final.resume_state == S.PLANNING
    with UnitOfWork(factory) as uow:
        assert sum(i.agent == A.PLANNER for i in uow.invocations.list_by_task(task.id)) == 3
        events = uow.history.list_events(task.id)
        assert sum(e.event_type == "RETRY_SCHEDULED" for e in events) == 2
        assert sum(e.event_type == "RETRY_EXHAUSTED" for e in events) == 1
        assert len(uow.history.list_errors(task.id)) == 3


def test_correctable_failure_without_changed_input_blocks(migrated_factory):
    factory, _, _ = migrated_factory
    task, runner = setup(factory, responses={A.RESEARCHER: (FakeResponse(failure=D.CORRECTABLE),)})
    assert runner.run(task.id).state == S.BLOCKED
    with UnitOfWork(factory) as uow:
        assert len(uow.invocations.list_by_task(task.id)) == 1
        assert not any(e.event_type == "RETRY_SCHEDULED" for e in uow.history.list_events(task.id))


def test_terminal_implementation_failure_uses_canonical_failed_edge(migrated_factory):
    factory, _, _ = migrated_factory
    task, runner = setup(factory, responses={A.IMPLEMENTER: (FakeResponse(failure=D.TERMINAL),)})
    assert runner.run(task.id).state == S.FAILED
    with UnitOfWork(factory) as uow:
        assert not uow.history.list_test_runs(task.id)
        assert any(d.decision_type == DecisionType.FAIL for d in uow.history.list_decisions(task.id))


def test_step_bound_stops_configured_research_planning_loop(migrated_factory):
    factory, _, _ = migrated_factory
    scenario, _ = division_scenario()
    plan = scenario.responses[A.PLANNER][0].output.model_copy(update={"decision": PlannerDecision.NEEDS_RESEARCH})
    task, runner = setup(factory, responses={A.PLANNER: (FakeResponse(output=plan),)}, repeat_last=True, max_steps=5)
    final = runner.run(task.id)
    assert final.state == S.BLOCKED and final.resume_state == S.RESEARCHING
    with UnitOfWork(factory) as uow:
        assert len(uow.invocations.list_by_task(task.id)) == 4
        error, = uow.history.list_errors(task.id)
        assert error.error_type.value == "WORKFLOW_ERROR" and error.code == "RUNTIME_STEP_LIMIT"


def test_reviewer_request_changes_requires_retest_before_done(migrated_factory):
    factory, _, _ = migrated_factory
    scenario, results = division_scenario()
    review = scenario.responses[A.REVIEWER][0].output
    task, runner = setup(factory, responses={A.REVIEWER: (
        FakeResponse(output=review.model_copy(update={"decision": ReviewDecision.REQUEST_CHANGES})), FakeResponse(output=review)),
        A.IMPLEMENTER: scenario.responses[A.IMPLEMENTER] * 2}, results=results * 2)
    assert runner.run(task.id).state == S.DONE
    with UnitOfWork(factory) as uow:
        assert len(uow.history.list_test_runs(task.id)) == 2
        assert (S.REVIEWING, S.IMPLEMENTING) in path(uow, task.id)
        assert uow.tasks.get(task.id).review_cycle == 2


def test_invalid_approval_cannot_bypass_review_gate(migrated_factory):
    factory, _, _ = migrated_factory
    scenario, _ = division_scenario()
    review = scenario.responses[A.REVIEWER][0].output.model_copy(update={"requirement_coverage": ()})
    task, runner = setup(factory, responses={A.REVIEWER: (FakeResponse(output=review),)})
    assert runner.run(task.id).state == S.BLOCKED
    with UnitOfWork(factory) as uow:
        assert (S.REVIEWING, S.DONE) not in path(uow, task.id)
        assert any(g.gate_name == "REVIEW_GATE" and g.result.value == "FAIL" for g in uow.history.list_gate_evaluations(task.id))


def test_repeated_test_failure_respects_circuit_breaker(migrated_factory):
    factory, _, _ = migrated_factory
    scenario, results = division_scenario(repair=True)
    task, runner = setup(factory, repair=True, repeat_last=True, results=(results[0],))
    final = runner.run(task.id)
    assert final.state == S.BLOCKED and final.resume_state == S.INVESTIGATING
    with UnitOfWork(factory) as uow:
        fingerprint, = uow.failure_fingerprints.list_by_task(task.id)
        assert fingerprint.occurrence_count == 3
        assert len(uow.history.list_test_runs(task.id)) == 3
        invocations = uow.invocations.list_by_task(task.id)
        assert sum(i.agent == A.IMPLEMENTER for i in invocations) == 3
        assert sum(i.agent == A.INVESTIGATOR for i in invocations) == 2
        assert any(e.event_type == "CIRCUIT_BREAKER_TRIPPED" for e in uow.history.list_events(task.id))


def test_defect_cycle_budget_blocks_further_repairs(migrated_factory):
    factory, _, _ = migrated_factory
    scenario, results = division_scenario(repair=True)
    # Without repeated fingerprint metadata, defect budget independently stops the loop.
    failed = results[0].model_copy(update={"failure_identity": None})
    task, runner = setup(factory, repair=True, repeat_last=True, results=(failed,),
                         reliability_config=ReliabilityConfig(max_defect_cycles=1))
    final = runner.run(task.id)
    assert final.state == S.BLOCKED and final.defect_cycle == 1
    with UnitOfWork(factory) as uow:
        assert len(uow.history.list_test_runs(task.id)) == 2
        assert any(d.reason_code == "DEFECT_CYCLE_EXHAUSTED" for d in uow.history.list_decisions(task.id))


def test_explicit_schema_configuration_is_respected(migrated_factory):
    factory, _, _ = migrated_factory
    budgets = dict(ReliabilityConfig().retry_budgets)
    budgets[RetryDomain.SCHEMA_VALIDATION] = 0
    task, runner = setup(factory, responses={A.PLANNER: (FakeResponse(raw_output={}, changed_input=True),)},
                         reliability_config=ReliabilityConfig(retry_budgets=budgets))
    assert runner.run(task.id).state == S.BLOCKED
    with UnitOfWork(factory) as uow:
        assert sum(i.agent == A.PLANNER for i in uow.invocations.list_by_task(task.id)) == 1


def test_safety_stop_preserves_graph_when_no_block_edge_exists(migrated_factory):
    factory, _, _ = migrated_factory
    task, runner = setup(factory, max_steps=3)  # CREATED -> research -> plan -> IMPLEMENTING.
    with pytest.raises(RunnerStoppedError, match="no BLOCKED edge"):
        runner.run(task.id)
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(task.id).state == S.IMPLEMENTING
        assert any(e.code == "RUNTIME_STEP_LIMIT" for e in uow.history.list_errors(task.id))
        assert any(d.decision_type == DecisionType.BLOCK for d in uow.history.list_decisions(task.id))


def test_missing_task_and_blocked_task_do_not_invoke_agents(migrated_factory):
    from uuid import uuid4
    factory, _, _ = migrated_factory
    task, runner = setup(factory)
    with pytest.raises(KeyError):
        runner.run(uuid4())
    runner.workflow.transition(task_id=task.id, to_state=S.BLOCKED, resume_state=S.RESEARCHING,
                               reason_code="EXTERNAL", reason_details="External blocker")
    assert runner.run(task.id).state == S.BLOCKED
    with UnitOfWork(factory) as uow:
        assert not uow.invocations.list_by_task(task.id)


def test_committed_agent_output_is_reused_after_transition_failure(migrated_factory, monkeypatch):
    factory, _, _ = migrated_factory
    task, runner = setup(factory)
    original = runner.workflow.transition
    def fail_before_transition(**kwargs):
        if kwargs["to_state"] == S.PLANNING:
            raise RuntimeError("Injected failure after agent completion")
        return original(**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(runner.workflow, "transition", fail_before_transition)
        with pytest.raises(RuntimeError, match="Injected"):
            runner.run(task.id)
    with UnitOfWork(factory) as uow:
        researcher, = uow.invocations.list_by_task(task.id)
        assert researcher.status.value == "COMPLETED"
        artifact, = uow.artifacts.list_by_task(task.id)
        assert uow.tasks.get(task.id).state == S.RESEARCHING
    assert runner.run(task.id).state == S.DONE
    with UnitOfWork(factory) as uow:
        assert sum(i.agent == A.RESEARCHER for i in uow.invocations.list_by_task(task.id)) == 1
        assert uow.artifacts.get(artifact.id) == artifact


def test_started_invocation_requires_reconciliation_without_duplicate_call(migrated_factory, monkeypatch):
    from qa_sentinel.persistence.repositories import ArtifactRepository
    factory, _, _ = migrated_factory
    task, runner = setup(factory)
    def fail(self, artifact):
        raise RuntimeError("Injected completion failure")
    with monkeypatch.context() as patch:
        patch.setattr(ArtifactRepository, "add", fail)
        with pytest.raises(RuntimeError):
            runner.run(task.id)
    with pytest.raises(RunnerStoppedError, match="unfinished invocation"):
        runner.run(task.id)
    with UnitOfWork(factory) as uow:
        invocation, = uow.invocations.list_by_task(task.id)
        assert invocation.status.value == "STARTED" and not uow.artifacts.list_by_task(task.id)
        assert any(e.error_type.value == "WORKFLOW_ERROR" for e in uow.history.list_errors(task.id))


def test_scenario_blocker_marks_invocation_blocked(migrated_factory):
    factory, _, _ = migrated_factory
    task, runner = setup(factory, responses={A.RESEARCHER: (
        FakeResponse(failure=D.STRUCTURAL, blocker_reason=BlockerReason.MISSING_CREDENTIAL),)})
    final = runner.run(task.id)
    assert final.state == S.BLOCKED and final.resume_state == S.RESEARCHING
    with UnitOfWork(factory) as uow:
        invocation, = uow.invocations.list_by_task(task.id)
        assert invocation.status.value == "BLOCKED" and invocation.finished_at is not None
        error = uow.history.get_error(invocation.error_id)
        assert error.blocking and error.error_type.value == "AGENT_ERROR"
        assert not any(e.event_type == "RETRY_SCHEDULED" for e in uow.history.list_events(task.id))


def test_investigator_more_research_routes_by_enum(migrated_factory):
    factory, _, _ = migrated_factory
    scenario, _ = division_scenario(repair=True)
    investigation = scenario.responses[A.INVESTIGATOR][0].output
    research = investigation.model_copy(update={"recommended_action": investigation.recommended_action.model_copy(
        update={"type": InvestigationActionType.MORE_RESEARCH})})
    task, runner = setup(factory, repair=True, responses={A.INVESTIGATOR: (FakeResponse(output=research),)}, repeat_last=True)
    assert runner.run(task.id).state == S.DONE
    with UnitOfWork(factory) as uow:
        assert (S.INVESTIGATING, S.RESEARCHING) in path(uow, task.id)
        assert sum(i.agent == A.RESEARCHER for i in uow.invocations.list_by_task(task.id)) == 2
        assert sum(i.agent == A.PLANNER for i in uow.invocations.list_by_task(task.id)) == 2


def test_runtime_completing_exactly_at_step_bound_is_success(migrated_factory):
    factory, _, _ = migrated_factory
    task, runner = setup(factory, max_steps=6)
    assert runner.run(task.id).state == S.DONE
    with UnitOfWork(factory) as uow:
        assert not uow.history.list_errors(task.id)
