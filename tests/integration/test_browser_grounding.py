"""Bounded reference-only grounding: no Run, no live provider or public internet."""
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
import json
import pytest
from alembic import command
from sqlalchemy import text,inspect
from sqlalchemy.exc import IntegrityError
from pydantic import ValidationError,TypeAdapter
from qa_sentinel.application import ApplicationError
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.domain.browser_grounding import (BrowserGroundingObservation,BrowserGroundingRecord,
    GroundingOutput,GroundingScope,GroundingLimitation,ObservedElement,ObservedPath,digest,now,action_hint)
from qa_sentinel.domain.browser_execution import RoleLocator,BrowserErrorCode,BrowserExecutionPlan
from qa_sentinel.execution.browser_policy import BrowserExecutionPolicy
from qa_sentinel.execution.browser_network import BrowserExecutionError
from qa_sentinel.execution.browser_observer import PlaywrightBrowserObserver
from qa_sentinel.agents.browser_grounding import BrowserGroundingReasoner,validate_grounding,validated_constraints
from qa_sentinel.agents.browser_plan_generation import BrowserPlanGenerator,validate_system_candidate
from qa_sentinel.models.base import ModelSettings
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from test_browser_preparation import source_free,approve_source_free,prepare,stored,transition
from test_browser_plan_generation import Executor,rows
from test_campaign_test_specifications import case,csv_text


LOC=RoleLocator(strategy="ROLE",role="heading",name="Welcome",exact=True)


def observation(scope,*,elements=None,title="Welcome",paths=None):
    elements=elements if elements is not None else (ObservedElement(ref="e1",role="heading",name="Welcome",text="Welcome",locator=LOC,matches=1),)
    stamp=now()
    from urllib.parse import urlsplit
    value=dict(id=str(uuid4()),contract_version="browser-grounding-observation-v1",scope=scope.model_dump(mode="json"),
        runtime_identity=Executor.identity.model_dump(mode="json"),started_at=TypeAdapter(type(stamp)).dump_python(stamp,mode="json"),finished_at=TypeAdapter(type(stamp)).dump_python(stamp,mode="json"),
        current_path_ref="p1",title=title,elements=[e.model_dump(mode="json") for e in elements],
        paths=paths or [dict(ref="p1",path=urlsplit(scope.target.base_url).path or "/",source="TARGET_BASE",element_ref=None)])
    return BrowserGroundingObservation(**value,observation_hash=digest(value))


def output_for(context):
    obs=context["observation"];scope=context["scope"]
    return dict(observation_id=obs["id"],observation_hash=obs["observation_hash"],test_hash=scope["test_hash"],target_hash=scope["target_hash"],
        disposition="GROUNDED",steps=[dict(step_index=1,operations=[dict(action="NAVIGATE",element_ref=None,path_ref="p1",value_ref=None)],
            assertion=dict(kind="TEXT",element_ref="e1",path_ref=None))],reason=None,affected_step=None)


def model_output(request):return output_for(json.loads(request["input"][0]["content"]))


class Observer:
    def __init__(self,build=observation):self.calls=[];self.build=build
    def policy_for(self,target):return BrowserExecutionPolicy()
    def observe(self,scope):self.calls.append(scope);return self.build(scope)


def active(data,*,key="ground",ids=None):
    approve_source_free(data)
    record=stored(prepare(data,key=key,ids=ids or [data[6][0].id]))
    record=transition(data[1],record,"START")
    return transition(data[1],record,"START_ITEM",item_id=record.items[0].id)


@pytest.fixture
def grounding(source_free,mock_openai):
    app=source_free[0];mock=mock_openai([model_output]);observer=Observer()
    app._browser_observer=observer
    app._browser_grounding_reasoner=BrowserGroundingReasoner(OpenAIModelAdapter(client=mock.client),ModelSettings(model="configured-model"))
    prep=active(source_free)
    return source_free,prep,mock,observer


def ground(data,prep):
    app,_,_,_,p,c,*_=data;item=prep.items[0]
    return app.ground_browser_preparation_item(p.id,c.id,prep.id,item.id,item.attempt_id)


