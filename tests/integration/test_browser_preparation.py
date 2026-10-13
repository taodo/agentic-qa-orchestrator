"""Offline source-free intent, immutable snapshots and pre-Run persistence."""
from copy import deepcopy
from uuid import uuid4
import json
import pytest
from alembic import command
from sqlalchemy import text, inspect
from sqlalchemy.exc import IntegrityError
from pydantic import ValidationError
from qa_sentinel.application import QASentinelApplication, ProjectExecutionResolver, ApplicationError
from qa_sentinel.projects import ProjectRuntimeRegistry
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.database import create_engine, create_session_factory
from qa_sentinel.domain.browser_preparation import (BrowserPreparation, CreateBrowserPreparation,
    PreparationError, start_preparation, start_item, finish_item, finish_preparation)
from qa_sentinel.domain.qa_run import (QARun, QARunTest, PreparedQARun, snapshot_fingerprint,
    CampaignSnapshot, BROWSER_SNAPSHOT_VERSION)
from qa_sentinel.domain.target import TargetSnapshot
from qa_sentinel.domain.browser_execution import BrowserExecutionPlan, BrowserPlanEnvelope
from qa_sentinel.domain.campaign_review import content_hash
from qa_sentinel.execution.browser_policy import BrowserExecutionPolicy, digest, run_test_snapshot_digest
from test_browser_plan_generation import Executor, planning, rows
from test_campaign_test_specifications import case, csv_text
from test_qa_runs import ready, create, review


@pytest.fixture
def source_free(migrated_factory):
    factory, engine, config = migrated_factory
    app = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]), []))
    p = app.create_project(key="source-free", name="Source free")
    c = app.create_campaign(p.id, name="No specification")
    values = [case("ONE"), case("TWO"), case("THREE")]
    for value in values:
        value.update(title="Public heading", preconditions=[], steps=[dict(index=1, action="Open the public page", expected="Welcome")], overall_expected_result="Welcome", required_evidence=["Heading assertion"])
    app.import_campaign_tests(p.id, c.id, name="Existing tests", format="CSV", content=csv_text(values))
    tests = app.list_campaign_test_specifications(p.id, c.id).items
    target = app.create_target(p.id, name="Generic WEB", environment="STAGING", configuration={"base_url":"https://example.com"})
    app.associate_campaign_target(p.id, c.id, target_id=target.id)
    return app, factory, engine, config, p, c, tests, target


def approve_source_free(data):
    app, _, _, _, p, c, tests, _ = data
    for test in tests:
        app.review_source_free_campaign_test(p.id, c.id, test.id, reviewer_label="qa")
    return tuple(app.get_campaign_test_specification(p.id, c.id, t.id) for t in tests)


def prepare(data, *, key="intent", ids=None, mode="HEADLESS"):
    app, _, _, _, p, c, tests, _ = data
    return app.create_browser_preparation(p.id, c.id, idempotency_key=key,
        test_specification_ids=ids or tuple(t.id for t in tests), browser_mode=mode)


def stored(record):
    return BrowserPreparation.model_validate(record.model_dump(exclude={"resulting_run_id"}))


def transition(factory, record, action, **arguments):
    with UnitOfWork(factory) as uow:
        uow.session.connection(execution_options={"qa_job_write":True})
        result = uow.browser_preparations.transition(record, action, **arguments)
        uow.commit()
        return result


