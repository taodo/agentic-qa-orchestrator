"""Issue #101: canonical human Tests, exact sealing and truthful Chromium evidence."""
import json
from copy import deepcopy
from uuid import uuid4
import pytest
from pydantic import ValidationError
from sqlalchemy import text
from qa_sentinel.agents.browser_grounding import BrowserGroundingReasoner, test_intent as intent
from qa_sentinel.domain.browser_grounding import GroundingLimitation, ObservedElement
from qa_sentinel.domain.browser_execution import RoleLocator
from qa_sentinel.execution.playwright_browser import PlaywrightBrowserExecutor
from qa_sentinel.execution.browser_observer import PlaywrightBrowserObserver
from qa_sentinel.models.base import ModelSettings
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from test_browser_grounding import source_free, observation, Observer, observation_site
from test_browser_batches import Runtime
from test_campaign_test_specifications import case, csv_text, seed_requirement
from qa_sentinel.agents.test_generation import TestSpecificationGenerator as Generator


def smoke(name="Example Domain"):
    value=case("SMOKE")
    value.update(title=f"{name} home page loads and displays its main heading",preconditions=[],
        steps=[dict(index=1,action=f"Open the {name} home page.",expected="The home page loads successfully."),
               dict(index=2,action="Observe the main heading on the loaded page.",expected=f'The heading "{name}" is visible.')],
        overall_expected_result=f'The {name} home page loads successfully and visibly displays the heading "{name}".',
        required_evidence=["Navigation/load outcome and visible heading assertion"])
    return value


def output(request):
    context=json.loads(request["input"][0]["content"]);obs=context["observation"];scope=context["scope"]
    name=context["approved_test_intent"]["steps"][1]["semantic_outcome"]["text"]
    heading=next((e for e in obs["elements"] if e["name"]==name),None)
    if heading is None:
        return dict(observation_id=obs["id"],observation_hash=obs["observation_hash"],test_hash=scope["test_hash"],target_hash=scope["target_hash"],disposition="CANNOT_GROUND",steps=[],reason="GROUNDING_UNAVAILABLE",affected_step=2)
    return dict(observation_id=obs["id"],observation_hash=obs["observation_hash"],test_hash=scope["test_hash"],target_hash=scope["target_hash"],disposition="GROUNDED",reason=None,steps=[
        dict(step_index=1,operations=[dict(action="NAVIGATE",element_ref=None,path_ref="p1",value_ref=None)],assertion=dict(kind="PAGE_LOAD",element_ref=None,path_ref="p1")),
        dict(step_index=2,operations=[],assertion=dict(kind="VISIBLE",element_ref=heading["ref"],path_ref=None))])


def imported(data,value):
    app=data[0];p,c=data[4:6]
    app.import_campaign_tests(p.id,c.id,name="Human Tests",format="CSV",content=csv_text([value]))
    return next(t for t in app.list_campaign_test_specifications(p.id,c.id).items if t.key==value["key"])


class SemanticRuntime(Runtime):
    """Offline batch/mode fixture; only the Chromium tests below assert real outcomes."""
    def for_mode(self,mode):return SemanticRuntime(self.calls,mode)
    def execute(self,envelope,run,test):
        from qa_sentinel.domain.evidence_variants import BrowserObservation
        from qa_sentinel.domain.qa_run_evidence import TestExecutionResult as Result,EvidenceDraft
        self.calls.append((test.content.key,self.mode))
        evidence=[]
        for number,step in enumerate(envelope.plan.steps,1):
            observation=BrowserObservation(category="NAVIGATION" if step.action=="NAVIGATE" else "ASSERTION",run_test_id=test.id,plan_hash=envelope.plan_hash,step_number=number,action=step.action,matched=True,outcome="PASS",browser_version=self.identity.browser_version)
            evidence.append(EvidenceDraft(source="web-browser",payload=observation,summary=observation.safe_summary()))
        return Result(executor_kind="WEB_BROWSER",qa_result="PASS",evidence=tuple(evidence))