def test_durable_current_grounding_is_idempotent_inert_and_usage_authoritative(grounding,monkeypatch):
    data,prep,mock,observer=grounding;app,_,engine,_,p,c,*_=data
    baseline=rows(engine)
    def checked(scope):
        with engine.connect() as db:
            assert db.scalar(text("SELECT status FROM browser_groundings"))=="STARTED"
        return observation(scope)
    observer.build=checked
    record=ground(data,prep)
    assert record.status=="GROUNDED" and record.reason is None and action_hint(record) is None
    assert record.settings.model=="configured-model" and record.metadata.total_tokens==30
    assert len(mock.calls)==len(observer.calls)==1
    call=mock.calls[0];assert call["tools"]==[] and call["tool_choice"]=="none" and call["store"] is False
    context=json.loads(call["input"][0]["content"])
    assert record.metadata.context_selection.selected_chars==len(call["input"][0]["content"])
    assert record.metadata.context_selection.selected_bytes==len(call["input"][0]["content"].encode())
    assert "html" not in context["observation"] and "approved_browser_facts" not in context
    assert rows(engine)==baseline==(0,0,0,0)
    assert app.get_browser_preparation(p.id,c.id,prep.id).items[0].status=="PREPARING"
    import socket,subprocess
    monkeypatch.setattr(socket,"getaddrinfo",lambda *a,**k:pytest.fail("No DNS on read/replay"))
    monkeypatch.setattr(subprocess,"Popen",lambda *a,**k:pytest.fail("No browser on read/replay"))
    engine.dispose()
    assert app.get_browser_grounding(p.id,c.id,record.id)==record
    observed=app.get_browser_grounding_observation(p.id,c.id,record.observation_id)
    assert observed.observation_hash==record.observation_hash
    assert ground(data,prep)==record and len(mock.calls)==len(observer.calls)==1
    assert app.get_campaign_test_specification(p.id,c.id,prep.items[0].original_test_id).preconditions==()


@pytest.mark.parametrize("change",["element","path","observation_id","observation_hash","target_hash","test_hash","action","value","omit","extra"])
def test_model_cannot_invent_grounding(grounding,change):
    data,prep,mock,_=grounding
    def bad(request):
        value=model_output(request);step=value["steps"][0]
        if change=="element":step["assertion"]["element_ref"]="e99"
        elif change=="path":step["operations"][0]["path_ref"]="p99"
        elif change.endswith("hash"):value[change]="0"*64
        elif change=="observation_id":value[change]=str(uuid4())
        elif change=="action":step["operations"][0]["action"]="EVALUATE"
        elif change=="value":step["operations"][0]["value"]="fabricated"
        elif change=="omit":step["operations"]=[]
        else:step["assertion"]["selector"]="#invented"
        return value
    mock.queue.clear();mock.queue.append(bad)
    record=ground(data,prep)
    assert record.status in {"NEEDS_ATTENTION","SYSTEM_ERROR"} and record.output is None and record.constraints is None
    assert len(mock.calls)==1 and rows(data[2])==(0,0,0,0)


@pytest.mark.parametrize("missing",[True,False])
def test_ambiguous_or_missing_candidates_need_attention(grounding,missing):
    data,prep,mock,observer=grounding
    observer.build=lambda scope:observation(scope,elements=(ObservedElement(ref="e1",role="heading",name="Welcome",locator=LOC,matches=0 if missing else 2),))
    result=ground(data,prep)
    assert result.status=="NEEDS_ATTENTION" and result.reason==("GROUNDING_UNAVAILABLE" if missing else "AMBIGUOUS_TARGET")
    assert result.affected_step==1 and action_hint(result)


@pytest.mark.parametrize("code,status,reason",[(BrowserErrorCode.NETWORK,"NEEDS_ATTENTION","POLICY_REJECTED"),
    (BrowserErrorCode.UNSUPPORTED,"NEEDS_ATTENTION","UNSUPPORTED_BEHAVIOR"),
    (BrowserErrorCode.LAUNCH,"SYSTEM_ERROR","OBSERVATION_RUNTIME_ERROR"),
    (BrowserErrorCode.DNS,"SYSTEM_ERROR","OBSERVATION_RUNTIME_ERROR"),
    (BrowserErrorCode.CLEANUP,"SYSTEM_ERROR","OBSERVATION_RUNTIME_ERROR")])