def sealed_v3(data, *, preparation_id=None):
    app, factory, _, _, p, c, tests, target = data
    test = app.get_campaign_test_specification(p.id, c.id, tests[0].id)
    approval = app.get_campaign_test_specification_review(p.id, c.id, test.id).evidence
    run_id = uuid4()
    run_test = QARunTest(id=uuid4(), run_id=run_id, original_test_specification_id=test.id, position=1,
        content=test, approval=approval, linked_requirement_snapshot_ids=(), snapshot_version=BROWSER_SNAPSHOT_VERSION)
    target_snapshot = TargetSnapshot.capture(target)
    plan = BrowserExecutionPlan(steps=[{"action":"NAVIGATE","path":"/"}, {"action":"ASSERT_TEXT", "locator":{"strategy":"ROLE","role":"heading","name":"Welcome","exact":True}, "text":"Welcome"}])
    envelope = BrowserPlanEnvelope(project_id=p.id, campaign_id=c.id, run_id=run_id, run_test_id=run_test.id,
        origin="DETERMINISTIC", test_snapshot_hash=run_test_snapshot_digest(run_test), target_snapshot_hash=digest(target_snapshot), plan_hash=digest(plan), plan=plan)
    run_test = QARunTest.model_validate({**run_test.model_dump(), "snapshot_version":BROWSER_SNAPSHOT_VERSION, "browser_plan":envelope})
    campaign = CampaignSnapshot.model_validate(c.model_dump(include=set(CampaignSnapshot.model_fields)))
    with UnitOfWork(factory) as uow:
        number = uow.qa_runs.next_number(c.id)
    run = QARun(id=run_id, project_id=p.id, campaign_id=c.id, run_number=number, idempotency_key="v3-"+str(run_id),
        snapshot_version=BROWSER_SNAPSHOT_VERSION, executor_kind="WEB_BROWSER", runtime_identity=Executor.identity,
        target_snapshot=target_snapshot, campaign_snapshot=campaign, readiness_at_creation=app.get_campaign_readiness(p.id,c.id),
        requirement_count=0, test_count=1, preparation_id=preparation_id,
        snapshot_hash=snapshot_fingerprint(campaign, (), (run_test,), BROWSER_SNAPSHOT_VERSION, target_snapshot, Executor.identity, preparation_id))
    return PreparedQARun(run=run, requirements=(), tests=(run_test,))


def test_explicit_source_free_approval_keeps_traceability_informational(source_free):
    app, _, engine, _, p, c, tests, _ = source_free
    assert all(t.review_status == "NEEDS_CLARIFICATION" for t in tests)
    with pytest.raises(ApplicationError, match="REVIEW_NOT_REVIEWABLE"):
        app.review_campaign_test_specification(p.id,c.id,tests[0].id,reviewer_label="qa")
    with pytest.raises(ApplicationError, match="REVIEW_NOT_REVIEWABLE"):
        prepare(source_free)
    approved = approve_source_free(source_free)
    assert all(t.review_status == "APPROVED" and not t.requirement_ids for t in approved)
    assert all([m.kind for m in t.information_markers] == ["MISSING_TRACEABILITY"] for t in approved)
    for old, new in zip(tests, approved):
        assert old.model_dump(exclude={"review_status","updated_at"}) == new.model_dump(exclude={"review_status","updated_at"})
        assert app.get_campaign_test_specification_review(p.id,c.id,new.id).evidence.content_hash == content_hash(new)
    assert app.get_campaign_readiness(p.id,c.id).status == "NOT_READY"
    with pytest.raises(ApplicationError):
        app.create_qa_run(p.id,c.id,idempotency_key="legacy",test_specification_ids=[approved[0].id])
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM campaign_requirements")) == 0
        assert db.scalar(text("SELECT count(*) FROM qa_runs")) == 0


@pytest.mark.parametrize("problem", ["unresolved", "ambiguity", "missing", "evidence", "draft", "superseded"])
def test_source_free_approval_preserves_real_blockers(source_free, problem):
    app, _, _, _, p, c, _, _ = source_free
    value = case("BLOCKED", refs=["UNKNOWN"] if problem == "unresolved" else [])
    if problem in {"ambiguity","missing"}:
        value["information_markers"] = [{"kind":"AMBIGUITY" if problem=="ambiguity" else "MISSING_INFORMATION","description":"Needs human information"}]
    if problem == "evidence":
        value["required_evidence"] = []
        value["information_markers"] = [{"kind":"MISSING_INFORMATION","description":"Evidence missing"}]
    app.import_campaign_tests(p.id,c.id,name="Blocked",format="CSV",content=csv_text([value]))
    test = next(t for t in app.list_campaign_test_specifications(p.id,c.id).items if t.key=="BLOCKED")
    if problem == "draft":
        from qa_sentinel.domain.campaign_review import approve, ApprovalCommand, SOURCE_FREE_APPROVAL_POLICY
        test = type(test).model_validate({**test.model_dump(), "review_status":"DRAFT"})
        with pytest.raises(ValueError):
            approve(test,"TEST_SPECIFICATION",ApprovalCommand(reviewer_label="qa"),policy=SOURCE_FREE_APPROVAL_POLICY)
        return
    if problem == "superseded":
        from qa_sentinel.domain.test_specification import TestDesign
        app.edit_campaign_test(p.id,c.id,test.id,design=TestDesign.model_validate(test.model_dump(include=set(TestDesign.model_fields))),previous_hash=content_hash(test),reviewer_label="qa",note="Human successor")
    with pytest.raises(ApplicationError, match="REVIEW_NOT_REVIEWABLE"):
        app.review_source_free_campaign_test(p.id,c.id,test.id,reviewer_label="qa")
    assert app.get_campaign_test_specification(p.id,c.id,test.id).review_status != "APPROVED"


