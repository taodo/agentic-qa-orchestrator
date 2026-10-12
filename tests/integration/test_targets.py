"""Targets, legacy migration, scoped APIs and sealed Run context. Offline only."""
from pathlib import Path
from uuid import uuid4
from alembic import command
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import pytest
from qa_sentinel.api import create_api_app
from qa_sentinel.application import QASentinelApplication, ProjectExecutionResolver, ApplicationError
from qa_sentinel.host.database import open_existing_database, SchemaNotReady, CURRENT_REVISION
from qa_sentinel.projects import ProjectRuntimeRegistry
from test_campaign_review import review, approve_all
from test_product_v2 import approve_selected
from test_host import config, offline


def make(app,p,url="https://staging.example.com"):
    return app.create_target(p.id,name="Staging",type="WEB",environment="STAGING",configuration={"base_url":url})


def test_crud_campaign_scope_multiple_targets_and_restart(review):
    app,factory,_,_,p,c,_,_=review
    assert app.get_campaign(p.id,c.id).target_id is None
    assert app.get_campaign_target(p.id,c.id) is None
    a=make(app,p);b=make(app,p,"https://example.com")
    assert app.list_targets(p.id,limit=1).truncated
    assert app.list_targets(p.id).items==tuple(sorted((a,b),key=lambda t:str(t.id)))
    other=app.create_project(key="other",name="Other")
    for action in (lambda:app.get_target(other.id,a.id),lambda:app.update_target(other.id,a.id,name="Wrong"),lambda:app.create_campaign(other.id,name="Wrong",target_id=a.id)):
        with pytest.raises(ApplicationError,match="TARGET_NOT_FOUND"):action()
    associated=app.associate_campaign_target(p.id,c.id,target_id=a.id)
    assert associated.target_id==a.id and associated.status=="DRAFT"
    app.update_campaign(p.id,c.id,name="Metadata only")
    assert app.get_campaign(p.id,c.id).target_id==a.id
    fresh=app.create_campaign(p.id,name="Explicit",target_id=b.id)
    restarted=QASentinelApplication(factory,ProjectExecutionResolver(ProjectRuntimeRegistry([]),[]))
    assert restarted.get_campaign_target(p.id,c.id)==a
    assert restarted.get_campaign(p.id,fresh.id).target_id==b.id
    assert {record.target_id for record in app.list_project_campaigns(p.id).items}=={a.id,b.id}
    app.associate_campaign_target(p.id,c.id,target_id=None)
    assert app.get_campaign_target(p.id,c.id) is None


def test_run_snapshot_retains_old_target_and_synthetic_meaning(review):
    app,p,c,test=approve_selected(review)
    target=make(app,p)
    app.associate_campaign_target(p.id,c.id,target_id=target.id)
    before=app.create_qa_run(p.id,c.id,idempotency_key="before",test_specification_ids=[test.id])
    updated=app.update_target(p.id,target.id,name="Production",environment="PRODUCTION",configuration={"base_url":"https://example.com"})
    after=app.create_qa_run(p.id,c.id,idempotency_key="after",test_specification_ids=[test.id])
    assert before.target_snapshot.base_url=="https://staging.example.com"
    assert after.target_snapshot.base_url=="https://example.com" and after.target_snapshot.name=="Production"
    assert before.snapshot_hash!=after.snapshot_hash
    assert app.create_qa_run(p.id,c.id,idempotency_key="before",test_specification_ids=[test.id])==before
    app.start_qa_run(p.id,c.id,before.id)
    assert app.get_qa_run_results(p.id,c.id,before.id).run.target_snapshot==before.target_snapshot
    engine=review[2]
    with pytest.raises(IntegrityError):
        with engine.begin() as db:db.execute(text("UPDATE qa_runs SET target_snapshot=NULL WHERE id=:id"),{"id":str(before.id)})
    assert app.get_target(p.id,target.id)==updated