def test_observation_failures_are_safe_distinct_not_qa_fail(grounding,code,status,reason):
    data,prep,mock,observer=grounding
    def fail(scope):raise BrowserExecutionError(code)
    observer.build=fail;record=ground(data,prep)
    assert (record.status,record.reason,record.browser_error_code)==(status,reason,code.value)
    assert record.observation_id is None and record.metadata is None and not mock.calls


def test_started_attempt_requires_reconciliation_without_replay(grounding):
    data,prep,mock,observer=grounding
    def crash(scope):raise KeyboardInterrupt()
    observer.build=crash
    with pytest.raises(KeyboardInterrupt):ground(data,prep)
    with pytest.raises(ApplicationError,match="GROUNDING_RECONCILIATION_REQUIRED"):ground(data,prep)
    assert len(observer.calls)==1 and not mock.calls


def test_wrong_attempt_and_cross_scope_reject_before_side_effect(grounding):
    data,prep,mock,observer=grounding;app,_,_,_,p,c,*_=data;item=prep.items[0]
    with pytest.raises(ApplicationError,match="PREPARATION_INVALID_STATE"):
        app.ground_browser_preparation_item(p.id,c.id,prep.id,item.id,uuid4())
    other=app.create_campaign(p.id,name="Other")
    with pytest.raises(ApplicationError,match="PREPARATION_NOT_FOUND"):
        app.ground_browser_preparation_item(p.id,other.id,prep.id,item.id,item.attempt_id)
    other_p=app.create_project(key="other",name="Other")
    with pytest.raises(ApplicationError):app.ground_browser_preparation_item(other_p.id,c.id,prep.id,item.id,item.attempt_id)
    assert not mock.calls and not observer.calls
    result=ground(data,prep)
    with pytest.raises(ApplicationError,match="GROUNDING_NOT_FOUND"):app.get_browser_grounding(p.id,other.id,result.id)
    with pytest.raises(ApplicationError,match="GROUNDING_NOT_FOUND"):app.get_browser_grounding_observation(p.id,other.id,result.observation_id)


def test_unknown_usage_stays_unknown(source_free,mock_openai):
    data=source_free;app=data[0];mock=mock_openai([model_output],usage_override=None)
    app._browser_observer=Observer();app._browser_grounding_reasoner=BrowserGroundingReasoner(OpenAIModelAdapter(client=mock.client),ModelSettings(model="configured-model"))
    result=ground(data,active(data))
    assert result.status=="GROUNDED" and result.metadata.total_tokens is None and result.metadata.input_tokens is None


def test_system_receipt_constrains_existing_planner_without_human_facts(grounding,mock_openai):
    data,prep,_,_=grounding;record=ground(data,prep);app=data[0];p,c=data[4:6];item=prep.items[0]
    obs=app.get_browser_grounding_observation(p.id,c.id,record.observation_id)
    def candidate(request):
        context=json.loads(request["input"][0]["content"]);facts=context["system_grounding"]
        assert "approved_browser_facts" not in context
        return dict(disposition="CANDIDATE",plan=dict(steps=facts["action_manifest"],redirect_limit=0),step_bindings=facts["step_bindings"],unable_reason=None)
    mock=mock_openai([candidate]);generator=BrowserPlanGenerator(OpenAIModelAdapter(client=mock.client),record.settings)
    response=generator.generate(generator.prepare_system(record,obs,item.test,item.approval))
    output=validate_system_candidate(record,obs,item.test,item.approval,response.parsed_output,record.scope.policy)
    assert output.plan.steps==record.constraints.action_manifest and len(mock.calls)==1
    from qa_sentinel.domain.browser_generation import BrowserPlanOutput
    for action in [{"action":"CLICK","locator":LOC.model_dump()}, {"action":"NAVIGATE","path":"/invented"},
        {"action":"ASSERT_TEXT","locator":{**LOC.model_dump(),"name":"Invented"},"text":"Welcome"},
        {"action":"FILL","locator":LOC.model_dump(),"value":"invented"},
        {"action":"ASSERT_TEXT","locator":LOC.model_dump(),"text":"weaker"}]:
        value=output.model_dump(mode="json");value["plan"]["steps"][1]=action
        with pytest.raises((ValueError,GroundingLimitation)):validate_system_candidate(record,obs,item.test,item.approval,BrowserPlanOutput.model_validate(value),record.scope.policy)
    stale=observation(record.scope)
    with pytest.raises(GroundingLimitation):generator.prepare_system(record,stale,item.test,item.approval)
    assert rows(data[2])==(0,0,0,0)


