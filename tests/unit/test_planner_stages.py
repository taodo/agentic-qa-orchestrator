"""Typed stage declarations protect planning without interpreting arbitrary prose."""
import json
from uuid import uuid4
import pytest
from pydantic import ValidationError
from qa_sentinel.agents.base import ImplementationContext
from qa_sentinel.agents.prompts import build_request
from qa_sentinel.agents.real import RealAgentRuntime
from qa_sentinel.domain.enums import AgentName as A, GateResult as R
from qa_sentinel.models.base import ModelSettings, ModelError
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from qa_sentinel.orchestration.gates import PlanGate, ImplementationGate
from qa_sentinel.orchestration.implementation_execution import canonical_output
from qa_sentinel.schemas.mutation import ImplementationProposal
from qa_sentinel.schemas.plan import PlannerOutput, ImplementationStep, ImplementationStepKind as K
from qa_sentinel.schemas.repository import PlannerTurn
from test_contracts import plan
from test_models import context


def stage_plan():
    data = plan()
    data["implementation_steps"] = [
        dict(id="repair", kind="CODE_CHANGE", description="Repair the inventory guard", files=["app.py"], depends_on=[]),
        dict(id="preserve", kind="STATIC_REVIEW", description="Compare lock and transaction source for preservation",
             files=["app.py"], depends_on=["repair"]),
    ]
    data["test_strategy"][0]["description"] = "Run existing exhaustion and concurrent-final-room tests during TESTING"
    return PlannerOutput.model_validate(data)


def proposal():
    return ImplementationProposal(implementation_status="COMPLETED", implementation_summary="Proposed repair",
        plan_steps=[dict(step_id=name, status="COMPLETED") for name in ("repair", "preserve")],
        mutations=[], tests_added_or_modified=[], assumptions=[], known_issues=[], deviations=[])


def test_valid_repair_static_attestation_and_downstream_verification():
    value = stage_plan()
    assert PlanGate.evaluate(uuid4(), value).result == R.PASS
    output = canonical_output(proposal())
    assert output.commands_executed == ()
    assert ImplementationGate.evaluate(uuid4(), output, value).result == R.PASS
    assert [s.kind for s in value.implementation_steps] == [K.CODE_CHANGE, K.STATIC_REVIEW]


@pytest.mark.parametrize("description", ["Run the existing booking, exhausted-inventory, and concurrent-final-room tests",
    "Harmless source edit", "pytest backend/tests", "Verify behavior"])
def test_declared_test_execution_rejected_even_if_description_is_disguised(description):
    data = stage_plan().model_dump(mode="json")
    data["implementation_steps"].append(dict(id="verify", kind="TEST_EXECUTION", description=description,
        files=[], depends_on=["repair"]))
    value = PlannerOutput.model_validate(data)
    before = value.model_dump_json()
    gate = PlanGate.evaluate(uuid4(), value)
    assert gate.result == R.FAIL
    failed, = [check for check in gate.checks if check.result == R.FAIL]
    assert failed.check == "IMPLEMENTING_STEP_KINDS" and "TESTING" in failed.reason
    assert value.model_dump_json() == before  # No silent removal/moving/rewriting of required steps.
    assert len(value.implementation_steps) == 3


def test_writing_authorized_tests_is_not_classified_as_execution():
    data = stage_plan().model_dump(mode="json")
    data["implementation_steps"][0].update(description="Write pytest tests without running them", files=["test_app.py"])
    assert PlanGate.evaluate(uuid4(), PlannerOutput.model_validate(data)).result == R.PASS


@pytest.mark.parametrize("kind", ["SHELL", "PYTEST", "PACKAGE_MANAGER", "", None])
def test_step_kind_is_closed_and_frozen(kind):
    data = dict(id="step", description="Work", files=[], depends_on=[], kind=kind)
    with pytest.raises(ValidationError): ImplementationStep.model_validate(data)
    value = stage_plan().implementation_steps[0]
    with pytest.raises(ValidationError): value.kind = K.TEST_EXECUTION


def test_legacy_contract_loads_without_rewriting_persisted_plan():
    data = plan()
    assert "kind" not in data["implementation_steps"][0]
    loaded = PlannerOutput.model_validate(data)
    assert loaded.implementation_steps[0].kind == K.CODE_CHANGE
    assert "kind" not in data["implementation_steps"][0]
    assert PlanGate.evaluate(uuid4(), loaded).result == R.PASS