def test_0012_populated_upgrade_legacy_reopen_and_downgrade_guard(review):
    app,factory,engine,config,p,c,_,_=review
    approve_all(review)
    old=app.create_qa_run(p.id,c.id,idempotency_key="legacy")
    app.start_qa_run(p.id,c.id,old.id)
    old=app.get_qa_run(p.id,c.id,old.id)
    old_results=app.get_qa_run_results(p.id,c.id,old.id)
    command.downgrade(config,"0012")
    with engine.connect() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version"))=="0012"
        assert db.scalar(text("SELECT count(*) FROM qa_runs"))==1
    path=engine.url.database
    before_admission = Path(path).read_bytes()
    with pytest.raises(SchemaNotReady) as exc:open_existing_database(path)
    assert Path(path).read_bytes() == before_admission
    assert (exc.value.current,exc.value.required)==("0012","0013")
    command.upgrade(config,"head");command.check(config)
    assert ScriptDirectory.from_config(config).get_current_head()==CURRENT_REVISION=="0013"
    reopened,refactory=open_existing_database(path)
    try:
        resumed=QASentinelApplication(refactory,ProjectExecutionResolver(ProjectRuntimeRegistry([]),[]))
        assert resumed.get_campaign(p.id,c.id).target_id is None
        assert resumed.get_qa_run(p.id,c.id,old.id)==old
        assert resumed.get_qa_run_results(p.id,c.id,old.id)==old_results
        assert resumed.list_targets(p.id).items==()
        target=make(resumed,p)
        resumed.associate_campaign_target(p.id,c.id,target_id=target.id)
        new=resumed.create_qa_run(p.id,c.id,idempotency_key="with-target")
        assert new.target_snapshot.target_id==target.id
        assert resumed.get_qa_run(p.id,c.id,new.id).target_snapshot==new.target_snapshot
        with reopened.connect() as db:assert not db.exec_driver_sql("PRAGMA foreign_key_check").all()
        with pytest.raises(RuntimeError,match="cannot discard"):command.downgrade(config,"0012")
    finally:reopened.dispose()


def test_api_bounds_closed_configuration_and_zero_execution(review,monkeypatch):
    app,_,engine,_,p,c,_,_=review
    def forbidden(*args,**kwargs):raise AssertionError("No network/provider/executor from Target CRUD")
    import socket
    monkeypatch.setattr(socket,"getaddrinfo",forbidden)
    monkeypatch.setattr(socket,"create_connection",forbidden)
    monkeypatch.setattr(app,"start_qa_run",forbidden)
    base=f"/api/v1/projects/{p.id}"
    with TestClient(create_api_app(app)) as client:
        body={"name":"Site","type":"WEB","environment":"STAGING","configuration":{"base_url":"https://example.com"}}
        created=client.post(base+"/targets",json=body)
        assert created.status_code==201,created.text
        id=created.json()["id"]
        assert client.get(base+"/targets").json()["total_returned"]==1
        assert client.patch(base+f"/targets/{id}",json={"environment":"PRODUCTION"}).status_code==200
        assert client.put(base+f"/campaigns/{c.id}/target",json={"target_id":id}).status_code==200
        assert client.get(base+f"/campaigns/{c.id}/target").json()["id"]==id
        for malformed in [dict(body,type="API"),dict(body,environment="ANY"),dict(body,configuration={"base_url":"https://user:secret@example.com"})]:
            failed=client.post(base+"/targets",json=malformed);assert failed.status_code==422
            assert "secret" not in failed.text and "user:" not in failed.text
        for suffix,method in [("/targets","post"),(f"/targets/{id}","patch"),(f"/campaigns/{c.id}/target","put")]:
            assert getattr(client,method)(base+suffix,content="x"*8193,headers={"Content-Type":"application/json"}).status_code==413
        assert client.get(base+"/targets?limit=1000").status_code==422
        assert client.post(base+"/campaigns",json={"name":"Unicode metadata","objective":"界"*4000}).status_code==201
        assert client.get(base.replace(str(p.id),str(uuid4()))+f"/targets/{id}").status_code==404
    with engine.connect() as db:
        for table in ("tasks","execution_jobs","qa_runs"):
            assert db.scalar(text(f"SELECT count(*) FROM {table}"))==0



def test_empty_downgrade_reupgrade_fk_scope_and_safe_persistence(review,monkeypatch):
    app,factory,engine,config,p,c,_,_=review
    command.check(config);command.downgrade(config,"0012");command.upgrade(config,"head");command.check(config)
    other=app.create_project(key="foreign",name="Foreign")
    target=make(app,other)
    with pytest.raises(ApplicationError,match="TARGET_NOT_FOUND"):app.associate_campaign_target(p.id,c.id,target_id=target.id)
    with pytest.raises(IntegrityError):
        with engine.begin() as db:db.execute(text("INSERT INTO campaign_targets(campaign_id,project_id,target_id) VALUES (:c,:p,:t)"),{"c":str(c.id),"p":str(p.id),"t":str(target.id)})
    with engine.connect() as db:assert not db.exec_driver_sql("PRAGMA foreign_key_check").all()
    from qa_sentinel.persistence.targets import TargetRepository
    def failed(*args,**kwargs):raise RuntimeError("private filesystem/path/secret detail")
    monkeypatch.setattr(TargetRepository,"list",failed)
    with TestClient(create_api_app(app)) as client:
        response=client.get(f"/api/v1/projects/{p.id}/targets")
        assert response.status_code==500 and response.json()=={"error":{"code":"PERSISTENCE_ERROR","message":"Persistence operation failed"}}