def test_preparation_is_durable_ordered_source_free_and_inert(source_free, monkeypatch):
    app, _, engine, _, p, c, tests, _ = source_free
    approve_source_free(source_free)
    import socket, subprocess
    monkeypatch.setattr(socket,"getaddrinfo",lambda *a,**k:pytest.fail("No DNS"))
    monkeypatch.setattr(subprocess,"Popen",lambda *a,**k:pytest.fail("No Chromium/subprocess"))
    ids = tuple(t.id for t in reversed(tests))
    record = prepare(source_free, ids=ids, mode="HEADED")
    assert record.browser_mode=="HEADED" and record.status=="CREATED" and record.resulting_run_id is None
    assert tuple(i.original_test_id for i in record.items)==ids and all(i.status=="PENDING" for i in record.items)
    assert all(i.test_hash==i.approval.content_hash for i in record.items)
    assert prepare(source_free, ids=ids, mode="HEADED")==record
    reopened=create_engine(str(engine.url)); factory=create_session_factory(reopened)
    try:
        restarted=QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]),[]))
        assert restarted.get_browser_preparation(p.id,c.id,record.id)==record
    finally: reopened.dispose()
    with engine.connect() as db:
        for table in ("qa_runs","qa_run_evidence","tasks","execution_jobs","browser_plan_generations"):
            assert db.scalar(text("SELECT count(*) FROM "+table))==0


@pytest.mark.parametrize("change", ["mode", "order", "selection", "target"])
def test_idempotency_conflicts_do_not_change_selection(source_free, change):
    app, _, _, _, p, c, tests, target = source_free
    approve_source_free(source_free); record=prepare(source_free)
    mode="HEADED" if change=="mode" else "HEADLESS"
    ids=tuple(t.id for t in (reversed(tests) if change=="order" else tests[:1] if change=="selection" else tests))
    if change=="target":
        target2=app.create_target(p.id,name="Other",environment="STAGING",configuration={"base_url":"https://different.example"})
        app.associate_campaign_target(p.id,c.id,target_id=target2.id)
    with pytest.raises(ApplicationError,match="PREPARATION_IDEMPOTENCY_CONFLICT"):
        prepare(source_free,ids=ids,mode=mode)
    assert app.get_browser_preparation(p.id,c.id,record.id)==record


def test_selection_bounds_duplicates_and_cross_scope(source_free):
    app, _, _, _, p, c, tests, _ = source_free; approve_source_free(source_free)
    for ids in [(), (tests[0].id,tests[0].id), tuple(uuid4() for _ in range(501))]:
        with pytest.raises(ValidationError):CreateBrowserPreparation(idempotency_key="key",test_specification_ids=ids)
    other=app.create_campaign(p.id,name="Other")
    with pytest.raises(ApplicationError,match="RUN_SELECTION_INVALID"):
        app.create_browser_preparation(p.id,c.id,idempotency_key="bad",test_specification_ids=[uuid4()])
    record=prepare(source_free)
    with pytest.raises(ApplicationError,match="PREPARATION_NOT_FOUND"):
        app.get_browser_preparation(p.id,other.id,record.id)
    for data in [{"idempotency_key":"key","test_specification_ids":[tests[0].id],"cookies":"secret"},
        {"idempotency_key":"key","test_specification_ids":[tests[0].id],"browser_mode":"EVALUATE"}]:
        with pytest.raises(ValidationError):CreateBrowserPreparation(**data)


