"""Offline campaign use cases, HTTP scoping, restart and side-effect proofs."""
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text, event
from qa_sentinel.api import create_api_app
from qa_sentinel.application import QASentinelApplication, ProjectExecutionResolver, ApplicationError
from qa_sentinel.projects import ProjectRuntimeRegistry
from qa_sentinel.domain.campaign import QACampaign
from qa_sentinel.persistence.unit_of_work import UnitOfWork


@pytest.fixture
def campaigns(migrated_factory):
    factory, engine, _ = migrated_factory
    app = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]), []))
    owner = app.create_project(key="owner", name="Owner")
    other = app.create_project(key="other", name="Other")
    return app, factory, engine, owner, other


def test_multiple_campaigns_reopen_updates_transitions_and_no_hidden_work(campaigns, monkeypatch):
    app, factory, engine, owner, other = campaigns
    from qa_sentinel.persistence.models import Base
    from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
    from pathlib import Path
    import subprocess
    api = create_api_app(app)
    def snapshot():
        with engine.connect() as connection:
            return {name: connection.execute(text(f'SELECT * FROM "{name}"')).all()
                    for name in Base.metadata.tables if name != "qa_campaigns"}
    before = snapshot()
    def forbidden(*args, **kwargs):
        raise AssertionError("Campaign preparation must not execute or access source/runtime")
    monkeypatch.setattr(app._resolver, "resolve", forbidden)
    monkeypatch.setattr(OpenAIModelAdapter, "generate", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    with TestClient(api) as client:
        base = f"/api/v1/projects/{owner.id}/campaigns"
        response = client.post(base, json={"name": "Booking smoke", "objective": "Checkout"})
        assert response.status_code == 201
        first = response.json()
        second = client.post(base, json={"name": "Browser acceptance"}).json()
        assert first["id"] != second["id"] and first["status"] == second["status"] == "DRAFT"
        path = base + "/" + first["id"]
        updated = client.patch(path, json={"name": "Checkout smoke", "objective": None}).json()
        assert updated["status"] == "DRAFT" and updated["objective"] is None
        assert updated["created_at"] == first["created_at"] and updated["updated_at"] >= first["updated_at"]
        assert client.patch(path, json={}).json() == updated
        ready = client.post(path+"/transitions", json={"status": "READY_FOR_REVIEW"}).json()
        assert ready["status"] == "READY_FOR_REVIEW"
        assert client.patch(path, json={"objective": "Updated scope"}).json()["status"] == "READY_FOR_REVIEW"
        approved = client.post(path+"/transitions", json={"status": "APPROVED"}).json()
        assert approved["status"] == "APPROVED"
        assert client.patch(path, json={"name": "Renamed"}).json()["status"] == "APPROVED"
        assert len(client.get(base).json()["items"]) == 2
        assert client.get(f"/api/v1/projects/{other.id}/campaigns").json()["items"] == []
    engine.dispose()
    restarted = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]), []))
    assert restarted.get_campaign(owner.id, first["id"]).status == "APPROVED"
    assert restarted.get_campaign(owner.id, first["id"]).name == "Renamed"
    assert restarted.get_campaign(owner.id, second["id"]).status == "DRAFT"
    assert snapshot() == before  # No Task, job, workflow/event/artifact or Project side effect.


@pytest.mark.parametrize("operation", ["get", "update", "transition"])
def test_application_project_scope_and_unknown_identity(campaigns, operation):
    app, _, _, owner, other = campaigns
    campaign = app.create_campaign(owner.id, name="Campaign")
    def invoke(project, identity):
        if operation == "get": return app.get_campaign(project, identity)
        if operation == "update": return app.update_campaign(project, identity, name="Spoof")
        return app.transition_campaign(project, identity, status="READY_FOR_REVIEW")
    for project, identity, code in [(other.id, campaign.id, "PROJECT_CAMPAIGN_MISMATCH"),
        (owner.id, uuid4(), "CAMPAIGN_NOT_FOUND"), (uuid4(), campaign.id, "PROJECT_NOT_FOUND"),
        ("invalid", campaign.id, "INVALID_INPUT"), (owner.id, "invalid", "INVALID_INPUT")]:
        with pytest.raises(ApplicationError, match=code): invoke(project, identity)
    assert app.get_campaign(owner.id, campaign.id) == campaign
    with pytest.raises(ApplicationError, match="PROJECT_NOT_FOUND"):
        app.create_campaign(uuid4(), name="No owner")
    with pytest.raises(ApplicationError, match="PROJECT_NOT_FOUND"):
        app.list_project_campaigns(uuid4())


