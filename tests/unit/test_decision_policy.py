from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from pydantic import ValidationError
from qa_sentinel.decisions.contracts import DecisionRequest, DecisionProposal, DecisionFailure, Reason
from qa_sentinel.decisions.policy import request_hash, arbitrate
from qa_sentinel.orchestration.decision_router import DecisionRouter


def request(**changes):
    now = datetime.now(timezone.utc)
    return DecisionRequest(**{**dict(baseline_route="PLANNER", allowed_routes=("PLANNER", "RESEARCHER"),
        created_at=now, expires_at=now+timedelta(seconds=25)), **changes})


def proposal(req, **changes):
    return DecisionProposal(**{**dict(correlation_id=req.correlation_id, request_sha256=request_hash(req),
        route="RESEARCHER", confidence=0.95, escalate=False, reason_codes=("CLASSIFICATION",),
        provider="offline", configured_model="fixture", reported_model="fixture-1", provider_version="fixture-v1",
        latency_ms=1.0), **changes})


class Fixture:
    def __init__(self, fn):
        self.calls = 0
        self.fn = fn
    def propose(self, req):
        self.calls += 1
        return self.fn(req)


def test_off_default_preserves_baseline_and_calls_nothing():
    fixture = Fixture(lambda r: pytest.fail("disabled provider called"))
    req = request()
    result = DecisionRouter(fixture).decide(req)
    assert result.route == req.baseline_route and result.reason == Reason.DISABLED
    assert fixture.calls == 0


def test_enabled_proposal_only_allowlisted_advice():
    fixture = Fixture(proposal)
    result = DecisionRouter(fixture, enabled=True).decide(request())
    assert result.accepted and result.route == "RESEARCHER"
    assert fixture.calls == 1


@pytest.mark.parametrize("change", [dict(risk="SECURITY"), dict(risk="ARCHITECTURE"), dict(risk="STATE_MACHINE"),
    dict(evidence_complete=False), dict(evidence_conflict=True), dict(untrusted_input=True),
    dict(permission_required=True), dict(policy_denied=True), dict(complexity="COMPLEX")])
def test_safety_lock_precedes_provider(change):
    fixture = Fixture(lambda r: pytest.fail("locked request reached provider"))
    result = DecisionRouter(fixture, enabled=True).decide(request(**change))
    assert result.reason == Reason.POLICY_LOCK and result.route == "PLANNER"
    assert fixture.calls == 0


@pytest.mark.parametrize("change,reason", [(dict(route="REVIEWER"),Reason.DISALLOWED_ROUTE),
    (dict(confidence=0.1),Reason.LOW_CONFIDENCE),(dict(escalate=True),Reason.DISALLOWED_ESCALATION),
    (dict(correlation_id=uuid4()),Reason.CORRELATION_MISMATCH),
    (dict(request_sha256="0"*64),Reason.CORRELATION_MISMATCH)])
def test_bad_advice_cannot_authorize(change, reason):
    req = request()
    result = arbitrate(req, proposal(req, **change))
    assert result.reason == reason and not result.accepted and result.route == req.baseline_route


def test_workflow_role_cannot_change_even_if_allowlisted():
    req = request(workflow_state="PLANNING")
    assert arbitrate(req, proposal(req)).reason == Reason.DISALLOWED_ROUTE


def test_advice_cannot_suppress_existing_escalation():
    req = request(escalation_allowed=True, baseline_escalation=True)
    result = arbitrate(req, proposal(req))
    assert not result.accepted and result.escalate
    assert arbitrate(req, proposal(req, escalate=True)).accepted


def test_expired_and_future_request_call_nothing():
    now = datetime.now(timezone.utc)
    for created in [now-timedelta(seconds=40),now+timedelta(seconds=5)]:
        req = request(created_at=created, expires_at=created+timedelta(seconds=25))
        fixture = Fixture(lambda r: pytest.fail("stale request reached provider"))
        assert DecisionRouter(fixture,enabled=True).decide(req).reason == Reason.STALE


def test_late_proposal_falls_back():
    req = request()
    assert arbitrate(req,proposal(req),now=req.expires_at).reason == Reason.STALE


@pytest.mark.parametrize("confidence", [-0.1,1.1,float("nan"),float("inf"),True,"0.9"])
def test_invalid_confidence(confidence):
    with pytest.raises(ValidationError):
        proposal(request(),confidence=confidence)


@pytest.mark.parametrize("change", [dict(route="ROOT"),dict(reason_codes=("run shell",)),
    dict(reported_model="x"*101),dict(execute="pytest"),dict(input_tokens=-1)])
def test_unbounded_unknown_or_command_output(change):
    with pytest.raises(ValidationError):
        proposal(request(),**change)


def test_revalidation_cannot_be_bypassed():
    fixture = Fixture(lambda req: proposal(req).model_copy(update={"confidence":float("nan")}))
    assert DecisionRouter(fixture,enabled=True).decide(request()).reason == Reason.INVALID_OUTPUT


@pytest.mark.parametrize("reason", [Reason.TIMEOUT,Reason.UNAVAILABLE,Reason.AUTHENTICATION,Reason.BUDGET_EXHAUSTED])
def test_failure_fallback_no_retries(reason):
    def fail(req):
        raise DecisionFailure(reason)
    fixture=Fixture(fail)
    result=DecisionRouter(fixture,enabled=True).decide(request())
    assert result.reason == reason and result.route == "PLANNER"
    assert fixture.calls == 1


def test_sanitized_bounded_audit_correlation_and_unknown_usage():
    secret = "secret-credential-do-not-log"
    def fail(req):
        raise RuntimeError(secret)
    router=DecisionRouter(Fixture(fail),enabled=True,audit_limit=2)
    for _ in range(3):
        req=request()
        result=router.decide(req)
        assert result.request == req
        assert result.correlation_id == req.correlation_id
        assert result.request_sha256 == request_hash(req)
    assert len(router.audit)==2
    assert secret not in str(router.audit)
    good=DecisionRouter(Fixture(proposal),enabled=True).decide(request())
    assert good.proposal.input_tokens is None and good.proposal.provider_cost_usd is None


def test_contract_has_no_raw_content_or_authority_handles():
    req=request()
    for field in ["instructions","raw_dom","credentials","task","browser","shell","source"]:
        with pytest.raises(ValidationError):
            DecisionRequest(**{**req.model_dump(),field:"untrusted secret"})