def test_mixed_lifecycle_reconciliation_and_terminal_seal(source_free):
    app, factory, engine, _, p, c, _, _=source_free;approve_source_free(source_free)
    record=stored(prepare(source_free));record=transition(factory,record,"START")
    stale=record
    outcomes=[("RUNNABLE",None), ("NEEDS_ATTENTION","AMBIGUOUS_TARGET"), ("SYSTEM_ERROR","PREPARATION_SYSTEM_ERROR")]
    for item,(status,reason) in zip(record.items,outcomes):
        record=transition(factory,record,"START_ITEM",item_id=item.id)
        current=next(i for i in record.items if i.id==item.id)
        args={"grounding_id":uuid4(),"observation_hash":"a"*64,"plan_hash":"b"*64} if status=="RUNNABLE" else {}
        with pytest.raises(PreparationError):
            transition(factory,record,"FINISH_ITEM",item_id=item.id,attempt_id=uuid4(),status=status,reason_code=reason,**args)
        record=transition(factory,record,"FINISH_ITEM",item_id=item.id,attempt_id=current.attempt_id,status=status,reason_code=reason,**args)
    with pytest.raises(PreparationError):transition(factory,stale,"START_ITEM",item_id=stale.items[0].id)
    record=transition(factory,record,"FINISH")
    assert record.status=="COMPLETED" and [i.status for i in record.items]==["RUNNABLE","NEEDS_ATTENTION","SYSTEM_ERROR"]
    assert all("qa_result" not in i.model_dump() for i in record.items)
    assert app.get_browser_preparation(p.id,c.id,record.id).resulting_run_id is None
    with pytest.raises(PreparationError):transition(factory,record,"START")
    for sql in ["UPDATE browser_preparations SET status=status", "DELETE FROM browser_preparations"]:
        with pytest.raises(IntegrityError),engine.begin() as db:db.execute(text(sql))


def test_started_work_survives_restart_and_cannot_be_restarted(source_free):
    app, factory, engine, _, p, c, _, _=source_free;approve_source_free(source_free)
    record=transition(factory,stored(prepare(source_free)),"START")
    record=transition(factory,record,"START_ITEM",item_id=record.items[0].id)
    engine.dispose();read=stored(app.get_browser_preparation(p.id,c.id,record.id))
    assert read==record and read.items[0].attempt_id is not None
    with pytest.raises(PreparationError):transition(factory,read,"START")
    with pytest.raises(PreparationError):transition(factory,read,"START_ITEM",item_id=read.items[0].id)
    failed=transition(factory,read,"FINISH",error_code="PREPARATION_INTERRUPTED")
    assert failed.status=="FAILED" and failed.items[0].status=="PREPARING" and failed.items[0].attempt_id==read.items[0].attempt_id


@pytest.mark.parametrize("bad", ["selection", "target", "mode", "test", "approval", "qa", "dom", "terminal"])
def test_forged_preparation_rejected(source_free,bad):
    approve_source_free(source_free);record=stored(prepare(source_free));value=record.model_dump(mode="json")
    if bad=="selection":value["items"][1]["original_test_id"]=value["items"][0]["original_test_id"]
    elif bad=="target":value["target_snapshot"]["project_id"]=str(uuid4())
    elif bad=="mode":value["browser_mode"]="HEADED"
    elif bad=="test":value["items"][0]["test"]["title"]="Changed"
    elif bad=="approval":value["items"][0]["approval"]["content_hash"]="0"*64
    elif bad=="qa":value["items"][0]["status"]="FAIL"
    elif bad=="dom":value["items"][0]["raw_dom"]="<untrusted>"
    elif bad=="terminal":value["status"]="COMPLETED"
    with pytest.raises(ValueError):BrowserPreparation.model_validate(value)


def test_v3_source_free_snapshot_persistence_results_and_exact_hash(source_free):
    app,factory,engine,_,p,c,_,_=source_free;approve_source_free(source_free)
    prepared=sealed_v3(source_free)
    BrowserExecutionPolicy().validate_envelope(prepared.tests[0].browser_plan,prepared.run,prepared.tests[0])
    assert PreparedQARun.model_validate(prepared.model_dump())==prepared
    assert prepared.run.snapshot_hash==snapshot_fingerprint(prepared.run.campaign_snapshot,(),prepared.tests, BROWSER_SNAPSHOT_VERSION,prepared.run.target_snapshot,prepared.run.runtime_identity)
    assert prepared.run.snapshot_hash!=snapshot_fingerprint(prepared.run.campaign_snapshot,(),prepared.tests,"qa-run-selection-v2",prepared.run.target_snapshot,prepared.run.runtime_identity)
    with UnitOfWork(factory) as uow:
        uow.session.connection(execution_options={"qa_job_write":True});uow.qa_runs.add(prepared);uow.commit()
    engine.dispose()
    assert app.get_qa_run(p.id,c.id,prepared.run.id)==prepared.run
    results=app.get_qa_run_results(p.id,c.id,prepared.run.id)
    assert results.summary.not_evaluated==1 and results.tests.items[0].linked_requirement_snapshot_ids==()
    assert results.tests.items[0].evidence_count==0
    with UnitOfWork(factory) as uow:assert uow.qa_runs.preparation(prepared.run)==prepared