def test_grounding_history_and_observations_are_immutable(grounding):
    data,prep,_,_=grounding;record=ground(data,prep);engine=data[2]
    for sql in ["UPDATE browser_groundings SET status=status","DELETE FROM browser_groundings", "UPDATE browser_grounding_observations SET payload=payload","DELETE FROM browser_grounding_observations"]:
        with pytest.raises(IntegrityError),engine.begin() as db:db.execute(text(sql))
    with pytest.raises(RuntimeError,match="cannot erase" ):command.downgrade(data[3],"0016")
    assert data[0].get_browser_grounding(data[4].id,data[5].id,record.id)==record
    with engine.connect() as db:assert db.execute(text("PRAGMA foreign_key_check")).all()==[]


def test_migration_preserves_preparation_history_and_reupgrade(source_free):
    data=source_free;approve_source_free(data);prep=prepare(data)
    command.downgrade(data[3],"0016")
    assert "browser_groundings" not in inspect(data[2]).get_table_names()
    assert data[0].get_browser_preparation(data[4].id,data[5].id,prep.id).selection_hash==prep.selection_hash
    command.upgrade(data[3],"head");command.check(data[3])
    command.downgrade(data[3],"0016");command.upgrade(data[3],"head")
    assert data[0].get_browser_preparation(data[4].id,data[5].id,prep.id)==prep


@pytest.mark.parametrize("kind",["elements","text","title","hash","time","scope","paths"])
def test_observation_bounds_and_canonical_hash_reject(kind,grounding):
    data,prep,_,observer=grounding;result=ground(data,prep)
    obs=data[0].get_browser_grounding_observation(data[4].id,data[5].id,result.observation_id)
    value=obs.model_dump(mode="json")
    if kind=="elements":value["elements"]*=81
    elif kind=="text":value["elements"][0]["text"]="x"*513
    elif kind=="title":value["title"]="x"*513
    elif kind=="hash":value["observation_hash"]="0"*64
    elif kind=="time":value["finished_at"]=(obs.started_at+timedelta(seconds=26)).isoformat()
    elif kind=="scope":value["scope"]["target_hash"]="0"*64
    else:value["paths"]*=21
    with pytest.raises((ValueError,GroundingLimitation)):BrowserGroundingObservation.model_validate(value)


@pytest.fixture
def observation_site():
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            seen.append(self.path)
            body="<h1>Welcome</h1><button>Continue</button><a href='/next'>Next</a><input aria-label='Name' value='do-not-capture'>"
            if self.path=="/duplicates":body="<h1>Welcome</h1><button>Continue</button><button>Continue</button>"
            elif self.path=="/sensitive-control":body="<h1>Welcome</h1><input type='password' aria-label='Password' value='never-persist-this'>"
            elif self.path=="/unsafe":body="<h1>Welcome</h1><a href='http://127.0.0.1:1/private'>Escape</a>"
            elif self.path=="/unsupported-control":body="<h1>Welcome</h1><input type='file' aria-label='Upload'>"
            elif self.path=="/many":body="<h1>Welcome</h1>"+"<button>Continue</button>"*81
            elif self.path=="/paths":body="<h1>Welcome</h1>"+''.join(f"<a href='/next{i}'>Next {i}</a>" for i in range(21))
            elif self.path=="/sensitive-text":body="<h1>sk-sensitive-synthetic-value</h1>"
            elif self.path=="/subresource":body="<h1>Welcome</h1><img src='http://127.0.0.1:1/private'>"
            elif self.path=="/redirect":
                self.send_response(302);self.send_header("Location","/");self.send_header("Content-Length","0");self.end_headers();return
            raw=body.encode();self.send_response(200)
            if self.path=="/stateful":self.send_header("Set-Cookie","session=never-persist-this")
            self.send_header("Content-Type","text/html");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f"http://127.0.0.1:{server.server_port}",seen
    finally:server.shutdown();server.server_close();thread.join(timeout=2)


