"""Offline paging, scoped/stale selection and immutable result export regressions."""
import base64
import csv
from io import BytesIO, StringIO
from zipfile import ZipFile
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from qa_sentinel.api import create_api_app
from qa_sentinel.application import ApplicationError
from qa_sentinel.domain.campaign_review import content_hash
from qa_sentinel.domain.test_specification import CampaignTestSpecification, TestDesign as Design
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from test_campaign_review import review


def seed(review, count=24):
    app, factory, _, _, p, c, _, original = review
    original = app.get_campaign_test_specification(p.id,c.id,original.id)
    with UnitOfWork(factory) as uow:
        owner = uow.test_specifications.import_record(original.provenance.record_id)
        tests = [CampaignTestSpecification.model_validate({**original.model_dump(),
            "id":uuid4(),"key":f"PAGED_{i:03}","logical_key":f"PAGED-{i:03}",
            "title":f"Booking example {i:03}"}) for i in range(count)]
        for offset in range(0,len(tests),100):
            uow.test_specifications._add_specs(tests[offset:offset+100],owner)
        uow.commit()
    return tests


def path(review):
    return f"/api/v1/projects/{review[4].id}/campaigns/{review[5].id}"


@pytest.mark.parametrize("size", [10,20,50,100])
def test_bounded_pages_filter_search_and_clamp(review,size):
    seed(review)
    with TestClient(create_api_app(review[0])) as client:
        url=path(review)+"/test-design"
        default=client.get(url).json()
        assert default["page_size"]==10 and len(default["items"])==10 and default["total"]==25
        data=client.get(url,params={"page_size":size,"search":"Booking","status":"READY"}).json()
        assert data["total"]==24 and len(data["items"])==min(24,size)
        last=client.get(url,params={"page_size":size,"page":999}).json()
        assert last["page"]==last["total_pages"]
        if size==10:
            second=client.get(url,params={"page":2}).json()
            assert not {r["test"]["id"] for r in default["items"]}&{r["test"]["id"] for r in second["items"]}
        assert client.get(url,params={"status":"DRAFT"}).json()["total"]==0
        assert client.get(url,params={"search":"%"}).json()["total"]==0
        for invalid in [0,1,11,200,100000]: assert client.get(url,params={"page_size":invalid}).status_code==422
        assert client.get(url,params={"page":0}).status_code==422
        assert client.get(url.replace(str(review[4].id),str(uuid4()))).status_code==404


def test_all_matching_is_bounded_descriptor_and_explicit_approval(review):
    tests=seed(review)
    app=review[0]
    with TestClient(create_api_app(app)) as client:
        selection={"criteria":{"search":"Booking", "status":"READY"}}
        response=client.post(path(review)+"/test-design/selection",json=selection)
        summary=response.json()
        assert response.status_code==200 and summary["matched"]==summary["eligible"]==24
        assert set(summary)=={"fingerprint","matched","eligible"}  # no materialized IDs
        assert all(t.review_status=="READY_FOR_REVIEW" for t in app.list_campaign_test_specifications(review[4].id,review[5].id).items)
        result=client.post(path(review)+"/test-design/approval",json={"selection":selection,"fingerprint":summary["fingerprint"],"reviewer_label":"human"})
        assert result.status_code==200,result.text
        assert result.json()=={"matched":24,"approved":24,"skipped":0}
        assert app.get_campaign_test_specification(review[4].id,review[5].id,review[7].id).review_status=="READY_FOR_REVIEW"
        assert client.post(path(review)+"/test-design/approval",json={"selection":selection,"fingerprint":summary["fingerprint"],"reviewer_label":"human"}).status_code==409