def setup(data,mock_openai,*,value=None,generated=False,choose=output,build=None):
    app=data[0];p,c=data[4:6];value=value or smoke()
    if generated:
        requirement=seed_requirement(data[1],p,c,"HEADING")
        app.review_campaign_requirement(p.id,c.id,requirement.id,reviewer_label="human")
        def generate(request):
            ids=json.loads(request["input"][0]["content"])["selected_requirement_ids"]
            design=deepcopy(value);design.pop("requirement_refs");design["requirement_ids"]=ids
            return dict(selected_requirement_ids=ids,tests=[design])
        model=mock_openai([generate]);app._test_generator=Generator(OpenAIModelAdapter(client=model.client),ModelSettings(model="offline"))
        receipt=app.generate_campaign_tests(p.id,c.id,requirement_ids=[requirement.id]);assert receipt.status=="SUCCEEDED"
        test=next(t for t in app.list_campaign_test_specifications(p.id,c.id).items if t.key==value["key"])
    else:test=imported(data,value)
    app.review_source_free_campaign_test(p.id,c.id,test.id,reviewer_label="human")
    test=app.get_campaign_test_specification(p.id,c.id,test.id)
    name=value["steps"][1]["expected"].split('"')[1]
    loc=RoleLocator(strategy="ROLE",role="heading",name=name,exact=True)
    observer=Observer(build or (lambda scope:observation(scope,elements=(ObservedElement(ref="e1",role="heading",name=name,text=name,locator=loc,matches=1),))))
    mock=mock_openai([choose]);app._browser_observer=observer
    app._browser_grounding_reasoner=BrowserGroundingReasoner(OpenAIModelAdapter(client=mock.client),ModelSettings(model="offline"))
    app._browser_executor=SemanticRuntime()
    return test,mock,observer


def execute(data,test,mode="HEADLESS"):
    app=data[0];p,c=data[4:6]
    batch=app.submit_browser_batch(p.id,c.id,idempotency_key=str(uuid4()),test_specification_ids=[test.id],browser_mode=mode)
    app.execute_browser_batch(p.id,c.id,batch.id)
    return app.get_browser_batch(p.id,c.id,batch.id)


@pytest.mark.parametrize("generated",[False,True])
@pytest.mark.parametrize("mode",["HEADLESS","HEADED"])
def test_exact_smoke_is_runnable_with_same_canonical_sealed_meaning(source_free,mock_openai,generated,mode):
    data=source_free;test,mock,observer=setup(data,mock_openai,generated=generated)
    assert test.overall_expected_result not in {s.expected for s in test.steps}
    done=execute(data,test,mode);assert done.summary["runnable"]==done.summary["passed"]==1 and done.run is not None
    assert data[0]._browser_executor.calls==[(test.key,mode)]
    app=data[0];p,c=data[4:6]
    run_test=app.list_qa_run_tests(p.id,c.id,done.run.id).items[0]
    assert [s.action for s in run_test.browser_plan.plan.steps]==["NAVIGATE","ASSERT_PAGE_LOAD","ASSERT_TEXT","ASSERT_VISIBLE"]
    assert run_test.browser_plan.plan.steps[-1].locator.name=="Example Domain"
    assert run_test.content.model_dump()==test.model_dump(include=set(type(run_test.content).model_fields))
    from qa_sentinel.domain.campaign_review import content_hash
    assert content_hash(run_test.content)==run_test.approval.content_hash
    assert len(mock.calls)==len(observer.calls)==1
    assert bool(test.requirement_ids)==generated
    assert done.run.requirement_count==int(generated)


@pytest.mark.parametrize("failure",["missing","duplicate","wrong-role","weakened-load","wrong-assertion","extra-operation"])
def test_unavailable_ambiguous_or_malformed_grounding_creates_no_run(source_free,mock_openai,failure):
    loc=RoleLocator(strategy="ROLE",role="heading",name="Example Domain",exact=True)
    def build(scope):
        elements=() if failure=="missing" else (ObservedElement(ref="e1",role="heading",name="Example Domain",text="Example Domain",locator=loc,matches=2 if failure=="duplicate" else 1),)
        if failure=="wrong-role":elements=(ObservedElement(ref="e1",role="button",name="Example Domain",locator=RoleLocator(strategy="ROLE",role="button",name="Example Domain",exact=True),matches=1),)
        return observation(scope,elements=elements)
    def choose(request):
        value=output(request)
        if failure=="weakened-load":value["steps"][0]["assertion"]["kind"]="URL"
        if failure=="wrong-assertion":value["steps"][1]["assertion"]["kind"]="TEXT"
        if failure=="extra-operation":value["steps"][1]["operations"]=[dict(action="NAVIGATE",path_ref="p1",element_ref=None,value_ref=None)]
        return value
    test,mock,_=setup(source_free,mock_openai,build=build,choose=choose)
    done=execute(source_free,test)
    assert done.summary["needs_attention"]==1 and done.summary["runnable"]==0 and done.run is None
    assert done.items.items[0].qa_result is None