@pytest.mark.parametrize("version",["qa-run-snapshot-v1","qa-run-selection-v2"])
def test_legacy_cannot_use_source_free_escape_hatch(source_free,version):
    approve_source_free(source_free);prepared=sealed_v3(source_free);value=prepared.model_dump()
    value["run"]["snapshot_version"]=version
    with pytest.raises(ValidationError):PreparedQARun.model_validate(value)
    with pytest.raises(ValidationError):QARunTest.model_validate({**prepared.tests[0].model_dump(),"snapshot_version":version})
    value["run"]["snapshot_version"]=BROWSER_SNAPSHOT_VERSION;value["run"]["executor_kind"]="SYNTHETIC";value["run"]["runtime_identity"]=None
    with pytest.raises(ValidationError):PreparedQARun.model_validate(value)


def test_v3_unresolved_and_missing_links_rejected(source_free):
    approve_source_free(source_free);prepared=sealed_v3(source_free);value=prepared.model_dump()
    value["tests"][0]["content"]["requirement_ids"]=[uuid4()]
    with pytest.raises(ValidationError):PreparedQARun.model_validate(value)
    value=prepared.model_dump();value["tests"][0]["content"]["unresolved_requirement_refs"]=["explicit-unknown"]
    with pytest.raises(ValidationError):PreparedQARun.model_validate(value)


def test_preparation_schema_migration_roundtrip_and_history_refusal(source_free):
    app,_,engine,config,p,c,_,_=source_free
    command.check(config)
    command.downgrade(config,"0015")
    assert "browser_preparations" not in inspect(engine).get_table_names()
    command.upgrade(config,"head");command.check(config)
    assert "browser_preparations" in inspect(engine).get_table_names()
    approve_source_free(source_free);record=prepare(source_free)
    with pytest.raises(RuntimeError,match="cannot erase"):
        command.downgrade(config,"0015")
    assert app.get_browser_preparation(p.id,c.id,record.id)==record
    with engine.connect() as db:assert not db.exec_driver_sql("PRAGMA foreign_key_check").all()


def test_upgrade_preserves_historical_fingerprints_triggers_and_results(ready):
    app,_,engine,config,p,c,_,_=ready
    command.downgrade(config,"0015")
    # Prior-version runtime is represented by old schema SQL, not new ORM columns.
    # Use the frozen 0015 schema and restore 0016 before current application writes.
    with engine.connect() as db:
        before_triggers=set(db.scalars(text("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='qa_runs'")))
    command.upgrade(config,"0016")
    run=create(ready);test=app.list_qa_run_tests(p.id,c.id,run.id).items[0]
    before=(run.snapshot_hash,test.model_dump())
    command.downgrade(config,"0015");command.upgrade(config,"0016")
    assert app.get_qa_run(p.id,c.id,run.id).snapshot_hash==before[0]
    assert app.list_qa_run_tests(p.id,c.id,run.id).items[0].model_dump()==before[1]
    assert app.get_qa_run_results(p.id,c.id,run.id).summary.total==run.test_count
    with engine.connect() as db:
        assert before_triggers <= set(db.scalars(text("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='qa_runs'")))
        assert not db.exec_driver_sql("PRAGMA foreign_key_check").all()
    command.upgrade(config,"head");command.check(config)


def test_no_traceability_approval_blocks_unsafe_downgrade(source_free):
    app, _, _, config, p, c, tests, _ = source_free
    app.review_source_free_campaign_test(p.id,c.id,tests[0].id,reviewer_label="qa")
    with pytest.raises(RuntimeError,match="source-free approval history"):
        command.downgrade(config,"0015")
    assert app.get_campaign_test_specification(p.id,c.id,tests[0].id).review_status=="APPROVED"


