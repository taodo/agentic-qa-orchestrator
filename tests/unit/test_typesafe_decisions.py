from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from datetime import date
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from qa_sentinel.decisions.contracts import DecisionRequest, DecisionFailure, Reason
from qa_sentinel.decisions.typesafe import TypeSafeSettings, TypeSafeDecisionProvider
from qa_sentinel.orchestration.decision_router import DecisionRouter

KEY = "fixture-secret-not-a-real-key"
MODELS = {"models": [{"name":"fixture-alias","description":"Fixture alias","release_date":"2026-09-15"},
    {"name":"fixture-version","description":"Fixture version","release_date":"2026-09-15"}]}
RESPONSE = {"model":"fixture-version","answers":{"route":{"type":"choice","choice":"PLANNER",
    "confidence":0.9,"probabilities":{"PLANNER":0.9,"RESEARCHER":0.1}}},
    "usage":{"input_tokens":120,"output_tokens":12}}


def fixture_response(status, *, json=None, content=None, text=None, headers=None):
    # Model an unread network stream, rather than HTTPX's preconsumed convenience response.
    import json as json_module
    data = json_module.dumps(json).encode() if json is not None else content if content is not None else (text or "").encode()
    result_headers = {"Content-Type":"application/json"} if json is not None else {}
    result_headers.update(headers or {})
    return httpx.Response(status, stream=httpx.ByteStream(data), headers=result_headers)


def request(**changes):
    now=datetime.now(timezone.utc)
    return DecisionRequest(**{**dict(baseline_route="PLANNER",allowed_routes=("PLANNER","RESEARCHER"),
        created_at=now,expires_at=now+timedelta(seconds=25)),**changes})


def harness(monkeypatch, post=None, models=None, settings=None):
    monkeypatch.setenv("TYPESAFE_API_KEY",KEY)
    calls=[]
    def handler(req):
        calls.append(req)
        assert req.url.host == "api.typesafe.ai" and req.url.scheme == "https"
        assert req.headers["Authorization"] == "Bearer "+KEY
        if req.method=="GET":
            return fixture_response(200,json=MODELS if models is None else models)
        return fixture_response(200,json=RESPONSE) if post is None else post(req)
    provider=TypeSafeDecisionProvider(settings or TypeSafeSettings(enabled=True,model="fixture-alias"),
        transport=httpx.MockTransport(handler))
    return provider,calls


def test_offline_poc_schema_identity_usage_and_exact_request(monkeypatch):
    provider,calls=harness(monkeypatch)
    result=DecisionRouter(provider,enabled=True).decide(request())
    assert result.accepted
    assert result.proposal.configured_model=="fixture-alias"
    assert result.proposal.reported_model=="fixture-version"
    assert result.proposal.reported_model_release_date == date(2026,9,15)
    assert result.proposal.input_tokens==120 and result.proposal.output_tokens==12
    assert result.proposal.provider_cost_usd is None and result.proposal.estimated_cost_usd is None
    assert len(calls)==2
    payload=json.loads(calls[1].content)
    assert set(payload)=={"state","model","questions"}
    assert payload["questions"]["route"]["type"]=="choice"
    assert set(payload["questions"]["route"]["criteria"])=={"PLANNER","RESEARCHER"}
    assert KEY not in result.model_dump_json()


def test_environment_flag_off_even_when_key_present(monkeypatch):
    monkeypatch.delenv("QA_SENTINEL_TYPESAFE_ENABLED",raising=False)
    monkeypatch.setenv("TYPESAFE_API_KEY",KEY)
    monkeypatch.setenv("QA_SENTINEL_TYPESAFE_MODEL","fixture-alias")
    settings=TypeSafeSettings.from_environment()
    assert settings.enabled is False and settings.model is None
    provider=TypeSafeDecisionProvider(settings,transport=httpx.MockTransport(lambda r:pytest.fail("external call")))
    assert DecisionRouter(provider,enabled=True).decide(request()).reason==Reason.DISABLED


def test_explicit_environment_opt_in(monkeypatch):
    monkeypatch.setenv("QA_SENTINEL_TYPESAFE_ENABLED","true")
    monkeypatch.setenv("QA_SENTINEL_TYPESAFE_MODEL","fixture-alias")
    assert TypeSafeSettings.from_environment().enabled
    monkeypatch.setenv("QA_SENTINEL_TYPESAFE_ENABLED","yes")
    with pytest.raises(ValueError): TypeSafeSettings.from_environment()


@pytest.mark.parametrize("key,model,reason", [(None,"fixture-alias",Reason.UNAVAILABLE),(KEY,None,Reason.MODEL_UNAVAILABLE)])
def test_missing_key_or_model_calls_nothing(monkeypatch,key,model,reason):
    if key is None: monkeypatch.delenv("TYPESAFE_API_KEY",raising=False)
    else: monkeypatch.setenv("TYPESAFE_API_KEY",key)
    provider=TypeSafeDecisionProvider(TypeSafeSettings(enabled=True,model=model),
        transport=httpx.MockTransport(lambda r:pytest.fail("external call")))
    assert DecisionRouter(provider,enabled=True).decide(request()).reason==reason


