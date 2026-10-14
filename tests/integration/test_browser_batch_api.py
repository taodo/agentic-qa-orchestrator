"""Checkpoint D: trusted-local explicit submission/review and bounded passive reads."""
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from qa_sentinel.api import create_api_app
from qa_sentinel.host.browser_http import add_browser_http
from qa_sentinel.domain.campaign_review import content_hash
from test_browser_batches import batch
from test_browser_grounding import source_free
from test_campaign_test_specifications import case,csv_text

@pytest.fixture
def http(batch,monkeypatch):
    app=batch[0][0];p,c=batch[0][4:6]
    app._browser_plan_generator=object()
    monkeypatch.setenv("OPENAI_API_KEY","SYNTHETIC_NOT_A_SECRET")
    api=create_api_app(app)
    add_browser_http(api,SimpleNamespace(host="127.0.0.1",port=8000,projects=[SimpleNamespace(key=p.key)]))
    with TestClient(api,base_url="http://127.0.0.1:8000",client=("127.0.0.1",123),headers={"origin":"http://127.0.0.1:8000"}) as client:
        yield client,f"/api/v1/projects/{p.id}/campaigns/{c.id}/browser"


def test_normal_local_submission_is_durable_inert_and_results_are_whole_batch(batch,http):
    client,base=http;data,specs,mock,runtime,observer=batch;app=data[0];p,c=data[4:6]
    assert client.get(base+"/capability").json()["automatic"]=="AVAILABLE"
    body=dict(idempotency_key="normal",test_specification_ids=[str(t.id) for t in specs],browser_mode="HEADLESS")
    response=client.post(base+"/batches",json=body)
    assert response.status_code==201,response.text
    view=response.json();assert view["selected_count"]==3 and not mock.calls and not observer.calls and not runtime.calls
    assert client.post(base+"/batches",json=body).json()==view
    app.execute_browser_batch(p.id,c.id,view["id"])
    done=client.get(base+"/batches/"+view["id"]).json()
    assert [t["outcome"] for t in done["items"]["items"]]==["FAIL","PASS","NEEDS_ATTENTION"]
    assert done["items"]["items"][-1]["hint"] and done["items"]["items"][-1]["affected_step"]==1
    assert done["items"]["items"][0]["evidence_count"]==1
    assert done["items"]["items"][0]["evidence"]["items"][0]["summary"]
    before=(len(mock.calls),len(observer.calls),len(runtime.calls))
    assert client.get(base+"/batches?limit=1").json()["total_returned"]==1
    page=client.get(base+"/batches/"+view["id"]+"?limit=1").json()["items"]
    assert page["truncated"] and page["total_returned"]==1
    assert client.get(base+"/batches?limit=21").status_code==422
    assert client.get(base+"/batches/"+view["id"]+"?limit=101").status_code==422
    assert client.get(base.replace(str(c.id),str(uuid4()))+"/batches/"+view["id"]).status_code==404
    assert (len(mock.calls),len(observer.calls),len(runtime.calls))==before
    assert "SYNTHETIC_NOT_A_SECRET" not in response.text+str(done)
    assert "metadata" not in str(done) and "observation" not in done


def test_source_free_human_review_and_atomic_stale_hash_protection(batch,http):
    client,base=http;data,_,mock,runtime,observer=batch;app=data[0];p,c=data[4:6]
    values=[]
    for key in ("FIRST","SECOND"):
        value=case(key);value.update(preconditions=[],steps=[dict(index=1,action="Open page",expected="Welcome")],overall_expected_result="Welcome",required_evidence=["Heading"]);values.append(value)
    app.import_campaign_tests(p.id,c.id,name="No Specification",format="CSV",content=csv_text(values))
    tests=[t for t in app.list_campaign_test_specifications(p.id,c.id).items if t.key in {"FIRST","SECOND"}]
    body=dict(test_ids=[str(t.id) for t in tests],expected_hashes={str(t.id):content_hash(t) for t in tests},reviewer_label="human")
    bad={**body,"expected_hashes":{**body["expected_hashes"],str(tests[-1].id):"f"*64}}
    assert client.post(base+"/tests/approve-selection",json=bad).status_code==409
    assert all(app.get_campaign_test_specification(p.id,c.id,t.id).review_status!="APPROVED" for t in tests)
    result=client.post(base+"/tests/approve-selection",json=body)
    assert result.status_code==200,result.text
    assert result.json()["approved"]==2
    assert not mock.calls and not runtime.calls and not observer.calls


@pytest.mark.parametrize("attack",["origin","host","extra-plan"])
def test_local_batch_security_rejects_without_side_effects(batch,http,attack):
    client,base=http;data,specs,mock,runtime,observer=batch
    body=dict(idempotency_key="attack",test_specification_ids=[str(specs[0].id)],browser_mode="HEADLESS")
    headers={}
    if attack=="origin":headers["origin"]="http://evil.invalid"
    if attack=="host":headers["host"]="evil.invalid"
    if attack=="extra-plan":body["plan"]={"script":"arbitrary"}
    assert client.post(base+"/batches",json=body,headers=headers).status_code in {403,422}
    assert not mock.calls and not runtime.calls and not observer.calls