def local_active(data,site,*,path="/",action="Open the public page",expected="Welcome"):
    app,_,_,_,p,c,*_=data
    app._browser_observer=PlaywrightBrowserObserver(trusted_local_origin=site[0])
    value=case("LOCAL");value.update(title="Public page",preconditions=[],steps=[dict(index=1,action=action,expected=expected)],overall_expected_result=expected,required_evidence=["Literal assertion"])
    app.import_campaign_tests(p.id,c.id,name="Local test",format="CSV",content=csv_text([value]))
    test=next(t for t in app.list_campaign_test_specifications(p.id,c.id).items if t.key=="LOCAL")
    app.review_source_free_campaign_test(p.id,c.id,test.id,reviewer_label="qa")
    target=app.create_target(p.id,name="Disposable WEB",environment="LOCAL",configuration={"base_url":site[0]+path})
    app.associate_campaign_target(p.id,c.id,target_id=target.id)
    prep=stored(prepare(data,ids=[test.id]));prep=transition(data[1],prep,"START")
    return transition(data[1],prep,"START_ITEM",item_id=prep.items[0].id)


@pytest.mark.parametrize("path,operation,element,status,reason",[
    ("/","NAVIGATE",None,"GROUNDED",None),
    ("/","CLICK","Continue","GROUNDED",None),
    ("/","CLICK","Next","GROUNDED",None),
    ("/","FILL","Name","GROUNDED",None),
    ("/duplicates","CLICK","Continue","NEEDS_ATTENTION","AMBIGUOUS_TARGET"),
    ("/","CLICK","Missing","NEEDS_ATTENTION","GROUNDING_UNAVAILABLE"),
    ("/unsafe","CLICK","Escape","NEEDS_ATTENTION","POLICY_REJECTED"),
    ("/sensitive-control","FILL","Password","NEEDS_ATTENTION","UNSUPPORTED_BEHAVIOR"),
    ("/unsupported-control","NAVIGATE",None,"NEEDS_ATTENTION","UNSUPPORTED_BEHAVIOR"),
    ("/many","NAVIGATE",None,"NEEDS_ATTENTION","OBSERVATION_LIMIT"),
    ("/paths","NAVIGATE",None,"NEEDS_ATTENTION","OBSERVATION_LIMIT"),
    ("/sensitive-text","NAVIGATE",None,"NEEDS_ATTENTION","UNSUPPORTED_BEHAVIOR"),
    ("/stateful","NAVIGATE",None,"NEEDS_ATTENTION","POLICY_REJECTED"),
    ("/subresource","NAVIGATE",None,"NEEDS_ATTENTION","POLICY_REJECTED"),
    ("/redirect","NAVIGATE",None,"GROUNDED",None),
])
def test_real_chromium_observation_and_reference_grounding(source_free,mock_openai,observation_site,path,operation,element,status,reason):
    data=source_free;app=data[0]
    action='Fill "Ada" into '+element if operation=="FILL" else 'Click '+element if operation=="CLICK" else "Open the public page"
    def choose(request):
        context=json.loads(request["input"][0]["content"]);value=output_for(context);obs=context["observation"]
        assert "do-not-capture" not in json.dumps(context) and "never-persist-this" not in json.dumps(context)
        assert "<h1>" not in json.dumps(context)
        if operation!="NAVIGATE":
            candidate=next((e for e in obs["elements"] if e["name"]==element),None)
            if candidate is None:
                value.update(disposition="CANNOT_GROUND",steps=[],reason="GROUNDING_UNAVAILABLE",affected_step=1);return value
            value["steps"][0]["operations"].append(dict(action=operation,element_ref=candidate["ref"],path_ref=None,value_ref="v1" if operation=="FILL" else None))
        return value
    mock=mock_openai([choose]);app._browser_grounding_reasoner=BrowserGroundingReasoner(OpenAIModelAdapter(client=mock.client),ModelSettings(model="configured-model"))
    prep=local_active(data,observation_site,path=path,action=action);result=ground(data,prep)
    assert (result.status,result.reason)==(status,reason), result.browser_error_code
    assert len(mock.calls)==(1 if result.observation_id else 0)
    assert rows(data[2])==(0,0,0,0)
    if result.observation_id:
        obs=app.get_browser_grounding_observation(data[4].id,data[5].id,result.observation_id)
        assert obs.runtime_identity.engine=="CHROMIUM"
        assert "do-not-capture" not in obs.model_dump_json() and "never-persist-this" not in obs.model_dump_json()
        if path=="/":assert any(p.path=="/next" and p.source=="LINK" for p in obs.paths)
    if path=="/sensitive-control":assert not observation_site[1]  # Test secret preflight precedes target access.
    elif path in {"/","/duplicates","/unsafe"}:assert set(observation_site[1]) <= {path,"/favicon.ico"}  # Inspection never clicks/fills.