def test_declared_kind_does_not_claim_semantic_certainty_about_prose():
    data = plan()
    data["implementation_steps"][0].update(kind="CODE_CHANGE", description="Run existing pytest tests")
    # This is a wrongly labelled model instruction, not decidable from these typed fields.
    # Prompt guidance and Implementer BLOCKED/replan behavior remain necessary; no NLP classifier.
    assert PlanGate.evaluate(uuid4(), PlannerOutput.model_validate(data)).result == R.PASS


@pytest.mark.parametrize("violation,check", [("missing", "ALL_REQUIRED_STEPS"), ("extra", "NO_EXTRA_STEPS"),
    ("duplicate", "UNIQUE_STEP_RESULTS"), ("blocked_static", "REQUIRED_WORK_COMPLETE"),
    ("skipped_static", "REQUIRED_WORK_COMPLETE"), ("replan", "NO_REPLAN_DEVIATIONS")])
def test_actual_work_including_static_review_still_requires_complete_exact_results(violation, check):
    data = proposal().model_dump(mode="json")
    if violation == "missing": data["plan_steps"].pop()
    elif violation == "extra": data["plan_steps"].append(dict(step_id="unknown", status="COMPLETED"))
    elif violation == "duplicate": data["plan_steps"].append(data["plan_steps"][0])
    elif violation == "blocked_static": data["plan_steps"][1]["status"] = "BLOCKED"
    elif violation == "skipped_static": data["plan_steps"][1]["status"] = "SKIPPED"
    else: data["deviations"] = [dict(description="Requires another plan", requires_replan=True)]
    output = canonical_output(ImplementationProposal.model_validate(data))
    gate = ImplementationGate.evaluate(uuid4(), output, stage_plan())
    assert gate.result == R.FAIL
    assert any(c.check == check and c.result == R.FAIL for c in gate.checks)


@pytest.mark.parametrize("repository_tools", [False, True])
def test_planner_strict_schema_and_prompt_require_typed_stage_separation(mock_openai, workflow_outputs, repository_tools):
    value = stage_plan()
    expected = PlannerTurn(kind="FINAL_OUTPUT", tool_request=None, final_output=value) if repository_tools else value
    mock = mock_openai([expected])
    runtime = RealAgentRuntime(OpenAIModelAdapter(client=mock.client), repository_tools=repository_tools)
    response = runtime.run(A.PLANNER, context(A.PLANNER, workflow_outputs))
    actual = response.parsed_output.final_output if repository_tools else response.parsed_output
    assert actual == value
    call, = mock.calls
    schema = call["text"]["format"]["schema"]
    step = schema["$defs"]["ImplementationStep"]
    assert "kind" in step["required"] and "default" not in step["properties"]["kind"]
    assert schema["$defs"]["ImplementationStepKind"]["enum"] == ["CODE_CHANGE", "STATIC_REVIEW", "TEST_EXECUTION"]
    instructions = call["instructions"]
    for text in ("implementation_steps", "test_strategy", "TESTING", "STATIC_REVIEW",
        "Do not duplicate test execution", "cannot execute pytest", "PlanGate rejects"):
        assert text in instructions
    assert call["tools"] == [] and call["tool_choice"] == "none"
    assert call["store"] is False and len(mock.calls) == 1


def test_implementer_receives_kinds_but_has_no_execution_capability():
    value = stage_plan()
    ctx = ImplementationContext(task_id=uuid4(), attempt=1, plan=value, plan_artifact_id=uuid4())
    request = build_request(A.IMPLEMENTER, ctx, ModelSettings(model="mock-only"))
    steps = json.loads(request.user_input)["accepted_plan"]["implementation_steps"]
    assert [step["kind"] for step in steps] == ["CODE_CHANGE", "STATIC_REVIEW"]
    assert "Do not claim mutation happened, tests ran, or commands ran" in request.system_instructions
    assert "requires_replan" in request.system_instructions and "Never mark downstream" in request.system_instructions
    with pytest.raises(ModelError, match="MODEL_UNSUPPORTED_ROLE"):
        build_request(A.IMPLEMENTER, ctx, ModelSettings(model="mock-only"), repository_tools=True)