def test_public_composition_does_not_mount_real_batch_or_review(batch):
    data,specs,mock,runtime,observer=batch;app=data[0];p,c=data[4:6]
    with TestClient(create_api_app(app)) as client:
        base=f"/api/v1/projects/{p.id}/campaigns/{c.id}/browser"
        assert client.get(base+"/capability").json()["automatic"]=="UNAVAILABLE"
        for path in ("/batches",f"/tests/{specs[0].id}/review"):
            assert client.post(base+path,json={}).status_code==404
    assert not mock.calls and not runtime.calls and not observer.calls


def test_bulk_review_body_has_scoped_bounded_capacity_for_500_hashes(batch,http):
    client,base=http
    ids=[str(uuid4()) for _ in range(500)]
    body=dict(test_ids=ids,expected_hashes={id:"a"*64 for id in ids},reviewer_label="human")
    # A semantic not-found is expected, not a transport limit or external execution.
    response=client.post(base+"/tests/approve-selection",json=body)
    assert response.status_code==404,response.text
    assert client.post(base+"/tests/approve-selection",content=b"x"*131073,headers={"content-type":"application/json"}).status_code==413
    assert client.post(base+"/batches",content=b"x"*32769,headers={"content-type":"application/json"}).status_code==413


def test_source_free_bulk_review_skips_blocked_without_hiding_ready_work(batch,http):
    client,base=http;data,*_=batch;app=data[0];p,c=data[4:6]
    values=[]
    for key,refs in (("REVIEWABLE",[]),("BLOCKED-REF",["UNKNOWN"])):
        value=case(key,refs);value.update(title="Public page",preconditions=[],steps=[dict(index=1,action="Open page",expected="Welcome")],overall_expected_result="Welcome",required_evidence=["Heading"]);values.append(value)
    app.import_campaign_tests(p.id,c.id,name="Mixed review",format="CSV",content=csv_text(values))
    tests=[t for t in app.list_campaign_test_specifications(p.id,c.id).items if t.key in {"REVIEWABLE","BLOCKED-REF"}]
    response=client.post(base+"/tests/approve-selection",json=dict(test_ids=[str(t.id) for t in tests],expected_hashes={str(t.id):content_hash(t) for t in tests},reviewer_label="human"))
    assert response.status_code==200,response.text
    assert response.json()=={"matched":2,"approved":1,"skipped":1}
    assert all(app.get_campaign_test_specification(p.id,c.id,t.id).review_status==("APPROVED" if t.key=="REVIEWABLE" else "NEEDS_CLARIFICATION") for t in tests)


def test_single_source_free_review_hash_is_checked_inside_application(batch,http):
    client,base=http;data,*_=batch;app=data[0];p,c=data[4:6]
    value=case("PINNED");value.update(title="Public page",preconditions=[],steps=[dict(index=1,action="Open page",expected="Welcome")],overall_expected_result="Welcome",required_evidence=["Heading"])
    app.import_campaign_tests(p.id,c.id,name="Pinned human review",format="CSV",content=csv_text([value]))
    test=next(t for t in app.list_campaign_test_specifications(p.id,c.id).items if t.key=="PINNED")
    path=base+f"/tests/{test.id}/review"
    assert client.post(path,json=dict(reviewer_label="human",previous_hash="f"*64)).status_code==409
    assert app.get_campaign_test_specification(p.id,c.id,test.id).review_status!="APPROVED"
    response=client.post(path,json=dict(reviewer_label="human",previous_hash=content_hash(test)))
    assert response.status_code==200,response.text
    assert response.json()["review_status"]=="APPROVED"


def test_explicit_local_operator_provenance_is_truthful_immutable_and_not_identity(batch,http):
    from qa_sentinel.application.local_approval import LOCAL_OPERATOR_LABEL,LOCAL_OPERATOR_NOTE
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    client,base=http;data,*_=batch;app=data[0];p,c=data[4:6]
    value=case("LOCAL-PROVENANCE");value.update(preconditions=[],steps=[dict(index=1,action="Open page",expected="Welcome")],overall_expected_result="Welcome",required_evidence=["Heading"])
    app.import_campaign_tests(p.id,c.id,name="Local review",format="CSV",content=csv_text([value]))
    test=next(t for t in app.list_campaign_test_specifications(p.id,c.id).items if t.key==value["key"])
    body=dict(test_ids=[str(test.id)],expected_hashes={str(test.id):content_hash(test)},approval_provenance="LOCAL_OPERATOR")
    assert client.post(base+"/tests/approve-selection",json=body,headers={"origin":"http://evil.invalid"}).status_code==403
    assert client.post(base+"/tests/approve-selection",json={**body,"reviewer_label":"some-person"}).status_code==422
    assert client.post(base+"/tests/approve-selection",json={**body,"note":"custom identity"}).status_code==422
    assert client.post(base+"/tests/approve-selection",json={k:v for k,v in body.items() if k!="approval_provenance"}).status_code==422
    assert app.get_campaign_test_specification(p.id,c.id,test.id).review_status!="APPROVED"
    assert client.post(base+"/tests/approve-selection",json=body).json()["approved"]==1
    receipt=app.get_campaign_test_specification_review(p.id,c.id,test.id).evidence
    assert receipt.reviewer_label==LOCAL_OPERATOR_LABEL and receipt.note==LOCAL_OPERATOR_NOTE
    assert receipt.approved_at and receipt.content_hash==content_hash(test)
    from pydantic import ValidationError
    with pytest.raises(ValidationError):receipt.note="rewritten"
    replay=client.post(base+f"/tests/{test.id}/review",json={"reviewer_label":"different-human","note":"rewrite attempt"})
    assert replay.status_code==409
    assert app.get_campaign_test_specification_review(p.id,c.id,test.id).evidence==receipt