def test_target_snapshot_is_hash_covered_and_legacy_hash_unchanged(review):
    from qa_sentinel.domain.qa_run import snapshot_fingerprint, PreparedQARun
    from qa_sentinel.persistence.unit_of_work import UnitOfWork
    from pydantic import ValidationError
    app,p,c,test=approve_selected(review)
    legacy=app.create_qa_run(p.id,c.id,idempotency_key="no-target",test_specification_ids=[test.id])
    target=make(app,p);app.associate_campaign_target(p.id,c.id,target_id=target.id)
    current=app.create_qa_run(p.id,c.id,idempotency_key="target",test_specification_ids=[test.id])
    with UnitOfWork(review[1]) as uow:
        old=uow.qa_runs.preparation(legacy);prepared=uow.qa_runs.preparation(current)
    assert snapshot_fingerprint(old.run.campaign_snapshot,old.requirements,old.tests,old.run.snapshot_version)==old.run.snapshot_hash
    values=prepared.model_dump();values["run"]["target_snapshot"]["base_url"]="https://changed.example.com"
    with pytest.raises(ValidationError,match="fingerprint"):PreparedQARun.model_validate(values)
    values=prepared.model_dump();values["run"]["target_snapshot"]["project_id"]=uuid4()
    with pytest.raises(ValidationError,match="ownership"):PreparedQARun.model_validate(values)


def test_target_routes_preserve_hosted_session_csrf_and_fake_only(config, monkeypatch):
    from test_hosted import hosted, login, csrf, USER, PASSWORD, SECRET
    from qa_sentinel.host.web import create_host_app
    from qa_sentinel.host import composition
    for key, value in (("QA_SENTINEL_OPERATOR_USERNAME", USER), ("QA_SENTINEL_OPERATOR_PASSWORD", PASSWORD), ("QA_SENTINEL_SESSION_SECRET", SECRET)):
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr('qa_sentinel.host.hosted.tempfile.gettempdir', lambda: str(config.database.parent.parent))
    def forbidden(*args, **kwargs): raise AssertionError("Target CRUD cannot construct real execution")
    monkeypatch.setattr(composition, "real_components", forbidden)
    with TestClient(create_host_app(hosted(config)), base_url="https://testserver") as client:
        assert client.get('/api/v1/projects').status_code == 401
        assert login(client).status_code == 303
        project = client.get('/api/v1/projects').json()['items'][0]['id']
        base = f'/api/v1/projects/{project}'
        body = {"name":"WEB","environment":"LOCAL","configuration":{"base_url":"http://localhost:8000"}}
        assert client.post(base+'/targets',json=body).status_code == 403
        headers = csrf(client)
        target = client.post(base+'/targets',json=body,headers=headers)
        assert target.status_code == 201
        tid = target.json()['id']
        assert client.patch(base+f'/targets/{tid}',json={"name":"New"}).status_code == 403
        campaign = client.post(base+'/campaigns',json={"name":"Black box"},headers=headers).json()
        path = base+f"/campaigns/{campaign['id']}/target"
        assert client.put(path,json={"target_id":tid}).status_code == 403
        assert client.put(path,json={"target_id":tid},headers={**headers,"Origin":"https://evil.example"}).status_code == 403
        assert client.put(path,json={"target_id":tid},headers=headers).status_code == 200
        assert client.get(path).json()['id'] == tid


def test_repository_add_preserves_explicit_campaign_target(review):
    from qa_sentinel.domain.campaign import QACampaign
    from qa_sentinel.persistence.unit_of_work import UnitOfWork
    app, factory, _, _, p, _, _, _ = review
    target = make(app, p)
    campaign = QACampaign(project_id=p.id, name="Repository association", target_id=target.id)
    with UnitOfWork(factory) as uow:
        uow.campaigns.add(campaign)
        uow.commit()
    with UnitOfWork(factory) as uow:
        assert uow.campaigns.get(campaign.id) == campaign