@pytest.mark.parametrize("kind",["aggregate","bytes","negative_text","selector","path","secret"])
def test_structured_observation_cannot_bypass_bounds_or_safety(grounding,kind):
    data,prep,_,_=grounding;record=ground(data,prep)
    obs=data[0].get_browser_grounding_observation(data[4].id,data[5].id,record.observation_id)
    value=obs.model_dump(mode="json")
    if kind in {"aggregate","bytes"}:
        name="x"*256 if kind=="aggregate" else "\U0001f600"*64
        text_value="x"*512 if kind=="aggregate" else "\U0001f600"*136
        value["elements"]=[dict(ref="e"+str(i),role="heading",name=name,text=text_value,visible=True,enabled=True,sensitive=False,blocked_destination=False,
            locator=dict(strategy="ROLE",role="heading",name=name,exact=True),matches=80,path_ref=None) for i in range(1,81)]
    elif kind=="negative_text":value["elements"][0]["text"]="x"*513
    elif kind=="selector":value["elements"][0]["locator"]={"strategy":"CSS","value":"#invented"}
    elif kind=="path":value["paths"][0]["path"]="//other.invalid/secret"
    else:value["elements"][0]["text"]="sk-sensitive-synthetic-value"
    value["observation_hash"]=digest({k:v for k,v in value.items() if k!="observation_hash"})
    with pytest.raises((ValueError,GroundingLimitation)):BrowserGroundingObservation.model_validate(value)


def test_context_and_output_fail_honestly_without_truncation(grounding,monkeypatch):
    data,prep,mock,observer=grounding
    import qa_sentinel.agents.browser_grounding as module
    original=module.test_intent
    def oversized(*args):return {**original(*args),"large_required_context":"x"*60000}
    import qa_sentinel.application.browser_grounding as application_module
    monkeypatch.setattr(application_module,"test_intent",oversized)
    result=ground(data,prep)
    assert result.status=="NEEDS_ATTENTION" and result.reason=="CONTEXT_LIMIT" and not mock.calls
    value=output_for({"scope":result.scope.model_dump(mode="json"),"observation":data[0].get_browser_grounding_observation(data[4].id,data[5].id,result.observation_id).model_dump(mode="json")})
    value["steps"]*=21
    with pytest.raises(ValidationError):GroundingOutput.model_validate(value)


def test_completion_persistence_failure_is_not_replayed(grounding,monkeypatch):
    data,prep,mock,observer=grounding
    from qa_sentinel.persistence.browser_groundings import BrowserGroundingRepository
    def fail(*args):raise RuntimeError("sensitive synthetic internals")
    monkeypatch.setattr(BrowserGroundingRepository,"finish",fail)
    with pytest.raises(ApplicationError,match="PERSISTENCE_ERROR"):ground(data,prep)
    with pytest.raises(ApplicationError,match="GROUNDING_RECONCILIATION_REQUIRED"):ground(data,prep)
    assert len(mock.calls)==len(observer.calls)==1
    with data[2].connect() as db:
        assert db.scalar(text("SELECT status FROM browser_groundings"))=="STARTED"
        assert db.scalar(text("SELECT count(*) FROM browser_grounding_observations"))==1