def test_v3_with_requirement_links_keeps_exact_snapshot_checks(planning):
    app, factory, _, _, p, c, test, _, _, _=planning
    run=app.create_qa_run(p.id,c.id,idempotency_key="linked",test_specification_ids=[test.id])
    from qa_sentinel.application.browser_runs import seal
    from test_browser_plan_generation import PLAN
    with UnitOfWork(factory) as uow: prepared=uow.qa_runs.preparation(run)
    prepared=seal(prepared,{test.id:BrowserExecutionPlan(**PLAN)},Executor.identity,BrowserExecutionPolicy())
    value=prepared.model_dump();value["run"]["snapshot_version"]=BROWSER_SNAPSHOT_VERSION
    value["run"]["snapshot_hash"]=snapshot_fingerprint(run.campaign_snapshot,prepared.requirements,prepared.tests,BROWSER_SNAPSHOT_VERSION,run.target_snapshot,Executor.identity)
    v3=PreparedQARun.model_validate(value)
    assert v3.tests[0].linked_requirement_snapshot_ids==(v3.requirements[0].id,)
    for links in [[],[uuid4()]]:
        forged=deepcopy(value);forged["tests"][0]["linked_requirement_snapshot_ids"]=links
        with pytest.raises(ValidationError):PreparedQARun.model_validate(forged)


def test_historical_fingerprint_matches_frozen_legacy_algorithm(ready):
    from hashlib import sha256
    from qa_sentinel.domain.qa_run import canonical_json
    app,factory,_,_,p,c,_,_=ready
    for selection in [None,[app.list_campaign_test_specifications(p.id,c.id).items[0].id]]:
        run=app.create_qa_run(p.id,c.id,idempotency_key="fingerprint-"+str(uuid4()),test_specification_ids=selection)
        with UnitOfWork(factory) as uow: prepared=uow.qa_runs.preparation(run)
        def old_facts(entry):
            return {"position":entry.position,"content":entry.content.model_dump(mode="json",exclude={"created_at","updated_at"}),"approved_content_hash":entry.approval.content_hash}
        payload={"version":run.snapshot_version,"campaign":run.campaign_snapshot.model_dump(mode="json"),"requirements":[old_facts(r) for r in prepared.requirements],"tests":[old_facts(t) for t in prepared.tests]}
        assert run.snapshot_hash==sha256(canonical_json(payload)).hexdigest()
        assert all("snapshot_version" not in t.model_dump() for t in prepared.tests)


def test_preparation_accepts_500_unique_test_identities_without_work(source_free):
    from qa_sentinel.domain.browser_preparation import create_preparation
    from qa_sentinel.domain.campaign_review import ApprovalEvidence
    app, _, _, _, p, c, tests, target=source_free
    selected=[]
    for n in range(500):
        test=type(tests[0]).model_validate({**tests[0].model_dump(),"id":uuid4(),"logical_key":"CASE-"+str(n),"review_status":"APPROVED"})
        approval=ApprovalEvidence(object_id=test.id,object_kind="TEST_SPECIFICATION",project_id=p.id,campaign_id=c.id,reviewer_label="fixture",content_hash=content_hash(test))
        selected.append((test,approval))
    command=CreateBrowserPreparation(idempotency_key="500",test_specification_ids=tuple(t.id for t,_ in selected))
    record=create_preparation(p.id,c.id,command,TargetSnapshot.capture(target),selected)
    assert record.selected_count==500 and len(record.items)==500 and record.status=="CREATED"
    assert all(i.attempt_id is None and i.status=="PENDING" for i in record.items)


def test_concurrent_idempotent_creation_has_one_durable_identity(source_free):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    approve_source_free(source_free); barrier=Barrier(2)
    def worker():
        barrier.wait();return prepare(source_free)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one,two=list(pool.map(lambda _:worker(),range(2)))
    assert one==two
    with source_free[2].connect() as db:assert db.scalar(text("SELECT count(*) FROM browser_preparations"))==1


@pytest.mark.parametrize("field",["browser_mode","target_snapshot","test","approval","status"])
def test_sql_cannot_rewrite_sealed_selection(source_free,field):
    _,_,engine,_,_,_,_,_=source_free;approve_source_free(source_free);record=prepare(source_free)
    value=start_preparation(stored(record)).model_dump(mode="json")
    if field=="browser_mode":value["browser_mode"]="HEADED"
    elif field=="target_snapshot":value[field]["name"]="Replaced"
    elif field=="test":value["items"][0]["test"]["title"]="Replaced"
    elif field=="approval":value["items"][0]["approval"]["reviewer_label"]="replacement"
    elif field=="status":value["items"][0]["status"]="RUNNABLE"
    with pytest.raises(IntegrityError),engine.begin() as db:
        db.execute(text("UPDATE browser_preparations SET status='PREPARING',browser_mode=:mode,payload=:payload WHERE id=:id"),{"payload":json.dumps(value),"id":str(record.id),"mode":value["browser_mode"]})