def test_deterministic_utc_order_ties_and_sql_limit(campaigns):
    app, factory, engine, owner, other = campaigns
    instant = datetime(2026, 10, 7, tzinfo=timezone.utc)
    records = [QACampaign(id=UUID(int=i), project_id=owner.id, name=str(i),
        created_at=instant.astimezone(timezone(timedelta(hours=i%12)))) for i in range(1, 202)]
    latest = QACampaign(project_id=owner.id, name="Newest", created_at=instant+timedelta(seconds=1))
    newer = QACampaign(project_id=other.id, name="Foreign", created_at=instant+timedelta(days=1))
    with UnitOfWork(factory) as uow:
        for record in reversed(records): uow.campaigns.add(record)
        uow.campaigns.add(latest); uow.campaigns.add(newer); uow.commit()
    statements=[]
    def capture(connection, cursor, statement, parameters, context, executemany):
        if "qa_campaigns" in statement: statements.append((statement, parameters))
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = app.list_project_campaigns(owner.id, limit=200)
        assert len(result.items) == 200 and result.truncated and result.total_returned == 200
        assert [r.id for r in result.items] == [latest.id] + [r.id for r in records[:199]]
        assert app.list_project_campaigns(owner.id, limit=1).items[0].id == latest.id
        assert app.list_project_campaigns(other.id).items == (app.get_campaign(other.id, newer.id),)
    finally: event.remove(engine, "before_cursor_execute", capture)
    assert any("LIMIT" in statement and 201 in parameters for statement, parameters in statements)


@pytest.mark.parametrize("limit", [0, 201, True, "1"])
def test_application_limits_and_metadata_status_spoof_rejected(campaigns, limit):
    app, _, _, owner, _ = campaigns
    campaign = app.create_campaign(owner.id, name="Campaign")
    with pytest.raises(ApplicationError, match="INVALID_LIST_LIMIT"):
        app.list_project_campaigns(owner.id, limit=limit)
    with pytest.raises(ApplicationError, match="INVALID_INPUT"):
        app.update_campaign(owner.id, campaign.id, status="APPROVED")
    with pytest.raises(ApplicationError, match="CAMPAIGN_INVALID_TRANSITION"):
        app.transition_campaign(owner.id, campaign.id, status="APPROVED")
    assert app.get_campaign(owner.id, campaign.id) == campaign


@pytest.mark.parametrize("method, suffix, body", [("post", "", {"name":""}), ("post", "", {"name":"x"*201}),
    ("post", "", {"name":"C", "objective":"x"*4001}), ("post", "", {"name":5}),
    ("post", "", {"name":"C", "status":"APPROVED"}), ("post", "", {"name":"C", "project_id":str(uuid4())}),
    ("patch", "/{id}", {"name":None}), ("patch", "/{id}", {"status":"READY_FOR_REVIEW"}),
    ("patch", "/{id}", {"project_id":str(uuid4())}), ("patch", "/{id}", {"workspace_root":"forbidden"}),
    ("post", "/{id}/transitions", {"status":"RUNNING"}), ("post", "/{id}/transitions", {"status":"APPROVED", "name":"Hidden"})])
def test_http_invalid_extra_inputs_are_safe_and_non_mutating(campaigns, method, suffix, body):
    app, _, _, owner, _ = campaigns
    campaign = app.create_campaign(owner.id, name="Campaign")
    with TestClient(create_api_app(app)) as client:
        response = getattr(client, method)(f"/api/v1/projects/{owner.id}/campaigns" + suffix.format(id=campaign.id), json=body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] in {"INVALID_INPUT", "REQUEST_VALIDATION_ERROR"}
        assert "forbidden" not in response.text
    assert app.get_campaign(owner.id, campaign.id) == campaign
    assert app.list_project_campaigns(owner.id).total_returned == 1


def test_http_ownership_lifecycle_and_limits(campaigns):
    app, _, _, owner, other = campaigns
    campaign = app.create_campaign(owner.id, name="Campaign")
    with TestClient(create_api_app(app)) as client:
        path = f"/api/v1/projects/{other.id}/campaigns/{campaign.id}"
        for method, route, body in [("get", path, None), ("patch", path, {"name":"Foreign"}),
                ("post", path+"/transitions", {"status":"READY_FOR_REVIEW"})]:
            response = getattr(client, method)(route, **({} if body is None else {"json":body}))
            assert response.status_code == 409 and response.json()["error"]["code"] == "PROJECT_CAMPAIGN_MISMATCH"
        path = f"/api/v1/projects/{owner.id}/campaigns/{campaign.id}"
        response = client.post(path+"/transitions", json={"status":"APPROVED"})
        assert response.status_code == 409 and response.json()["error"]["code"] == "CAMPAIGN_INVALID_TRANSITION"
        for status in ("READY_FOR_REVIEW", "APPROVED"):
            assert client.post(path+"/transitions", json={"status":status}).json()["status"] == status
        for status in ("APPROVED", "READY_FOR_REVIEW", "DRAFT"):
            assert client.post(path+"/transitions", json={"status":status}).status_code == 409
        assert client.get(f"/api/v1/projects/{owner.id}/campaigns/{uuid4()}").json()["error"]["code"] == "CAMPAIGN_NOT_FOUND"
        assert client.get(f"/api/v1/projects/{uuid4()}/campaigns").json()["error"]["code"] == "PROJECT_NOT_FOUND"
        for limit in ("0", "201", "garbage"):
            assert client.get(f"/api/v1/projects/{owner.id}/campaigns?limit={limit}").status_code == 422
        assert client.get(f"/api/v1/projects/{owner.id}/campaigns/invalid").status_code == 422