@pytest.mark.parametrize("secret",['Fill "sk-sensitive-value" into Name','Fill "bearer abc" into Name','Authenticate with credentials','Enter OTP','Set cookie state'])
def test_secret_intent_never_reaches_browser_or_provider(source_free,mock_openai,secret):
    data=source_free;app=data[0];p,c=data[4:6]
    value=case("SENSITIVE");value.update(title="Sensitive intent",preconditions=[],steps=[dict(index=1,action=secret,expected="Welcome")],overall_expected_result="Welcome",required_evidence=["Literal assertion"])
    app.import_campaign_tests(p.id,c.id,name="Test intent",format="CSV",content=csv_text([value]))
    spec=next(t for t in app.list_campaign_test_specifications(p.id,c.id).items if t.key=="SENSITIVE")
    app.review_source_free_campaign_test(p.id,c.id,spec.id,reviewer_label="qa")
    mock=mock_openai([model_output]);observer=Observer();app._browser_observer=observer
    app._browser_grounding_reasoner=BrowserGroundingReasoner(OpenAIModelAdapter(client=mock.client),ModelSettings(model="configured-model"))
    prep=active(data,ids=[spec.id]);result=ground(data,prep)
    assert (result.status,result.reason)==("NEEDS_ATTENTION","UNSUPPORTED_BEHAVIOR")
    assert not mock.calls and not observer.calls and secret not in result.model_dump_json()


def test_password_control_values_are_not_observed(source_free,mock_openai,observation_site):
    data=source_free;app=data[0];mock=mock_openai([model_output])
    app._browser_grounding_reasoner=BrowserGroundingReasoner(OpenAIModelAdapter(client=mock.client),ModelSettings(model="configured-model"))
    prep=local_active(data,observation_site,path="/sensitive-control")
    result=ground(data,prep)
    assert result.status=="GROUNDED"
    obs=app.get_browser_grounding_observation(data[4].id,data[5].id,result.observation_id)
    control=next(e for e in obs.elements if e.role=="textbox")
    assert control.sensitive and control.name is None and control.locator is None and not control.text
    assert "never-persist-this" not in obs.model_dump_json()
    from qa_sentinel.agents.browser_grounding import validate_grounding
    wrong=result.output.model_dump(mode="json");wrong["steps"][0]["assertion"]["element_ref"]=control.ref
    with pytest.raises(GroundingLimitation,match="UNSUPPORTED_BEHAVIOR"):
        validate_grounding(result,obs,prep.items[0].test,prep.items[0].approval,GroundingOutput.model_validate(wrong))


def test_private_target_remains_blocked_without_trusted_fixture(grounding):
    data,prep,_,_=grounding;record=ground(data,prep)
    value=record.scope.model_dump(mode="json");value["target"]["base_url"]="http://127.0.0.1:1234/"
    value["target_hash"]=digest(value["target"])
    scope=GroundingScope.model_validate(value)
    with pytest.raises(ValueError):PlaywrightBrowserObserver().observe(scope)


def test_active_scope_cannot_be_substituted_in_repository(grounding):
    data,prep,_,_=grounding;record=ground(data,prep)
    for field in ("item_id","attempt_id","preparation_id","test_id","approval_hash","test_hash"):
        value=record.scope.model_dump(mode="json");value[field]="0"*64 if field.endswith("hash") else str(uuid4())
        wrong=GroundingScope.model_validate(value)
        with pytest.raises(GroundingLimitation),UnitOfWork(data[1]) as uow:uow.browser_groundings.active_item(wrong)