@pytest.mark.parametrize("change",["summary-extra","auth","secret","unsupported","different-page","unnamed-route"])
def test_unaccounted_meaning_is_not_silently_dropped(source_free,change):
    value=smoke()
    if change=="summary-extra":value["overall_expected_result"]+=' Payments are processed.'
    if change=="auth":value["steps"][0]["action"]="Log in to the home page."
    if change=="secret":value["preconditions"]=["Use password hunter2"]
    if change=="unsupported":value["steps"][1]["action"]="Download the report."
    if change=="different-page":value["steps"][0]["action"]="Open the Account home page."
    if change=="unnamed-route":
        value["steps"][0]["action"]="Open the Checkout page."
        value["overall_expected_result"]='The home page loads successfully and The heading "Example Domain" is visible.'
    test=imported(source_free,value)
    from qa_sentinel.domain.target import TargetSnapshot
    with pytest.raises(GroundingLimitation):intent(test,TargetSnapshot.capture(source_free[-1]))


def test_supported_text_wording_and_exact_composed_summary(source_free):
    value=smoke();value["steps"][1]["action"]="Verify the heading.";value["steps"][1]["expected"]='The heading reads "Example Domain".'
    value["overall_expected_result"]='The home page loads successfully and The heading reads "Example Domain".'
    test=imported(source_free,value)
    from qa_sentinel.domain.target import TargetSnapshot
    parsed=intent(test,TargetSnapshot.capture(source_free[-1]))
    assert parsed["steps"][1]["semantic_outcome"]==dict(kind="HEADING_TEXT",text="Example Domain")


@pytest.mark.parametrize("status,heading",[(200,"Example Domain"),(404,"Example Domain"),(200,"Changed heading")])
def test_real_chromium_load_and_visible_heading_evidence(source_free,mock_openai,status,heading):
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from threading import Thread
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            body=('<h1 aria-label="Example Domain">'+heading+'</h1>').encode()
            self.send_response(status);self.send_header("Content-Type","text/html");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    site=f"http://127.0.0.1:{server.server_port}"
    try:
        test,_,_=setup(source_free,mock_openai)
        app=source_free[0];p,c=source_free[4:6]
        target=app.create_target(p.id,name="Controlled page",environment="LOCAL",configuration={"base_url":site})
        app.associate_campaign_target(p.id,c.id,target_id=target.id)
        app._browser_executor=PlaywrightBrowserExecutor(trusted_local_origin=site)
        app._browser_observer=PlaywrightBrowserObserver(trusted_local_origin=site)
        done=execute(source_free,test)
        assert done.run is not None and done.run.execution_status=="COMPLETED"
        passed=status==200 and heading=="Example Domain"
        assert done.summary["passed"]==int(passed) and done.summary["failed"]==int(not passed)
        item=done.items.items[0]
        evidence=app.list_qa_run_test_evidence(p.id,c.id,done.run.id,item.run_test_id).items
        assert [e.payload.action for e in evidence]==(["NAVIGATE","ASSERT_PAGE_LOAD","ASSERT_TEXT","ASSERT_VISIBLE"] if passed else ["NAVIGATE","ASSERT_PAGE_LOAD","ASSERT_TEXT"] if status==200 else ["NAVIGATE","ASSERT_PAGE_LOAD"])
        assert '2xx main response' in evidence[1].summary
        assert evidence[1].payload.matched==(status==200)
        assert not any('overall' in e.summary.lower() for e in evidence)
    finally:server.shutdown();server.server_close();thread.join(timeout=2)


def test_removing_summary_equality_alone_does_not_make_literal_output_executable(source_free,mock_openai):
    def legacy(request):
        value=output(request)
        value["steps"][0]["assertion"]=dict(kind="TEXT",element_ref="e1",path_ref=None)
        return value
    test,_,_=setup(source_free,mock_openai,choose=legacy)
    done=execute(source_free,test)
    assert done.run is None and done.summary["needs_attention"]==1


def test_legacy_grounding_receipt_keeps_original_intent_hash(source_free,mock_openai):
    from test_browser_grounding import active,ground,model_output
    from qa_sentinel.agents.browser_grounding import validated_constraints
    from qa_sentinel.domain.browser_grounding import BrowserGroundingRecord,digest
    data=source_free;app=data[0];p,c=data[4:6]
    mock=mock_openai([model_output]);app._browser_observer=Observer()
    app._browser_grounding_reasoner=BrowserGroundingReasoner(OpenAIModelAdapter(client=mock.client),ModelSettings(model="offline"))
    record=ground(data,active(data));observation_record=app.get_browser_grounding_observation(p.id,c.id,record.observation_id)
    test=app.get_campaign_test_specification(p.id,c.id,record.scope.test_id)
    approval=app.get_campaign_test_specification_review(p.id,c.id,test.id).evidence
    legacy=BrowserGroundingRecord.model_validate({**record.model_dump(),"prompt_version":"browser-grounder-v1"})
    assert record.intent_hash==digest(intent(test,record.scope.target,semantic=False))
    assert validated_constraints(legacy,observation_record,test,approval)==record.constraints