@pytest.mark.parametrize("status,reason", [(401,Reason.AUTHENTICATION),(403,Reason.AUTHENTICATION),
    (429,Reason.RATE_LIMIT),(500,Reason.PROVIDER_ERROR),(302,Reason.PROVIDER_ERROR)])
def test_http_failures_redacted_no_retry_no_redirect(monkeypatch,status,reason):
    provider,calls=harness(monkeypatch,post=lambda r:fixture_response(status,text=KEY+" raw SQL private path",
        headers={"Location":"https://attacker.example"}))
    result=DecisionRouter(provider,enabled=True).decide(request())
    assert result.reason==reason and len(calls)==2
    assert KEY not in result.model_dump_json()


def test_timeout_redacted_no_retry(monkeypatch):
    def timeout(r): raise httpx.ReadTimeout(KEY,request=r)
    provider,calls=harness(monkeypatch,post=timeout)
    result=DecisionRouter(provider,enabled=True).decide(request())
    assert result.reason==Reason.TIMEOUT and len(calls)==2
    assert KEY not in result.model_dump_json()


@pytest.mark.parametrize("body", [b"not-json",b"{}",b"[1]",b'{"model":"one","model":"two"}',
    b"x"*16385, b"["*2000+b"]"*2000], ids=["non-json","empty","array","duplicate","oversize","deep"])
def test_malformed_oversized_output(monkeypatch,body):
    provider,calls=harness(monkeypatch,post=lambda r:fixture_response(200,content=body,
        headers={"Content-Type":"application/json"}))
    assert DecisionRouter(provider,enabled=True).decide(request()).reason==Reason.INVALID_OUTPUT
    assert len(calls)==2


@pytest.mark.parametrize("change", [dict(model="unknown"),dict(model=KEY),dict(usage=None),dict(extra="execute"),
    dict(answers={"route":{"type":"choice","choice":"ROOT","confidence":0.9,"probabilities":{"ROOT":1.0}}}),
    dict(usage={"input_tokens":True,"output_tokens":12}),dict(usage={"input_tokens":-1,"output_tokens":12})])
def test_strict_response_validation(monkeypatch,change):
    provider,_=harness(monkeypatch,post=lambda r:fixture_response(200,json={**RESPONSE,**change}))
    assert DecisionRouter(provider,enabled=True).decide(request()).reason==Reason.INVALID_OUTPUT


@pytest.mark.parametrize("confidence", [-0.1,1.1,True,"0.9"])
def test_invalid_provider_confidence(monkeypatch,confidence):
    data=json.loads(json.dumps(RESPONSE));data["answers"]["route"]["confidence"]=confidence
    provider,_=harness(monkeypatch,post=lambda r:fixture_response(200,json=data))
    assert DecisionRouter(provider,enabled=True).decide(request()).reason==Reason.INVALID_OUTPUT


def test_low_confidence_and_enabled_policy_cannot_bypass_workflow(monkeypatch):
    data=json.loads(json.dumps(RESPONSE));data["answers"]["route"].update(choice="RESEARCHER",
        probabilities={"PLANNER":0.1,"RESEARCHER":0.9})
    provider,_=harness(monkeypatch,post=lambda r:fixture_response(200,json=data))
    assert DecisionRouter(provider,enabled=True).decide(request(workflow_state="PLANNING")).reason==Reason.DISALLOWED_ROUTE
    data["answers"]["route"]["confidence"]=0.3
    provider,_=harness(monkeypatch,post=lambda r:fixture_response(200,json=data))
    assert DecisionRouter(provider,enabled=True).decide(request()).reason==Reason.LOW_CONFIDENCE


def test_bounded_discovery_unknown_model_and_duplicate_names(monkeypatch):
    for models in [{"models":MODELS["models"]*17},{"models":[MODELS["models"][0]]*2},{"models":[]},
        {"models":[{**MODELS["models"][0],"release_date":"not-date"}]}]:
        provider,calls=harness(monkeypatch,models=models)
        assert DecisionRouter(provider,enabled=True).decide(request()).reason==Reason.INVALID_OUTPUT
        assert len(calls)==1
    provider,calls=harness(monkeypatch,settings=TypeSafeSettings(enabled=True,model="not-advertised"))
    assert DecisionRouter(provider,enabled=True).decide(request()).reason==Reason.MODEL_UNAVAILABLE
    assert len(calls)==1


def test_total_call_budget_includes_discovery(monkeypatch):
    provider,calls=harness(monkeypatch,settings=TypeSafeSettings(enabled=True,model="fixture-alias",max_requests=2))
    router=DecisionRouter(provider,enabled=True)
    assert router.decide(request()).accepted
    assert router.decide(request()).reason==Reason.BUDGET_EXHAUSTED
    assert len(calls)==2


def test_rate_limit_and_usage_budget(monkeypatch):
    for settings,reason in [(TypeSafeSettings(enabled=True,model="fixture-alias",requests_per_minute=1),Reason.RATE_LIMIT),
        (TypeSafeSettings(enabled=True,model="fixture-alias",max_observed_input_tokens=100),Reason.BUDGET_EXHAUSTED)]:
        provider,calls=harness(monkeypatch,settings=settings)
        router=DecisionRouter(provider,enabled=True)
        first=router.decide(request())
        if reason==Reason.RATE_LIMIT: assert first.reason==reason and len(calls)==1
        else: assert first.accepted and router.decide(request()).reason==reason and len(calls)==2