def test_local_finding_approval_uses_same_explicit_provenance_and_host_boundary(batch,http):
    from test_campaign_test_specifications import seed_requirement
    from qa_sentinel.application.local_approval import LOCAL_OPERATOR_LABEL
    client,base=http;data,*_=batch;app=data[0];p,c=data[4:6]
    requirement=seed_requirement(data[1],p,c,"LOCAL-FINDING")
    path=base+f"/requirements/{requirement.id}/review"
    body=dict(approval_provenance="LOCAL_OPERATOR")
    assert client.post(path,json=body,headers={"origin":"http://evil.invalid"}).status_code==403
    result=client.post(path,json=body);assert result.status_code==200,result.text
    assert result.json()["evidence"]["reviewer_label"]==LOCAL_OPERATOR_LABEL
    assert client.post(path,json=body).json()==result.json()
    assert not batch[2].calls and not batch[3].calls and not batch[4].calls


def test_local_design_approval_before_target_preserves_legacy_eligibility(batch,http):
    from test_campaign_test_specifications import seed_requirement
    from qa_sentinel.application.local_approval import LOCAL_OPERATOR_LABEL
    client,base=http;data,*_=batch;app=data[0];p,c=data[4:6]
    app.associate_campaign_target(p.id,c.id,target_id=None)
    capability=client.get(base+"/capability").json()
    assert capability["local_operator_review"]=="AVAILABLE" and capability["source_free_review"]=="UNAVAILABLE"
    requirement=seed_requirement(data[1],p,c,"BEFORE-TARGET")
    result=client.post(base+f"/requirements/{requirement.id}/review",json={"approval_provenance":"LOCAL_OPERATOR"})
    assert result.status_code==200
    value=case("TRACED-LOCAL",[requirement.key]);value.update(preconditions=[],steps=[dict(index=1,action="Open page",expected="Welcome")],overall_expected_result="Welcome",required_evidence=["Heading"])
    app.import_campaign_tests(p.id,c.id,name="Spec-based",format="CSV",content=csv_text([value]))
    test=next(t for t in app.list_campaign_test_specifications(p.id,c.id).items if t.key==value["key"])
    assert test.review_status=="READY_FOR_REVIEW"
    selection=dict(criteria=dict(search="",status="ALL"),ids=[str(test.id)],expected_versions={str(test.id):content_hash(test)+":"+test.review_status})
    summary=client.post(base.replace('/browser','')+'/test-design/selection',json=selection)
    assert summary.status_code==200
    body=dict(selection=selection,fingerprint=summary.json()["fingerprint"],approval_provenance="LOCAL_OPERATOR")
    assert client.post(base+'/test-design/approval',json=body,headers={"origin":"http://evil.invalid"}).status_code==403
    result=client.post(base+'/test-design/approval',json=body);assert result.status_code==200,result.text
    assert result.json()["approved"]==1
    assert app.get_campaign_test_specification_review(p.id,c.id,test.id).evidence.reviewer_label==LOCAL_OPERATOR_LABEL
    # The generic operator path does not acquire the browser/source-free approval exemption.
    value=case("UNTRACED-LOCAL");value.update(preconditions=[],steps=[dict(index=1,action="Open page",expected="Welcome")],overall_expected_result="Welcome",required_evidence=["Heading"])
    app.import_campaign_tests(p.id,c.id,name="Needs browser context",format="CSV",content=csv_text([value]))
    untraced=next(t for t in app.list_campaign_test_specifications(p.id,c.id).items if t.key==value["key"])
    result=client.post(base+f"/tests/{untraced.id}/operator-review",json={"approval_provenance":"LOCAL_OPERATOR"})
    assert result.status_code==409
    assert app.get_campaign_test_specification_review(p.id,c.id,untraced.id).evidence is None
    assert not batch[2].calls and not batch[3].calls and not batch[4].calls