def test_page_selection_is_version_pinned_and_cannot_cross_scope(review):
    tests=seed(review,3);app=review[0];p,c=review[4:6]
    selected=tests[:2]
    selection={"criteria":{},"ids":[str(t.id) for t in selected],"expected_versions":{str(t.id):f"{content_hash(t)}:{t.review_status}" for t in selected}}
    summary=app.test_design_selection(p.id,c.id,selection=selection)
    app.review_campaign_test_specification(p.id,c.id,selected[0].id,reviewer_label="another-human")
    with pytest.raises(ApplicationError,match="REVIEW_CONFLICT"):
        app.test_design_selection(p.id,c.id,selection=selection,fingerprint=summary.fingerprint,reviewer_label="human")
    assert app.get_campaign_test_specification(p.id,c.id,selected[1].id).review_status=="READY_FOR_REVIEW"
    other=app.create_campaign(p.id,name="Other")
    with pytest.raises(ApplicationError):app.test_design_selection(p.id,other.id,selection=selection)
    with pytest.raises(ApplicationError):app.test_design_selection(p.id,c.id,selection={"ids":[str(uuid4())]})


def test_matching_new_version_race_rejects_before_any_write(review):
    tests=seed(review,3);app=review[0];p,c=review[4:6]
    selection={"criteria":{"search":"Booking"}}
    summary=app.test_design_selection(p.id,c.id,selection=selection)
    t=tests[0];design={k:v for k,v in t.model_dump().items() if k in Design.model_fields}
    design["title"]="Booking changed"
    app.edit_campaign_test(p.id,c.id,t.id,design=design,previous_hash=content_hash(t),reviewer_label="human",note="Supported fact")
    with pytest.raises(ApplicationError,match="REVIEW_CONFLICT"):
        app.test_design_selection(p.id,c.id,selection=selection,fingerprint=summary.fingerprint,reviewer_label="human")
    assert app.get_campaign_test_specification(p.id,c.id,tests[1].id).review_status=="READY_FOR_REVIEW"


def test_mixed_selection_skips_ineligible_and_max_matches_fails_closed(review,monkeypatch):
    seed(review,3);app=review[0];p,c=review[4:6]
    app.review_campaign_test_specification(p.id,c.id,review[7].id,reviewer_label="human")
    summary=app.test_design_selection(p.id,c.id,selection={})
    assert (summary.matched,summary.eligible)==(4,3)
    result=app.test_design_selection(p.id,c.id,selection={},fingerprint=summary.fingerprint,reviewer_label="human")
    assert result==dict(matched=4,approved=3,skipped=1)
    monkeypatch.setattr("qa_sentinel.application.test_design.MAX_MATCHES",2)
    with pytest.raises(ApplicationError,match="INVALID_LIST_LIMIT"):app.test_design_selection(p.id,c.id,selection={})


@pytest.mark.parametrize("format",["CSV","XLSX"])
def test_export_only_immutable_run_data_and_truthful_fail_evidence(review,format):
    tests=seed(review,2);app=review[0];p,c=review[4:6]
    app.review_campaign_requirement(p.id,c.id,review[6].id,reviewer_label="human")
    summary=app.test_design_selection(p.id,c.id,selection={})
    app.test_design_selection(p.id,c.id,selection={},fingerprint=summary.fingerprint,reviewer_label="human")
    run=app.create_qa_run(p.id,c.id,idempotency_key="export",test_specification_ids=[t.id for t in tests]+[review[7].id])
    app.start_qa_run(p.id,c.id,run.id)
    t=tests[0];design={k:v for k,v in t.model_dump().items() if k in Design.model_fields};design["title"]="MUTABLE LATER TITLE"
    app.edit_campaign_test(p.id,c.id,t.id,design=design,previous_hash=content_hash(t),reviewer_label="human",note="Later facts")
    export=app.export_qa_run(p.id,c.id,run.id,format=format);raw=base64.b64decode(export["content_base64"])
    assert export["count"]==3
    if format=="CSV":
        rows=list(csv.reader(StringIO(raw.decode("utf-8-sig"))))
        assert [r[6] for r in rows[1:]]==["PASS","FAIL","PASS"]
        assert all(r[5]=="COMPLETED" and r[9]=="1" and r[13]=="COMPLETED" and r[14]=="FAIL" for r in rows[1:])
        assert all("MUTABLE LATER" not in r[4] for r in rows[1:])
    else:
        with ZipFile(BytesIO(raw)) as z:
            xml=z.read("xl/worksheets/sheet1.xml")
            assert b"MUTABLE LATER" not in xml and b"FAIL" in xml and b"PASS" in xml and b"<f>" not in xml
    with TestClient(create_api_app(app)) as client:
        assert client.get(path(review)+f"/runs/{run.id}/export?format={format}").status_code==200
        assert client.get(path(review).replace(str(p.id),str(uuid4()))+f"/runs/{run.id}/export?format={format}").status_code==404
        other=app.create_campaign(p.id,name="Other")
        assert client.get(path(review).replace(str(c.id),str(other.id))+f"/runs/{run.id}/export?format={format}").status_code==409


