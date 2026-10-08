"""Offline atomic, immutable and scoped preparation snapshots; no executor binding."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text, event, select, func
from sqlalchemy.exc import IntegrityError
from qa_sentinel.application import QASentinelApplication, ProjectExecutionResolver, ApplicationError
from qa_sentinel.api import create_api_app
from qa_sentinel.persistence.models import Base, QARunRow, QARunTestRow, QARunRequirementRow
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.database import create_engine, create_session_factory
from qa_sentinel.projects import ProjectRuntimeRegistry
from qa_sentinel.domain.qa_run import PreparedQARun, snapshot_fingerprint, QAOutcome, QAResult, RunExecutionStatus
from test_campaign_review import review, approve_all
from test_campaign_test_specifications import seed_requirement, case, csv_text


@pytest.fixture
def ready(review):
    approve_all(review)
    return review


def create(ready, key="request-1", **kwargs):
    app, _, _, _, p, c, _, _ = ready
    return app.create_qa_run(p.id, c.id, idempotency_key=key, **kwargs)


def count_rows(engine):
    with engine.connect() as connection:
        return tuple(connection.scalar(text(f"SELECT count(*) FROM {table}"))
                     for table in ("qa_runs", "qa_run_requirements", "qa_run_tests"))


def test_complete_approved_snapshot_and_independent_status_contracts(ready):
    app, _, _, _, p, c, req, spec = ready
    run = create(ready, note="RC snapshot; inert <script>text</script>")
    assert (run.execution_status, run.qa_outcome, run.run_number) == ("CREATED", "NOT_EVALUATED", 1)
    assert run.started_at is run.completed_at is None
    assert run.requirement_count == run.test_count == 1
    assert run.readiness_at_creation == app.get_campaign_readiness(p.id, c.id)
    requirements = app.list_qa_run_requirements(p.id, c.id, run.id).items
    tests = app.list_qa_run_tests(p.id, c.id, run.id).items
    assert requirements[0].content.model_dump() == app.get_campaign_requirement(p.id, c.id, req.id).model_dump()
    assert tests[0].content.model_dump() == app.get_campaign_test_specification(p.id, c.id, spec.id).model_dump()
    assert requirements[0].approval == app.get_campaign_requirement_review(p.id, c.id, req.id).evidence
    assert tests[0].approval == app.get_campaign_test_specification_review(p.id, c.id, spec.id).evidence
    assert tests[0].linked_requirement_snapshot_ids == (requirements[0].id,)
    assert (tests[0].execution_status, tests[0].qa_result, tests[0].position) == ("NOT_STARTED", "NOT_EVALUATED", 1)
    assert snapshot_fingerprint(run.campaign_snapshot, requirements, tests) == run.snapshot_hash
    assert QAOutcome.FAIL.value == QAResult.FAIL.value == "FAIL"
    assert RunExecutionStatus.COMPLETED.value != QAOutcome.FAIL.value
    with pytest.raises(ValidationError): tests[0].content.title = "Changed"
    with pytest.raises(ValidationError): run.snapshot_hash = "0" * 64


def test_intentional_duplicates_key_replay_conflict_and_changed_preparation(ready):
    app, factory, _, _, p, c, _, _ = ready
    first = create(ready, note="RC")
    assert create(ready, note="RC") == first
    second = create(ready, "request-2", note="RC")
    assert second.id != first.id and second.run_number == 2 and second.snapshot_hash == first.snapshot_hash
    with pytest.raises(ApplicationError, match="RUN_IDEMPOTENCY_CONFLICT"): create(ready, note="Different")
    seed_requirement(factory, p, c, "ADDED")
    assert app.get_campaign_readiness(p.id, c.id).status == "NOT_READY"
    assert create(ready, note="RC") == first
    with pytest.raises(ApplicationError, match="CAMPAIGN_NOT_READY_FOR_RUN"): create(ready, "new-intent")


def test_snapshot_reopens_unchanged_after_campaign_evolves(ready):
    app, factory, engine, _, p, c, req, spec = ready
    run = create(ready)
    requirements = app.list_qa_run_requirements(p.id, c.id, run.id)
    tests = app.list_qa_run_tests(p.id, c.id, run.id)
    app.update_campaign(p.id, c.id, name="A later release", objective="New objective")
    seed_requirement(factory, p, c, "LATER")
    # Deliberate storage tampering proves historical reads use copies, not live content.
    with engine.begin() as connection:
        connection.execute(text("UPDATE campaign_test_specifications SET title='Live changed' WHERE id=:id"), {"id": str(spec.id)})
        connection.execute(text("UPDATE campaign_requirements SET description='Live changed' WHERE id=:id"), {"id": str(req.id)})
    url = str(engine.url)
    engine.dispose()
    reopened = create_engine(url)
    try:
        restarted = QASentinelApplication(create_session_factory(reopened), ProjectExecutionResolver(ProjectRuntimeRegistry([]), []))
        assert restarted.get_qa_run(p.id, c.id, run.id) == run
        assert restarted.list_qa_run_requirements(p.id, c.id, run.id) == requirements
        assert restarted.list_qa_run_tests(p.id, c.id, run.id) == tests
    finally:
        reopened.dispose()


@pytest.mark.parametrize("problem", ["campaign", "requirement", "test", "missing_requirement_receipt", "missing_test_receipt", "clarification"])
def test_not_ready_is_rejected_without_partial_records(ready, problem):
    _, factory, engine, _, p, c, _, _ = ready
    statements = {"campaign": "UPDATE qa_campaigns SET status='DRAFT'",
        "requirement": "UPDATE campaign_requirements SET review_status='READY_FOR_REVIEW'",
        "test": "UPDATE campaign_test_specifications SET review_status='READY_FOR_REVIEW'",
        "missing_requirement_receipt": "DELETE FROM campaign_requirement_reviews",
        "missing_test_receipt": "DELETE FROM campaign_test_reviews"}
    if problem == "clarification": seed_requirement(factory, p, c, "UNCLEAR", markers=[dict(kind="AMBIGUITY", description="Unresolved")])
    else:
        with engine.begin() as connection: connection.execute(text(statements[problem]))
    with pytest.raises(ApplicationError, match="CAMPAIGN_NOT_READY_FOR_RUN"): create(ready)
    assert count_rows(engine) == (0, 0, 0)


@pytest.mark.parametrize("kind", ["requirement", "test"])
def test_readiness_counts_do_not_bypass_full_receipt_hash_verification(ready, kind):
    app, _, engine, _, p, c, _, _ = ready
    table = "campaign_requirements" if kind == "requirement" else "campaign_test_specifications"
    with engine.begin() as connection: connection.execute(text(f"UPDATE {table} SET title='Unauthorized changed content'"))
    assert app.get_campaign_readiness(p.id, c.id).status == "READY"  # SQL counts are not hash verification.
    with pytest.raises(ApplicationError, match="REVIEW_EVIDENCE_INVALID"): create(ready)
    assert count_rows(engine) == (0, 0, 0)


def test_excludes_unapproved_and_blocked_extras_includes_all_approved_links(ready):
    app, _, _, _, p, c, req, _ = ready
    blocked = case("BLOCKED", refs=[str(req.id)])
    blocked["information_markers"] = [dict(kind="AMBIGUITY", description="Unknown")]
    app.import_campaign_tests(p.id, c.id, name="Extras", format="CSV", content=csv_text([
        case("Z_APPROVED", refs=[str(req.id)]), case("A_UNAPPROVED", refs=[str(req.id)]), blocked]))
    spec = next(s for s in app.list_campaign_test_specifications(p.id, c.id).items if s.key == "Z_APPROVED")
    app.review_campaign_test_specification(p.id, c.id, spec.id, reviewer_label="qa")
    run = create(ready)
    tests = app.list_qa_run_tests(p.id, c.id, run.id).items
    assert run.test_count == len(tests) == 2
    assert {t.content.key for t in tests} == {"LOGIN", "Z_APPROVED"}
    assert [t.content.logical_key for t in tests] == sorted(t.content.logical_key for t in tests)
    assert [t.position for t in tests] == [1, 2]


def test_multiple_requirements_preserve_links_and_hash_changes_with_preparation(ready):
    app, factory, _, _, p, c, original, _ = ready
    before = create(ready)
    req = seed_requirement(factory, p, c, "LOGOUT")
    app.review_campaign_requirement(p.id, c.id, req.id, reviewer_label="qa")
    app.import_campaign_tests(p.id, c.id, name="Coverage", format="CSV", content=csv_text([case("BOTH", refs=[str(original.id), str(req.id)])]))
    spec = next(s for s in app.list_campaign_test_specifications(p.id, c.id).items if s.key == "BOTH")
    app.review_campaign_test_specification(p.id, c.id, spec.id, reviewer_label="qa")
    after = create(ready, "after")
    assert before.snapshot_hash != after.snapshot_hash and after.requirement_count == after.test_count == 2
    reqs = app.list_qa_run_requirements(p.id, c.id, after.id).items
    tests = app.list_qa_run_tests(p.id, c.id, after.id).items
    linked = next(t for t in tests if t.content.key == "BOTH")
    assert set(linked.linked_requirement_snapshot_ids) == {r.id for r in reqs}


@pytest.mark.parametrize("intent", ["distinct", "same", "conflicting"])
def test_concurrent_creates_unique_atomic_numbers_and_idempotency(ready, intent):
    _, _, engine, _, _, _, _, _ = ready
    barrier = Barrier(4)
    def request(i):
        barrier.wait(timeout=10)
        try: return create(ready, str(i) if intent == "distinct" else "shared", note=str(i) if intent == "conflicting" else None)
        except ApplicationError as error: return error.code.value
    with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(request, range(4)))
    if intent == "distinct":
        assert {r.run_number for r in results} == {1, 2, 3, 4} and count_rows(engine) == (4, 4, 4)
    elif intent == "same":
        assert all(r == results[0] for r in results) and count_rows(engine) == (1, 1, 1)
    else:
        assert sum(r == "RUN_IDEMPOTENCY_CONFLICT" for r in results) == 3 and count_rows(engine) == (1, 1, 1)


@pytest.mark.parametrize("stage", ["child_insert", "commit"])
def test_failure_rolls_back_entire_run_and_key_and_number(ready, monkeypatch, stage):
    _, _, engine, _, _, _, _, _ = ready
    def fail(*args, **kwargs): raise RuntimeError("Synthetic persistence failure; must not leak")
    if stage == "commit": monkeypatch.setattr(UnitOfWork, "commit", fail)
    else: event.listen(QARunTestRow, "before_insert", fail)
    try:
        with pytest.raises(ApplicationError, match="PERSISTENCE_ERROR"): create(ready)
        assert count_rows(engine) == (0, 0, 0)
    finally:
        if stage == "child_insert": event.remove(QARunTestRow, "before_insert", fail)
        else: monkeypatch.undo()
    assert create(ready).run_number == 1


@pytest.mark.parametrize("bound", ["records", "bytes"])
def test_snapshot_bounds_fail_honestly_without_truncation(ready, monkeypatch, bound):
    from qa_sentinel.domain import qa_run
    from qa_sentinel.persistence import qa_runs
    _, _, engine, _, _, _, _, _ = ready
    if bound == "records": monkeypatch.setattr(qa_runs, "MAX_SNAPSHOT_RECORDS", 0)
    else: monkeypatch.setattr(qa_run, "MAX_SNAPSHOT_BYTES", 1)
    with pytest.raises(ApplicationError, match="RUN_SNAPSHOT_SIZE_LIMIT"): create(ready)
    assert count_rows(engine) == (0, 0, 0)


@pytest.mark.parametrize("key", [None, "", "x" * 129, "white space", "bad\nkey", 7, True, {"secret": "do-not-echo"}])
def test_invalid_idempotency_key_has_safe_explicit_code(ready, key):
    app, _, engine, _, p, c, _, _ = ready
    with pytest.raises(ApplicationError, match="INVALID_IDEMPOTENCY_KEY"): create(ready, key)
    with TestClient(create_api_app(app)) as client:
        response = client.post(f"/api/v1/projects/{p.id}/campaigns/{c.id}/runs", json={"idempotency_key": key})
    assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID_IDEMPOTENCY_KEY"
    assert "do-not-echo" not in response.text and count_rows(engine) == (0, 0, 0)


def test_scope_reads_hide_foreign_runs_and_create_scopes_key(ready):
    app, _, _, _, p, c, _, _ = ready
    run = create(ready)
    other_project = app.create_project(key="other", name="Other")
    other = app.create_campaign(p.id, name="Other")
    foreign = app.create_campaign(other_project.id, name="Foreign")
    for project, campaign in [(p, other), (other_project, foreign)]:
        for operation in (app.get_qa_run, app.list_qa_run_tests, app.list_qa_run_requirements):
            for id in (run.id, uuid4()):
                expected = "RUN_CAMPAIGN_MISMATCH" if project.id == p.id and id == run.id else "RUN_NOT_FOUND"
                with pytest.raises(ApplicationError, match=expected): operation(project.id, campaign.id, id)
        assert app.list_qa_runs(project.id, campaign.id).items == ()
        with pytest.raises(ApplicationError, match="CAMPAIGN_NOT_READY_FOR_RUN"):
            app.create_qa_run(project.id, campaign.id, idempotency_key="request-1")
    with pytest.raises(ApplicationError, match="PROJECT_NOT_FOUND"): app.create_qa_run(uuid4(), c.id, idempotency_key="valid")
    with pytest.raises(ApplicationError, match="CAMPAIGN_NOT_FOUND"): app.create_qa_run(p.id, uuid4(), idempotency_key="valid")
    with pytest.raises(ApplicationError, match="PROJECT_CAMPAIGN_MISMATCH"): app.create_qa_run(p.id, foreign.id, idempotency_key="valid")


def test_bounded_paginated_snapshot_reads_and_newest_first_runs(ready):
    app, _, _, _, p, c, req, _ = ready
    app.import_campaign_tests(p.id, c.id, name="More", format="CSV", content=csv_text([case("SECOND", refs=[str(req.id)])]))
    second = next(s for s in app.list_campaign_test_specifications(p.id, c.id).items if s.key == "SECOND")
    app.review_campaign_test_specification(p.id, c.id, second.id, reviewer_label="qa")
    first = create(ready)
    last = create(ready, "last")
    runs = app.list_qa_runs(p.id, c.id, limit=1)
    assert runs.truncated and runs.items == (last,)
    tests = app.list_qa_run_tests(p.id, c.id, first.id, limit=1)
    assert tests.truncated and tests.items[0].position == 1
    rest = app.list_qa_run_tests(p.id, c.id, first.id, limit=1, after_position=1)
    assert not rest.truncated and rest.items[0].position == 2
    assert app.list_qa_run_tests(p.id, c.id, first.id, after_position=2).items == ()
    for limit in (0, 201, True, "1"):
        with pytest.raises(ApplicationError, match="INVALID_LIST_LIMIT"): app.list_qa_runs(p.id, c.id, limit=limit)
        with pytest.raises(ApplicationError, match="INVALID_LIST_LIMIT"): app.list_qa_run_tests(p.id, c.id, first.id, limit=limit)
    for cursor in (-1, 1001, True, "1"):
        with pytest.raises(ApplicationError, match="INVALID_INPUT"): app.list_qa_run_tests(p.id, c.id, first.id, after_position=cursor)


def test_api_create_read_replay_error_bounds_and_no_execution_endpoint(ready):
    app, _, _, _, p, c, _, _ = ready
    prefix = f"/api/v1/projects/{p.id}/campaigns/{c.id}/runs"
    with TestClient(create_api_app(app)) as client:
        result = client.post(prefix, json={"idempotency_key": "browser-click", "note": "RC"})
        assert result.status_code == 201, result.text
        run = result.json()
        assert run["execution_status"] == "CREATED" and run["qa_outcome"] == "NOT_EVALUATED"
        assert client.get(prefix + "/" + run["id"]).json() == run
        assert client.post(prefix, json={"idempotency_key": "browser-click", "note": "RC"}).json() == run
        assert client.post(prefix, json={"idempotency_key": "browser-click"}).json()["error"]["code"] == "RUN_IDEMPOTENCY_CONFLICT"
        assert client.get(prefix).json()["items"] == [run]
        for kind in ("tests", "requirements"):
            entries = client.get(prefix + "/" + run["id"] + "/" + kind).json()
            assert entries["total_returned"] == 1 and entries["items"][0]["content"]["review_status"] == "APPROVED"
            assert client.get(prefix + "/" + run["id"] + "/" + kind + "?limit=201").status_code == 422
        for action in ("run", "execute", "resume"):
            assert client.post(prefix + "/" + run["id"] + "/" + action).status_code == 404
        assert client.patch(prefix + "/" + run["id"], json={"qa_outcome": "PASS"}).status_code == 405
        assert client.post(prefix, json={}).json()["error"]["code"] == "INVALID_IDEMPOTENCY_KEY"
        assert client.post(prefix, json={"idempotency_key": "new", "execution_status": "RUNNING"}).status_code == 422
        assert client.post(prefix, content=b"x"*8193).json()["error"]["code"] == "RUN_REQUEST_SIZE_LIMIT"


def test_create_and_reads_have_no_model_executor_or_legacy_side_effects(ready, monkeypatch):
    import subprocess
    import socket
    from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
    from qa_sentinel.mutation.service import MutationService
    app, factory, _, _, p, c, _, _ = ready
    def forbidden(*args, **kwargs): raise AssertionError("External or workflow execution forbidden")
    with UnitOfWork(factory) as uow:
        before = {t.name: uow.session.scalar(select(func.count()).select_from(t)) for t in Base.metadata.tables.values()}
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(OpenAIModelAdapter, "generate", forbidden)
    monkeypatch.setattr(MutationService, "apply", forbidden)
    monkeypatch.setattr(app._resolver, "resolve", forbidden)
    monkeypatch.setattr(app, "run_task", forbidden)
    monkeypatch.setattr(app, "create_task", forbidden)
    run = create(ready)
    app.get_qa_run(p.id, c.id, run.id)
    app.list_qa_runs(p.id, c.id)
    app.list_qa_run_requirements(p.id, c.id, run.id)
    app.list_qa_run_tests(p.id, c.id, run.id)
    with UnitOfWork(factory) as uow:
        after = {t.name: uow.session.scalar(select(func.count()).select_from(t)) for t in Base.metadata.tables.values()}
    changed = {name for name in after if after[name] != before[name]}
    assert changed == {"qa_runs", "qa_run_requirements", "qa_run_tests"}
    assert all(after[name] == 0 for name in ("tasks", "execution_jobs", "invocations", "events", "artifacts", "test_runs"))
    assert app.get_campaign(p.id, c.id).status == "APPROVED"


@pytest.mark.parametrize("table,column,value", [
    ("qa_runs", "run_number", 0), ("qa_runs", "qa_outcome", "APPROVED"),
    ("qa_runs", "execution_status", "PASS"), ("qa_run_tests", "execution_status", "FAIL"),
    ("qa_run_tests", "qa_result", "COMPLETED"), ("qa_run_tests", "position", 0),
    ("qa_run_requirements", "position", 0), ("qa_run_tests", "run_id", str(uuid4())),
    ("qa_runs", "campaign_id", str(uuid4()))])
def test_db_constraints_guard_status_separation_ownership_and_order(ready, table, column, value):
    _, _, engine, _, _, _, _, _ = ready
    create(ready)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text(f"UPDATE {table} SET {column}=:value"), {"value": value})
    assert count_rows(engine) == (1, 1, 1)


def test_complete_selection_is_independent_of_default_collection_page(ready):
    app, _, _, _, p, c, req, _ = ready
    app.import_campaign_tests(p.id, c.id, name="Large eligible set", format="CSV", content=csv_text([
        case(f"CASE_{i:03d}", refs=[str(req.id)]) for i in range(60)]))
    for spec in app.list_campaign_test_specifications(p.id, c.id, limit=200).items:
        if spec.review_status != "APPROVED":
            app.review_campaign_test_specification(p.id, c.id, spec.id, reviewer_label="qa")
    assert app.list_campaign_test_specifications(p.id, c.id).truncated
    run = create(ready)
    assert run.test_count == 61
    first = app.list_qa_run_tests(p.id, c.id, run.id)
    last = app.list_qa_run_tests(p.id, c.id, run.id, after_position=50)
    assert first.total_returned == 50 and first.truncated
    assert last.total_returned == 11 and not last.truncated
    assert {t.original_test_specification_id for t in first.items + last.items} == {
        s.id for s in app.list_campaign_test_specifications(p.id, c.id, limit=200).items}


@pytest.mark.parametrize("change", ["counts", "owner", "hash", "order", "link", "approval", "content", "original", "missing"])
def test_typed_repository_boundary_rejects_incomplete_or_forged_snapshots(ready, change):
    app, factory, _, _, p, c, _, _ = ready
    run = create(ready)
    values = PreparedQARun(run=run, requirements=app.list_qa_run_requirements(p.id, c.id, run.id).items,
                           tests=app.list_qa_run_tests(p.id, c.id, run.id).items).model_dump(mode="json")
    if change == "counts": values["run"]["test_count"] = 2
    elif change == "owner": values["tests"][0]["run_id"] = str(uuid4())
    elif change == "hash": values["run"]["snapshot_hash"] = "0" * 64
    elif change == "order": values["tests"][0]["position"] = 2
    elif change == "link": values["tests"][0]["linked_requirement_snapshot_ids"] = [str(uuid4())]
    elif change == "approval": values["requirements"][0]["approval"]["content_hash"] = "0" * 64
    elif change == "content": values["tests"][0]["content"]["title"] = "Forged"
    elif change == "original": values["requirements"][0]["original_requirement_id"] = str(uuid4())
    elif change == "missing": values["tests"] = []
    # model_construct bypass is revalidated at the persistence boundary.
    with UnitOfWork(factory) as uow, pytest.raises(ValidationError), pytest.warns(UserWarning, match="Pydantic serializer warnings"):
        uow.qa_runs.add(PreparedQARun.model_construct(**values))


def test_fingerprint_ignores_snapshot_and_approval_times_but_tracks_facts(ready):
    from datetime import timedelta
    app, _, _, _, p, c, _, _ = ready
    run = create(ready)
    reqs = app.list_qa_run_requirements(p.id, c.id, run.id).items
    tests = app.list_qa_run_tests(p.id, c.id, run.id).items
    approval = reqs[0].approval.model_copy(update={"approved_at": reqs[0].approval.approved_at + timedelta(days=1)})
    later = (reqs[0].model_copy(update={"approval": approval}),)
    assert snapshot_fingerprint(run.campaign_snapshot, later, tests) == run.snapshot_hash
    req_content = reqs[0].content.model_copy(update={"description": "New execution fact"})
    changed_req = (reqs[0].model_copy(update={"content": req_content}),)
    assert snapshot_fingerprint(run.campaign_snapshot, changed_req, tests) != run.snapshot_hash
    test_content = tests[0].content.model_copy(update={"requirement_ids": (uuid4(),)})
    changed_test = (tests[0].model_copy(update={"content": test_content}),)
    assert snapshot_fingerprint(run.campaign_snapshot, reqs, changed_test) != run.snapshot_hash
    campaign = run.campaign_snapshot.model_copy(update={"objective": "New objective"})
    assert snapshot_fingerprint(campaign, reqs, tests) != run.snapshot_hash