def test_optional_operator_tariff_is_estimate_not_billed_cost(monkeypatch):
    settings=TypeSafeSettings(enabled=True,model="fixture-alias",input_usd_per_million=Decimal("0.042"),
        output_usd_per_million=Decimal("0"),max_estimated_spend_usd=Decimal("0.000001"))
    provider,calls=harness(monkeypatch,settings=settings)
    router=DecisionRouter(provider,enabled=True)
    first=router.decide(request())
    assert first.proposal.estimated_cost_usd==Decimal("0.00000504")
    assert first.proposal.provider_cost_usd is None and first.proposal.pricing_source=="operator-configured"
    assert router.decide(request()).reason==Reason.BUDGET_EXHAUSTED
    assert len(calls)==2


def test_escalation_is_bounded_noul_advice(monkeypatch):
    data=json.loads(json.dumps(RESPONSE));data["answers"]["escalate"]={"type":"noul","noul":0.9}
    provider,calls=harness(monkeypatch,post=lambda r:fixture_response(200,json=data))
    receipt=DecisionRouter(provider,enabled=True).decide(request(escalation_allowed=True))
    assert receipt.accepted and receipt.escalate
    assert set(json.loads(calls[1].content)["questions"])=={"route","escalate"}


def test_no_execution_or_active_host_wiring():
    root=Path(__file__).resolve().parents[2]/"src/qa_sentinel"
    for path in [root/"decisions/typesafe.py",root/"orchestration/decision_router.py"]:
        text=path.read_text(encoding="utf-8")
        for term in ["playwright", "subprocess", "MutationService", "WorkflowEngine", "UnitOfWork"]:
            assert term not in text
    # Only explicit standalone consumers can construct this foundation.
    for area in ["host","execution","application","api"]:
        for path in (root/area).glob("*.py"):
            assert "TypeSafeDecisionProvider" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("encoding", ["gzip", "br"])
def test_encoded_response_rejected_before_decompression(monkeypatch, encoding):
    provider,_=harness(monkeypatch,post=lambda r:fixture_response(200,content=b"not-compressed",
        headers={"Content-Type":"application/json","Content-Encoding":encoding}))
    assert DecisionRouter(provider,enabled=True).decide(request()).reason in {Reason.INVALID_OUTPUT,Reason.PROVIDER_ERROR}


def test_response_probabilities_and_answer_types_strict(monkeypatch):
    for answer in [{"type":"noul","noul":0.9},
        {"type":"choice","choice":"PLANNER","confidence":0.9,"probabilities":{"PLANNER":0.8,"RESEARCHER":0.8}},
        {"type":"choice","choice":"PLANNER","confidence":0.9,"probabilities":{"PLANNER":0.1,"RESEARCHER":0.9}}]:
        provider,_=harness(monkeypatch,post=lambda r:fixture_response(200,json={**RESPONSE,"answers":{"route":answer}}))
        assert DecisionRouter(provider,enabled=True).decide(request()).reason==Reason.INVALID_OUTPUT


def test_whole_attempt_deadline_includes_discovery(monkeypatch):
    import qa_sentinel.decisions.typesafe as adapter
    clock=[0.0]
    monkeypatch.setattr(adapter,"monotonic",lambda:clock[0])
    provider,calls=harness(monkeypatch)
    original=provider._transport.handler
    def late(req):
        clock[0]=4.0
        return original(req)
    provider._transport.handler=late
    assert DecisionRouter(provider,enabled=True).decide(request()).reason==Reason.TIMEOUT
    assert len(calls)==1


def test_lock_contention_is_fail_closed(monkeypatch):
    provider,calls=harness(monkeypatch)
    provider._lock.acquire()
    try:
        assert DecisionRouter(provider,enabled=True).decide(request()).reason==Reason.RATE_LIMIT
        assert calls==[]
    finally:
        provider._lock.release()


def test_bounded_request_has_no_secret_or_document_context():
    from uuid import uuid4
    req=request(evidence_refs=tuple(uuid4() for _ in range(16)),escalation_allowed=True)
    assert len(req.model_dump_json())<4096
    with pytest.raises(ValidationError):
        request(evidence_refs=tuple(uuid4() for _ in range(17)))


@pytest.mark.parametrize("probability", [0.21,0.5,0.79])
def test_uncertain_escalation_cannot_be_labeled_no(monkeypatch,probability):
    data=json.loads(json.dumps(RESPONSE))
    data["answers"]["escalate"]={"type":"noul","noul":probability}
    provider,calls=harness(monkeypatch,post=lambda r:fixture_response(200,json=data))
    result=DecisionRouter(provider,enabled=True).decide(request(escalation_allowed=True))
    assert result.reason==Reason.LOW_CONFIDENCE and not result.accepted
    assert result.route=="PLANNER" and len(calls)==2
