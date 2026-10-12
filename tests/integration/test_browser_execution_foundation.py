"""Snapshot provenance, no-browser refusal and historical evidence compatibility."""
from uuid import uuid4
import socket
import subprocess
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from qa_sentinel.api import create_api_app
from qa_sentinel.domain.browser_execution import BrowserExecutionPlan, BrowserPlanEnvelope
from qa_sentinel.domain.qa_run import CreateQARun
from qa_sentinel.domain.qa_run_evidence import TestExecutionResult as ResultContract
from qa_sentinel.execution.browser import UnavailableBrowserExecutor, BrowserRuntimeUnavailable
from qa_sentinel.execution.browser_policy import BrowserExecutionPolicy, BrowserPolicyError, digest, run_test_snapshot_digest
from qa_sentinel.execution.synthetic_run import execute_synthetic, SyntheticRunExecutor
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from test_qa_runs import ready, create
from test_campaign_review import review


@pytest.fixture
def browser_candidate(ready):
    app, _, _, _, p, c, _, _ = ready
    target = app.create_target(p.id,name="WEB",environment="STAGING",configuration={"base_url":"https://example.com/app"})
    app.associate_campaign_target(p.id,c.id,target_id=target.id)
    run = create(ready)
    test = app.list_qa_run_tests(p.id,c.id,run.id).items[0]
    plan = BrowserExecutionPlan(steps=({"action":"NAVIGATE","path":"/courses"},))
    envelope = BrowserPlanEnvelope(project_id=p.id,campaign_id=c.id,run_id=run.id,run_test_id=test.id,
        origin="MANUAL",test_snapshot_hash=run_test_snapshot_digest(test),target_snapshot_hash=digest(run.target_snapshot),
        plan_hash=digest(plan),plan=plan)
    return ready, run, test, envelope


def test_candidate_hashes_exact_plan_and_frozen_target(browser_candidate):
    ready,run,test,envelope=browser_candidate
    app,_,_,_,p,c,_,_=ready
    assert BrowserExecutionPolicy().validate_envelope(envelope,run,test)==envelope
    app.update_target(p.id,run.target_snapshot.target_id,configuration={"base_url":"https://different.example"})
    assert app.get_qa_run(p.id,c.id,run.id).target_snapshot==run.target_snapshot
    assert BrowserExecutionPolicy().validate_envelope(envelope,run,test)==envelope
    for field in ("project_id","campaign_id","run_id","run_test_id"):
        forged=envelope.model_copy(update={field:uuid4()})
        with pytest.raises(BrowserPolicyError,match="BROWSER_PROVENANCE_REJECTED"):
            BrowserExecutionPolicy().validate_envelope(forged,run,test)
    for field in ("plan_hash","test_snapshot_hash","target_snapshot_hash"):
        with pytest.raises(BrowserPolicyError,match="BROWSER_PROVENANCE_REJECTED"):
            BrowserExecutionPolicy().validate_envelope(envelope.model_copy(update={field:"0"*64}),run,test)
    assert run_test_snapshot_digest(test)==run_test_snapshot_digest(test.model_copy(update={"execution_status":"RUNNING"}))


def test_no_runtime_no_fallback_no_effects_or_evidence(browser_candidate,monkeypatch):
    ready,run,test,envelope=browser_candidate
    app,_,_,_,p,c,_,_=ready
    def forbidden(*args,**kwargs): raise AssertionError("External capability forbidden")
    for obj,name in [(socket,"getaddrinfo"),(socket.socket,"connect"),(subprocess,"Popen"),(OpenAIModelAdapter,"generate"),(SyntheticRunExecutor,"evaluate")]:
        monkeypatch.setattr(obj,name,forbidden)
    with pytest.raises(BrowserRuntimeUnavailable,match="BROWSER_RUNTIME_UNAVAILABLE"):
        UnavailableBrowserExecutor().execute(envelope,run,test)
    saved=app.get_qa_run(p.id,c.id,run.id)
    assert saved.execution_status=="CREATED" and saved.qa_outcome=="NOT_EVALUATED"
    assert app.get_qa_run_results(p.id,c.id,run.id).tests.items[0].evidence_count==0


def test_web_selection_and_fake_browser_results_fail_closed(browser_candidate):
    ready,run,test,_=browser_candidate
    app,_,_,_,p,c,_,_=ready
    with pytest.raises(ValidationError): CreateQARun(idempotency_key="web",executor_kind="WEB_BROWSER")
    result=execute_synthetic(SyntheticRunExecutor(),test)
    assert result.executor_kind=="SYNTHETIC"
    with pytest.raises(ValidationError): ResultContract.model_validate({**result.model_dump(),"executor_kind":"WEB_BROWSER"})
    client=TestClient(create_api_app(app))
    base=f"/api/v1/projects/{p.id}/campaigns/{c.id}/runs/{run.id}"
    assert client.post(base+"/start",json={"executor_kind":"WEB_BROWSER"}).status_code==422
    assert app.get_qa_run(p.id,c.id,run.id).execution_status=="CREATED"


def test_historical_synthetic_identity_reopen_and_api_reads(ready):
    app,_,engine,_,p,c,_,_=ready
    run=create(ready)
    final=app.start_qa_run(p.id,c.id,run.id)
    engine.dispose()
    view=app.get_qa_run_results(p.id,c.id,run.id)
    assert final.execution_status=="COMPLETED" and final.qa_outcome=="PASS"
    record=view.tests.items[0].evidence.items[0]
    assert record.executor_kind=="SYNTHETIC" and record.source=="synthetic"
    from qa_sentinel.application.qa_run_results import QARunEvidenceView
    with pytest.raises(ValidationError):
        QARunEvidenceView.model_validate({**record.model_dump(),"executor_kind":"WEB_BROWSER"})
    client=TestClient(create_api_app(app))
    data=client.get(f"/api/v1/projects/{p.id}/campaigns/{c.id}/runs/{run.id}/results").json()
    assert data["tests"]["items"][0]["evidence"]["items"][0]["executor_kind"]=="SYNTHETIC"