@pytest.mark.parametrize("format",["CSV","XLSX"])
def test_run_export_formula_safety_and_unstarted_missing_evidence(review,format):
    from xml.etree import ElementTree as ET
    app,factory,_,_,p,c,req,original=review
    original=app.get_campaign_test_specification(p.id,c.id,original.id)
    injected=CampaignTestSpecification.model_validate({**original.model_dump(),"id":uuid4(),"key":"FORMULA", "logical_key":"FORMULA", "title":"=SUM(1,2)"})
    with UnitOfWork(factory) as uow:
        owner=uow.test_specifications.import_record(original.provenance.record_id)
        uow.test_specifications._add_specs([injected],owner);uow.commit()
    app.review_campaign_requirement(p.id,c.id,req.id,reviewer_label="human")
    app.review_campaign_test_specification(p.id,c.id,injected.id,reviewer_label="human")
    run=app.create_qa_run(p.id,c.id,idempotency_key="formula",test_specification_ids=[injected.id])
    raw=base64.b64decode(app.export_qa_run(p.id,c.id,run.id,format=format)["content_base64"])
    if format=="CSV":
        row=list(csv.reader(StringIO(raw.decode("utf-8-sig"))))[1]
        assert row[4]=="'=SUM(1,2)" and row[5:7]==["NOT_STARTED","NOT_EVALUATED"]
        assert row[9]=="0" and row[11:13]==["",""]
    else:
        with ZipFile(BytesIO(raw)) as z:
            root=ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
            assert not root.findall(".//{*}f")
            assert all(cell.attrib["t"]=="inlineStr" for cell in root.findall(".//{*}c"))
            assert "=SUM(1,2)" in [t.text for t in root.findall(".//{*}t")]


def test_selection_over_pages_streams_in_100_record_batches_and_preserves_scopes(review):
    from sqlalchemy import event
    seed(review,205);app,factory,engine,_,p,c,_,_=review
    queries=[]
    def observe(conn,cursor,statement,parameters,*args):
        if statement.lstrip().upper().startswith("SELECT") and "campaign_test_specifications" in statement:
            queries.append((statement,parameters))
    event.listen(engine,"before_cursor_execute",observe)
    try:
        summary=app.test_design_selection(p.id,c.id,selection={"criteria":{"search":"Booking"}})
    finally:event.remove(engine,"before_cursor_execute",observe)
    assert summary.matched==summary.eligible==205
    assert len(queries)<12 and all("LIMIT" in sql for sql,params in queries)
    other=app.create_campaign(p.id,name="Other")
    assert app.test_design_selection(p.id,other.id,selection={}).matched==0
    with TestClient(create_api_app(app)) as client:
        assert client.post(path(review)+"/test-design/selection",content=b"x"*32769,headers={"Content-Type":"application/json"}).status_code==413
        assert client.post(path(review)+"/test-design/approval",content=b"x"*32769,headers={"Content-Type":"application/json"}).status_code==413
