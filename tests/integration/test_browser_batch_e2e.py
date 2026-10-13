"""Normal API → existing worker → real secured Chromium. Disposable fixtures, fake provider."""
from types import SimpleNamespace
from threading import Event
import json
import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient
from qa_sentinel.api import create_api_app
from qa_sentinel.host.browser_http import add_browser_http
from qa_sentinel.host.admission import ExecutionAdmission
from qa_sentinel.host.worker import ExecutionWorker
from qa_sentinel.execution.playwright_browser import PlaywrightBrowserExecutor
from qa_sentinel.execution.browser_observer import PlaywrightBrowserObserver
from qa_sentinel.agents.browser_grounding import BrowserGroundingReasoner
from qa_sentinel.models.base import ModelSettings
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from test_campaign_test_specifications import seed_requirement,case
from qa_sentinel.agents.test_generation import TestSpecificationGenerator as Generator
from test_browser_batches import batch
from test_browser_grounding import source_free,observation_site,output_for


@pytest.mark.parametrize("scenario",["imported-pass","imported-mixed","generated"])
def test_normal_headless_real_chromium_no_spec_and_mixed_truth(batch,mock_openai,observation_site,monkeypatch,scenario):
    mixed=scenario=="imported-mixed"
    data,specs,_,_,_=batch;app=data[0];p,c=data[4:6]
    site,seen=observation_site
    target=app.create_target(p.id,name="Disposable generic Target",environment="LOCAL",configuration={"base_url":site})
    app.associate_campaign_target(p.id,c.id,target_id=target.id)
    executor=PlaywrightBrowserExecutor(trusted_local_origin=site)
    app._browser_executor=executor;app._browser_observer=PlaywrightBrowserObserver(trusted_local_origin=site)
    def choose(request):
        context=json.loads(request["input"][0]["content"]);value=output_for(context)
        heading=next(e for e in context["observation"]["elements"] if e["role"]=="heading" and e["name"]=="Welcome")
        value["steps"][0]["assertion"]["element_ref"]=heading["ref"]
        if context["approved_test_intent"]["steps"][0]["action"]=="Click Missing":value.update(disposition="CANNOT_GROUND",steps=[],reason="GROUNDING_UNAVAILABLE",affected_step=1)
        return value
    mock=mock_openai([choose]*(3 if mixed else 1))
    app._browser_grounding_reasoner=BrowserGroundingReasoner(OpenAIModelAdapter(client=mock.client),ModelSettings(model="offline-structured"))
    app._browser_plan_generator=object();app._execution_admission=ExecutionAdmission()
    worker=ExecutionWorker(app,app._execution_admission,Event())
    monkeypatch.setenv("OPENAI_API_KEY","SYNTHETIC_NEVER_NETWORK")
    api=create_api_app(app);add_browser_http(api,SimpleNamespace(host="127.0.0.1",port=8000,projects=[SimpleNamespace(key=p.key)]))
    base=f"/api/v1/projects/{p.id}/campaigns/{c.id}/browser"
    selected=specs if mixed else [specs[1]]
    if scenario=="generated":
        requirement=seed_requirement(data[1],p,c,"WELCOME")
        app.review_campaign_requirement(p.id,c.id,requirement.id,reviewer_label="human")
        def generate(request):
            context=json.loads(request["input"][0]["content"]);ids=context["selected_requirement_ids"]
            value=case("GENERATED");value.pop("requirement_refs")
            value.update(title="Public page heading",requirement_ids=ids,preconditions=[],steps=[dict(index=1,action="Open the public page",expected="Welcome")],overall_expected_result="Welcome",required_evidence=["Heading assertion"])
            return dict(selected_requirement_ids=ids,tests=[value])
        generation=mock_openai([generate]);app._test_generator=Generator(OpenAIModelAdapter(client=generation.client),ModelSettings(model="offline-designer"))
        receipt=app.generate_campaign_tests(p.id,c.id,requirement_ids=[requirement.id]);assert receipt.status=="SUCCEEDED"
        selected=[t for t in app.list_campaign_test_specifications(p.id,c.id).items if t.key=="GENERATED"]
        assert len(selected)==1 and selected[0].provenance.origin=="AI_GENERATED"
        app.review_campaign_test_specification(p.id,c.id,selected[0].id,reviewer_label="human")
    with TestClient(api,base_url="http://127.0.0.1:8000",client=("127.0.0.1",123),headers={"origin":"http://127.0.0.1:8000"}) as client:
        created=client.post(base+"/batches",json=dict(idempotency_key="normal-browser",test_specification_ids=[str(t.id) for t in selected],browser_mode="HEADLESS"))
        assert created.status_code==201,created.text
        id=created.json()["id"];assert not seen and not mock.calls
        assert worker.execute_one() and not worker.execute_one()
        done=client.get(base+"/batches/"+id).json()
        assert done["run"] is not None, done["items"]
        assert done["run"]["execution_status"]=="COMPLETED" and done["run"]["executor_kind"]=="WEB_BROWSER"
        assert done["browser_mode"]=="HEADLESS" and done["run"]["runtime_identity"]["engine"]=="CHROMIUM"
        assert [item["outcome"] for item in done["items"]["items"]]==(["FAIL","PASS","NEEDS_ATTENTION"] if mixed else ["PASS"])
        assert done["summary"]["passed"]==1 and done["summary"]["failed"]==int(mixed) and done["summary"]["needs_attention"]==int(mixed)
        assert done["selected_count"]==len(selected) and done["run"]["test_count"]==(2 if mixed else 1)
        assert done["run"]["requirement_count"]==int(scenario=="generated")
        assert all(item["evidence_count"]>=2 for item in done["items"]["items"] if item["run_test_id"])
        assert len(mock.calls)==len(selected) and all(call["tools"]==[] for call in mock.calls)
        before=(len(seen),len(mock.calls));assert client.get(base+"/batches/"+id).json()==done
        assert (len(seen),len(mock.calls))==before
        assert "never-persist-this" not in json.dumps(done) and "do-not-capture" not in json.dumps(done)
    with data[2].connect() as db:
        assert db.scalar(text("SELECT count(*) FROM campaign_sources"))==int(scenario=="generated")
        assert db.scalar(text("SELECT count(*) FROM campaign_requirements"))==int(scenario=="generated")
        assert db.execute(text("PRAGMA foreign_key_check")).all()==[]