def test_future_run_link_is_scoped_unique_and_auditable(source_free):
    app,factory,engine,_,p,c,tests,_=source_free;approve_source_free(source_free)
    record=stored(prepare(source_free,ids=(tests[0].id,)))
    sealed=sealed_v3(source_free,preparation_id=record.id)
    with pytest.raises(ValueError),UnitOfWork(factory) as uow:
        uow.qa_runs.add(sealed)
    record=transition(factory,record,"START")
    record=transition(factory,record,"START_ITEM",item_id=record.items[0].id)
    record=transition(factory,record,"FINISH_ITEM",item_id=record.items[0].id,attempt_id=record.items[0].attempt_id,status="RUNNABLE",grounding_id=uuid4(),observation_hash="a"*64,plan_hash=sealed.tests[0].browser_plan.plan_hash)
    record=transition(factory,record,"FINISH")
    with UnitOfWork(factory) as uow:
        uow.qa_runs.add(sealed);uow.commit()
    assert app.get_browser_preparation(p.id,c.id,record.id).resulting_run_id==sealed.run.id
    with pytest.raises(IntegrityError),UnitOfWork(factory) as uow:
        uow.qa_runs.add(sealed_v3(source_free,preparation_id=record.id));uow.commit()
    with pytest.raises(IntegrityError),engine.begin() as db:
        db.execute(text("UPDATE qa_runs SET preparation_id=NULL"))
    assert app.get_browser_preparation(p.id,c.id,record.id).items==record.items


@pytest.mark.parametrize("action", ["START_ITEM", "FINISH_ITEM", "FINISH", "EXECUTE"])
def test_preparation_transition_whitelist_requires_start(source_free,action):
    _,factory,_,_,_,_,_,_=source_free;approve_source_free(source_free);record=stored(prepare(source_free))
    kwargs={"item_id":record.items[0].id} if action=="START_ITEM" else {"item_id":record.items[0].id,"attempt_id":uuid4(),"status":"RUNNABLE"} if action=="FINISH_ITEM" else {}
    with pytest.raises(PreparationError):transition(factory,record,action,**kwargs)


def test_complete_preparation_cannot_hide_pending_items(source_free):
    _,factory,_,_,_,_,_,_=source_free;approve_source_free(source_free)
    record=transition(factory,stored(prepare(source_free)),"START")
    with pytest.raises(ValidationError):transition(factory,record,"FINISH")
    with pytest.raises(PreparationError):transition(factory,record,"FINISH_ITEM",item_id=record.items[0].id,attempt_id=uuid4(),status="FAIL")
    with pytest.raises(ValidationError):transition(factory,record,"FINISH",error_code="raw internal exception")


def test_complete_selection_size_limit_is_honest_and_atomic(source_free,monkeypatch):
    import qa_sentinel.domain.browser_preparation as contract
    approve_source_free(source_free);monkeypatch.setattr(contract,"MAX_PREPARATION_BYTES",100)
    with pytest.raises(ApplicationError,match="PREPARATION_SIZE_LIMIT"):prepare(source_free)
    with source_free[2].connect() as db:assert db.scalar(text("SELECT count(*) FROM browser_preparations"))==0


def test_browser_v3_history_cannot_be_downgraded(source_free):
    app,factory,engine,config,p,c,_,_=source_free;approve_source_free(source_free);prepared=sealed_v3(source_free)
    with UnitOfWork(factory) as uow:uow.qa_runs.add(prepared);uow.commit()
    with pytest.raises(RuntimeError,match="cannot erase"):command.downgrade(config,"0015")
    assert app.get_qa_run(p.id,c.id,prepared.run.id)==prepared.run



def test_sql_terminal_transition_cannot_hide_pending_selection(source_free):
    _,factory,engine,_,_,_,_,_=source_free;approve_source_free(source_free)
    record=transition(factory,stored(prepare(source_free)),"START")
    value=record.model_dump(mode="json");value["status"]="COMPLETED";value["finished_at"]=value["started_at"]
    with pytest.raises(IntegrityError),engine.begin() as db:
        db.execute(text("UPDATE browser_preparations SET status='COMPLETED',payload=:payload WHERE id=:id"),{"payload":json.dumps(value),"id":str(record.id)})