def test_storage_guards_reject_forged_completion_timestamp(grounding):
    data,prep,mock,observer=grounding
    def crash(scope):raise KeyboardInterrupt()
    observer.build=crash
    with pytest.raises(KeyboardInterrupt):ground(data,prep)
    with data[2].connect() as db:payload=json.loads(db.scalar(text("SELECT payload FROM browser_groundings")))
    for finished in ("invalid", "2000-01-01T00:00:00Z",None):
        wrong={**payload,"status":"NEEDS_ATTENTION","reason":"GROUNDING_UNAVAILABLE","finished_at":finished}
        with pytest.raises(IntegrityError),data[2].begin() as db:
            db.execute(text("UPDATE browser_groundings SET status='NEEDS_ATTENTION',payload=:value"),{"value":json.dumps(wrong)})
    assert not mock.calls


@pytest.mark.parametrize("wrong",[None,"control","value","order"])
def test_multistep_binding_and_literal_values_are_not_interchangeable(source_free,mock_openai,wrong):
    from qa_sentinel.domain.browser_execution import LabelLocator
    data=source_free;app=data[0];p,c=data[4:6]
    value=case("STEPS");value.update(title="Two explicit actions",preconditions=[],steps=[
        dict(index=1,action='Fill "Name" into City',expected="Welcome"),dict(index=2,action='Click Continue',expected="Welcome")],
        overall_expected_result="Welcome",required_evidence=["Two assertions"])
    app.import_campaign_tests(p.id,c.id,name="Steps",format="CSV",content=csv_text([value]))
    spec=next(t for t in app.list_campaign_test_specifications(p.id,c.id).items if t.key=="STEPS")
    app.review_source_free_campaign_test(p.id,c.id,spec.id,reviewer_label="qa")
    elements=(ObservedElement(ref="e1",role="heading",name="Welcome",locator=LOC,matches=1),
        ObservedElement(ref="e2",role="button",name="Continue",locator=RoleLocator(strategy="ROLE",role="button",name="Continue",exact=True),matches=1),
        ObservedElement(ref="e3",role="textbox",name="Name",locator=LabelLocator(strategy="LABEL",value="Name",exact=True),matches=1),
        ObservedElement(ref="e4",role="textbox",name="City",locator=LabelLocator(strategy="LABEL",value="City",exact=True),matches=1))
    app._browser_observer=Observer(lambda scope:observation(scope,elements=elements))
    def choose(request):
        value=model_output(request)
        value["steps"][0]["operations"].append(dict(action="FILL",element_ref="e3" if wrong=="control" else "e4",path_ref=None,value_ref="v2" if wrong=="value" else "v1"))
        value["steps"].append(dict(step_index=2,operations=[dict(action="CLICK",element_ref="e2",path_ref=None,value_ref=None)],assertion=dict(kind="TEXT",element_ref="e1",path_ref=None)))
        if wrong=="order":value["steps"].reverse()
        return value
    mock=mock_openai([choose]);app._browser_grounding_reasoner=BrowserGroundingReasoner(OpenAIModelAdapter(client=mock.client),ModelSettings(model="configured-model"))
    prep=active(data,ids=[spec.id]);result=ground(data,prep)
    assert result.status==("GROUNDED" if wrong is None else "NEEDS_ATTENTION")
    assert len(mock.calls)==1
    if wrong is None:
        assert result.constraints.action_manifest[1].value=="Name" and result.constraints.action_manifest[1].locator.value=="City"
        assert result.constraints.step_bindings==(1,1,1,2,2)
    assert rows(data[2])==(0,0,0,0)


def test_contract_name_in_ordinary_prose_does_not_bypass_secret_scan(source_free):
    from qa_sentinel.agents.browser_grounding import test_intent
    data=source_free;test=approve_source_free(data)[0]
    target=prepare(data).target_snapshot
    safe=type(test).model_validate({**test.model_dump(),"preconditions":['{"contract_version":"browser-facts-v1","legacy":"secret"}']})
    assert test_intent(safe,target)["preconditions"]==[]
    for field in ("title","preconditions","steps"):
        values=test.model_dump()
        if field=="preconditions":values[field]=['Ordinary "browser-facts-v1" secret']
        elif field=="steps":values[field]=[dict(index=1,action='Click "browser-facts-v1" sk-sensitive-value',expected="Welcome")]
        else:values[field]='"browser-facts-v1" secret'
        with pytest.raises(GroundingLimitation,match="UNSUPPORTED_BEHAVIOR"):test_intent(type(test).model_validate(values),target)
