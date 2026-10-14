"""Real migrated QA identities/evidence; offline scoped persistence and retrieval."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4
import pytest
from alembic import command as alembic
from sqlalchemy import text, select, inspect
from sqlalchemy.exc import IntegrityError
from qa_sentinel.application.experiences import ExperienceService, ExperienceError
from qa_sentinel.domain.experience import (CreateExperience, ExperienceQuery, ExperienceScope,
    ExperienceRecord, ExperienceKind, digest)
from qa_sentinel.persistence.database import create_engine, create_session_factory
from qa_sentinel.persistence.models import ExperienceRow, ExperienceSourceRow
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from test_qa_runs import ready, create, review
from test_qa_run_lifecycle import showcase
from test_browser_plan_generation import planning


@pytest.fixture
def history(ready):
    app, factory, engine, config, p, c, *_ = ready
    target = app.create_target(p.id, name="External", type="WEB", environment="STAGING",
        configuration={"base_url":"https://fixture.example"})
    app.associate_campaign_target(p.id, c.id, target_id=target.id)
    run = create(ready)
    app.start_qa_run(p.id, c.id, run.id)  # Existing deterministic SYNTHETIC executor.
    evidence = app.get_qa_run_results(p.id, c.id, run.id).tests.items[0].evidence.items[0]
    scope = ExperienceScope(project_id=p.id, campaign_id=c.id, target_id=target.id,
        target_snapshot_hash=digest(run.target_snapshot.model_dump(mode="json")))
    now = evidence.recorded_at+timedelta(seconds=2)
    service = ExperienceService(factory, clock=lambda:now)
    request = CreateExperience(scope=scope, idempotency_key=uuid4(), kind="QA_FAIL_CLASSIFICATION",
        evidence_ids=[evidence.id], freshness_seconds=60)
    return ready, run, evidence, scope, now, service, request


def query(history, **changes):
    return ExperienceQuery.model_validate({"scope":history[3], "kinds":list(ExperienceKind), **changes})


def seed_state(history, state="PROMOTED", **changes):
    # Explicit SQL fixture only. There is deliberately no production promotion API.
    source = history[5].create(history[6])
    data = source.model_dump(exclude={"content_hash"})
    data.update(id=uuid4(), idempotency_key=uuid4(), state=state, **changes)
    record = ExperienceRecord.seal(**data)
    with UnitOfWork(history[0][1]) as uow:
        uow.session.add(ExperienceRow(id=str(record.id), **{k:str(v) for k,v in record.scope.model_dump().items()},
            idempotency_key=str(record.idempotency_key),kind=record.kind,state=record.state,
            content_hash=record.content_hash,created_at=record.created_at,expires_at=record.expires_at,
            freshness_seconds=record.freshness_seconds,payload=record.model_dump(mode="json")))
        uow.session.flush()
        for i,ref in enumerate(record.references,1):
            uow.session.add(ExperienceSourceRow(experience_id=str(record.id),position=i,
                project_id=str(record.scope.project_id),campaign_id=str(record.scope.campaign_id),
                evidence_id=str(ref.evidence_id),run_id=str(ref.run_id),run_test_id=str(ref.run_test_id)))
        uow.commit()
    return record


def test_candidate_reopen_idempotency_immutable_and_zero_other_side_effects(history, monkeypatch):
    data, run, evidence, scope, _, service, request = history
    app, factory, engine, *_ = data
    def snapshot():
        with engine.connect() as db:
            return {table:db.execute(text(f'SELECT * FROM "{table}" ORDER BY rowid')).all()
                for table in inspect(engine).get_table_names() if table not in {"experiences","experience_sources"}}
    before = snapshot()
    import subprocess, socket
    from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
    from qa_sentinel.mutation.service import MutationService
    def forbidden(*args, **kwargs): raise AssertionError("Experience operation may not execute")
    for obj,name in [(subprocess,"Popen"),(socket.socket,"connect"),(OpenAIModelAdapter,"generate"),(MutationService,"apply")]:
        monkeypatch.setattr(obj,name,forbidden)
    record = service.create(request)
    assert record.state == "CANDIDATE" and record.references[0].evidence_id == evidence.id
    assert service.create(request) == record and service.get(scope, record.id) == record
    response = service.retrieve(query(history))
    assert not response.candidates and response.dispositions[0].reason == "NOT_PROMOTED"
    url = str(engine.url);engine.dispose(); reopened = create_engine(url)
    try:
        restarted = ExperienceService(create_session_factory(reopened))
        assert restarted.get(scope, record.id) == record
    finally: reopened.dispose()
    assert snapshot() == before
    with pytest.raises(IntegrityError),engine.begin() as db:
        db.execute(text("UPDATE experiences SET state='PROMOTED'"))
    with pytest.raises(IntegrityError),engine.begin() as db:
        db.execute(text("DELETE FROM experience_sources"))


@pytest.mark.parametrize("state", ["CANDIDATE","VALIDATED","SUPERSEDED","RETIRED","PROMOTED"])
def test_lifecycle_and_honest_advisory_projection(history, state):
    record = seed_state(history,state)
    result = history[5].retrieve(query(history))
    decision = next(d for d in result.dispositions if d.experience_id == record.id)
    assert decision.reason == ("RETURNED" if state=="PROMOTED" else "NOT_PROMOTED")
    if state=="PROMOTED":
        candidate=result.candidates[0]
        assert candidate.status == "UNVALIDATED_ADVISORY_CANDIDATE"
        assert candidate.references == record.references
        assert result.context_bytes == len(__import__('qa_sentinel.domain.qa_run',fromlist=['canonical_json']).canonical_json(result.advisory_context()))
        serialized=str(result.advisory_context())
        for forbidden in ["fixture.example", "Login", "selector", "browser_plan", "Test prose"]:
            assert forbidden not in serialized
        with UnitOfWork(history[0][1]) as uow:
            with pytest.raises(ValueError,match="candidate"): uow.experiences.add_candidate(record)


@pytest.mark.parametrize("change", ["kind", "scope", "sources", "freshness"])
def test_changed_idempotency_intent_conflicts(history, change):
    request=history[6];history[5].create(request)
    edits={"kind":dict(kind="PLAN_SEPARATION"),"scope":dict(scope=request.scope.model_copy(update={"target_snapshot_hash":"b"*64})),
        "sources":dict(evidence_ids=[uuid4()]),"freshness":dict(freshness_seconds=61)}[change]
    with pytest.raises(ExperienceError,match="EXPERIENCE_IDEMPOTENCY_CONFLICT"):
        history[5].create({**request.model_dump(),**edits})


def test_concurrent_idempotency_serialized_using_existing_writer_reservation(history):
    barrier=Barrier(2)
    def create_once():
        barrier.wait(timeout=5);return history[5].create(history[6])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:create_once(),range(2)))
    assert results[0]==results[1]
    with history[0][2].connect() as db:
        assert db.scalar(text('SELECT count(*) FROM experiences'))==1
        assert db.scalar(text('SELECT count(*) FROM experience_sources'))==1


@pytest.mark.parametrize("scope_field",["project_id","campaign_id","target_id","target_snapshot_hash"])
def test_no_cross_scope_get_retrieval_creation(history,scope_field):
    seed_state(history)
    scope=history[3].model_copy(update={scope_field:"f"*64 if scope_field.endswith("hash") else uuid4()})
    if scope_field.endswith("hash"):
        assert not history[5].retrieve(query(history,scope=scope)).candidates
        with pytest.raises(ExperienceError,match="INVALID_PROVENANCE"):
            history[5].create({**history[6].model_dump(),"scope":scope,"idempotency_key":uuid4()})
    else:
        with pytest.raises(ExperienceError,match="SCOPE_NOT_FOUND"):
            history[5].retrieve(query(history,scope=scope))
    with pytest.raises(ExperienceError):history[5].get(scope,uuid4())


def test_existing_foreign_campaign_and_target_are_never_scanned(history):
    app,_,_,_,p,*_=history[0]
    own=seed_state(history)
    other_campaign=app.create_campaign(p.id,name="Other")
    other_target=app.create_target(p.id,name="Other",type="WEB",environment="STAGING",configuration={"base_url":"https://other.example"})
    for change in [dict(campaign_id=other_campaign.id),dict(target_id=other_target.id)]:
        scope=history[3].model_copy(update=change)
        response=history[5].retrieve(query(history,scope=scope))
        assert not response.candidates and not response.dispositions
        assert str(own.id) not in response.model_dump_json()
        with pytest.raises(ExperienceError,match="INVALID_PROVENANCE"):
            history[5].create({**history[6].model_dump(),"scope":scope,"idempotency_key":uuid4()})


@pytest.mark.parametrize("seconds,reason", [(0,"RETURNED"),(57.999999,"RETURNED"),(58,"STALE"),(60,"STALE"),(-1,"STALE")])
def test_freshness_exact_source_age_and_creation_boundaries(history,seconds,reason):
    record=seed_state(history)
    service=ExperienceService(history[0][1],clock=lambda:history[4]+timedelta(seconds=seconds))
    result=service.retrieve(query(history))
    assert next(d.reason for d in result.dispositions if d.experience_id==record.id)==reason


def test_future_source_creation_and_clock_are_rejected(history):
    earlier=ExperienceService(history[0][1],clock=lambda:history[2].recorded_at-timedelta(microseconds=1))
    with pytest.raises(ExperienceError,match="INVALID_PROVENANCE"):earlier.create(history[6])
    invalid=ExperienceService(history[0][1],clock=lambda:datetime(2026,10,14))
    with pytest.raises(ExperienceError,match="INVALID_CLOCK"):invalid.retrieve(query(history))


@pytest.mark.parametrize("source_problem",["missing","test_content","run_hash","target","evidence_hash","reference_row"])
def test_tampered_or_missing_sources_are_ineligible(history,source_problem):
    record=seed_state(history)
    engine=history[0][2]
    if source_problem in {"evidence_hash","reference_row"}:
        # Privileged corruption simulation; normal writes remain trigger-protected.
        with engine.begin() as db:
            if source_problem=="reference_row":
                db.execute(text('DROP TRIGGER experience_sources_no_delete'))
                db.execute(text('DELETE FROM experience_sources WHERE experience_id=:id'),{"id":str(record.id)})
            else:
                db.execute(text('DROP TRIGGER experiences_no_update'))
                altered=ExperienceRecord.seal(**{**record.model_dump(exclude={"content_hash"}),"references":[record.references[0].model_copy(update={"evidence_hash":"0"*64})]})
                db.execute(ExperienceRow.__table__.update().where(ExperienceRow.id==str(record.id)).values(payload=altered.model_dump(mode="json"),content_hash=altered.content_hash))
    else:
        with engine.begin() as db:
            if source_problem=="missing":
                db.execute(text('DROP TRIGGER qa_run_evidence_no_delete'))
                # Removing the source is blocked by the new FK.
                # FK is intentionally deferred: commit, not DELETE, is the guard.
                db.execute(text('DELETE FROM qa_run_evidence'))
                with pytest.raises(IntegrityError): db.commit()
                db.rollback()
                return
            if source_problem == "target":
                with pytest.raises(IntegrityError):
                    db.execute(text("UPDATE qa_runs SET target_snapshot=json_set(target_snapshot,'$.target_id',:id)"), {"id":str(uuid4())})
                return  # Existing immutable snapshot guard is authoritative.
            sql={"test_content":"UPDATE qa_run_tests SET content=json_set(content,'$.title','Changed')",
                "run_hash":"UPDATE qa_runs SET snapshot_hash=:hash",
                "target":"UPDATE qa_runs SET target_snapshot=json_set(target_snapshot,'$.target_id',:id)"}[source_problem]
            db.execute(text(sql),{"hash":"0"*64,"id":str(uuid4())})
    result=history[5].retrieve(query(history))
    assert next(d.reason for d in result.dispositions if d.experience_id==record.id)=="INVALID_PROVENANCE"
    with pytest.raises(ExperienceError,match="INVALID_PROVENANCE"):history[5].get(history[3],record.id)


def test_corrupt_record_is_disclosed_without_payload_or_exception_leak(history):
    record=seed_state(history)
    with history[0][2].begin() as db:
        db.execute(text('DROP TRIGGER experiences_no_update'))
        db.execute(text("UPDATE experiences SET payload=json_set(payload,'$.secret','SECRET-CANARY'),content_hash=content_hash WHERE id=:id"),{"id":str(record.id)})
    result=history[5].retrieve(query(history))
    assert next(d.reason for d in result.dispositions if d.experience_id==record.id)=="INVALID_RECORD"
    assert "SECRET" not in result.model_dump_json()
    with pytest.raises(ExperienceError) as error: history[5].get(history[3],record.id)
    assert str(error.value)=="EXPERIENCE_INVALID_PROVENANCE" and "SECRET" not in str(error.value)


def test_bounded_windows_result_limits_bytes_and_stable_order(history):
    records=[seed_state(history) for _ in range(6)]
    result=history[5].retrieve(query(history,scan_limit=3,limit=1))
    assert len(result.dispositions)==3 and result.scan_limited and result.next_after_id
    assert [str(d.experience_id) for d in result.dispositions]==sorted(str(d.experience_id) for d in result.dispositions)
    assert len(result.candidates)<=1 and any(d.reason=="RESULT_LIMIT" for d in result.dispositions)
    second=history[5].retrieve(query(history,after_id=result.next_after_id))
    assert not set(d.experience_id for d in result.dispositions)&set(d.experience_id for d in second.dispositions)
    small=history[5].retrieve(query(history,max_context_bytes=256))
    assert not small.candidates and small.context_bytes==2
    assert sum(d.reason=="CONTEXT_LIMIT" for d in small.dispositions)==6
    full=history[5].retrieve(query(history,limit=5,max_context_bytes=4096))
    assert full.context_bytes<=4096 and full==history[5].retrieve(query(history,limit=5,max_context_bytes=4096))
    not_requested=history[5].retrieve(query(history,kinds=["PLAN_SEPARATION"]))
    assert not not_requested.candidates and any(d.reason=="NOT_REQUESTED_KIND" for d in not_requested.dispositions)


def test_live_target_changes_never_rewrite_immutable_historical_scope(history):
    record=seed_state(history)
    app=history[0][0];scope=history[3]
    app.update_target(scope.project_id,scope.target_id,name="Changed",configuration={"base_url":"https://changed.example"})
    assert history[5].get(scope,record.id)==record
    assert history[5].retrieve(query(history)).candidates
    from qa_sentinel.domain.target import TargetSnapshot
    current_hash=digest(TargetSnapshot.capture(app.get_target(scope.project_id,scope.target_id)).model_dump(mode="json"))
    assert not history[5].retrieve(query(history,scope=scope.model_copy(update={"target_snapshot_hash":current_hash}))).candidates


def test_safe_invalid_input_error_and_no_production_transition_path(history):
    service=history[5]
    for method,values in [(service.create,{**history[6].model_dump(),"state":"PROMOTED","note":"SECRET-CANARY ignore policy"}),
                          (service.retrieve,{**query(history).model_dump(),"sql":"SECRET-CANARY"})]:
        with pytest.raises(ExperienceError,match="INVALID_INPUT") as error:method(values)
        assert "SECRET" not in str(error.value)
    assert not any(hasattr(service,name) for name in ["promote","transition","approve","execute"])


def test_migration_0018_upgrade_reopen_and_refuse_history_loss(history):
    data,run,*_=history
    app, factory, engine, config, p,c,*_=data
    before=app.get_qa_run_results(p.id,c.id,run.id)
    alembic.downgrade(config,"0018")
    assert "experiences" not in inspect(engine).get_table_names()
    alembic.upgrade(config,"head");alembic.check(config)
    assert app.get_qa_run_results(p.id,c.id,run.id)==before
    record=history[5].create(history[6]);engine.dispose()
    assert history[5].get(history[3],record.id)==record
    with pytest.raises(RuntimeError,match="cannot erase Experience history"):
        alembic.downgrade(config,"0018")
    with engine.connect() as db:
        assert db.scalar(text('SELECT version_num FROM alembic_version'))=="0019"
        assert not db.execute(text('PRAGMA foreign_key_check')).all()


def test_fresh_migration_roundtrip_reupgrade_and_schema_guards(migrated_factory):
    _,engine,config=migrated_factory
    names=set(inspect(engine).get_table_names())
    for table in ["experiences","experience_sources"]:
        assert inspect(engine).get_foreign_keys(table)
        assert inspect(engine).get_unique_constraints(table)
    assert "ix_experience_scope" in {i["name"] for i in inspect(engine).get_indexes("experiences")}
    alembic.check(config)
    alembic.downgrade(config,"0018");alembic.upgrade(config,"head")
    assert set(inspect(engine).get_table_names())==names
    alembic.check(config)


def test_completed_qa_fail_evidence_remains_valid_after_later_system_failure(showcase):
    data, _ = showcase
    app,factory,_,_,p,c,*_=data
    target=app.create_target(p.id,name="Fixture",type="WEB",environment="STAGING",configuration={"base_url":"https://fixture.example"})
    app.associate_campaign_target(p.id,c.id,target_id=target.id)
    run=create(data,"partial-experience")
    from qa_sentinel.execution.synthetic_run import SyntheticRunExecutor
    class Partial(SyntheticRunExecutor):
        def evaluate(self,test):
            if test.position==3: raise RuntimeError("secret failure must not enter experience")
            return super().evaluate(test)
    app._synthetic_run_executor=Partial()
    final=app.start_qa_run(p.id,c.id,run.id)
    assert final.execution_status=="FAILED"
    evidence=app.get_qa_run_results(p.id,c.id,run.id).tests.items[1].evidence.items[0]
    scope=ExperienceScope(project_id=p.id,campaign_id=c.id,target_id=target.id,target_snapshot_hash=digest(run.target_snapshot.model_dump(mode="json")))
    service=ExperienceService(factory,clock=lambda:evidence.recorded_at+timedelta(seconds=2))
    record=service.create(CreateExperience(scope=scope,idempotency_key=uuid4(),kind="QA_FAIL_CLASSIFICATION",evidence_ids=[evidence.id]))
    assert record.references[0].qa_result=="FAIL" and record.references[0].executor_kind=="SYNTHETIC"
    assert "secret" not in record.model_dump_json()


def test_multiple_canonical_references_and_reordered_idempotent_input(history):
    from qa_sentinel.execution.synthetic_run import execute_synthetic, SyntheticRunExecutor
    from qa_sentinel.domain.qa_run_evidence import TestExecutionResult
    data=history[0];app,factory,_,_,p,c,*_=data
    run=create(data,"multiple-evidence")
    with UnitOfWork(factory) as uow:
        running=uow.qa_runs.start(run)
        test=uow.qa_runs.start_test(running,uow.qa_runs.all_entries(run,"tests")[0])
        result=execute_synthetic(SyntheticRunExecutor(),test)
        uow.qa_runs.complete_test(running,test,TestExecutionResult(qa_result=result.qa_result,evidence=result.evidence*4))
        uow.qa_runs.finish(running);uow.commit()
    evidence=app.get_qa_run_results(p.id,c.id,run.id).tests.items[0].evidence.items
    now=max(e.recorded_at for e in evidence)+timedelta(seconds=2)
    service=ExperienceService(factory,clock=lambda:now)
    request=CreateExperience(scope=history[3],idempotency_key=uuid4(),kind="EVIDENCE_COMPLETENESS",evidence_ids=[e.id for e in evidence])
    record=service.create(request)
    assert len(record.references)==4
    assert [str(r.evidence_id) for r in record.references]==sorted(str(e.id) for e in evidence)
    assert service.create({**request.model_dump(),"evidence_ids":tuple(reversed(request.evidence_ids))})==record
    assert service.get(history[3],record.id)==record


def test_db_foreign_keys_unique_and_source_identity_guards(history):
    record=history[5].create(history[6]);engine=history[0][2]
    app=history[0][0]
    foreign=app.create_project(key="foreign",name="Foreign")
    foreign_target=app.create_target(foreign.id,name="Foreign",type="WEB",environment="STAGING",configuration={"base_url":"https://foreign.example"})
    with engine.connect() as db:
        values=db.execute(select(ExperienceRow).where(ExperienceRow.id==str(record.id))).mappings().one()
    # Same key and a new identity cannot silently insert duplicate intent.
    duplicate=ExperienceRecord.seal(**{**record.model_dump(exclude={"content_hash"}),"id":uuid4()})
    with pytest.raises(IntegrityError,match="idempotency_key"),engine.begin() as db:
        db.execute(ExperienceRow.__table__.insert().values(**{**values,"id":str(duplicate.id),
            "payload":duplicate.model_dump(mode="json"),"content_hash":duplicate.content_hash}))
    for sql,params in [("DELETE FROM targets_under_test WHERE id=:id",{"id":str(history[3].target_id)}),
                       ("DELETE FROM qa_campaigns WHERE id=:id",{"id":str(history[3].campaign_id)})]:
        with pytest.raises(IntegrityError),engine.begin() as db:db.execute(text(sql),params)
    with pytest.raises(IntegrityError),engine.begin() as db:
        db.execute(ExperienceSourceRow.__table__.insert().values(experience_id=str(record.id),position=2,
            project_id=str(history[3].project_id),campaign_id=str(history[3].campaign_id),
            evidence_id=str(uuid4()),run_id=str(history[1].id),run_test_id=str(record.references[0].run_test_id)))
    with UnitOfWork(history[0][1]) as uow:
        bad=ExperienceRecord.seal(**{**record.model_dump(exclude={"content_hash"}),"id":uuid4(),"idempotency_key":uuid4(),
            "scope":record.scope.model_copy(update={"target_id":foreign_target.id})})
        uow.experiences.add_candidate(bad)
        with pytest.raises(IntegrityError):uow.commit()


def test_query_counts_are_explicitly_bounded_no_unbounded_source_scan(history):
    from sqlalchemy import event
    for _ in range(3):seed_state(history)
    reads=[]
    def collect(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith("SELECT"): reads.append(statement)
    event.listen(history[0][2],"before_cursor_execute",collect)
    try:result=history[5].retrieve(query(history,scan_limit=2))
    finally:event.remove(history[0][2],"before_cursor_execute",collect)
    assert len(result.dispositions)==2 and result.scan_limited
    # Scope (3), bounded identities/payload (2), at most two provenance checks (2 each).
    assert len(reads)<=9
    assert any("LIMIT" in statement and "experiences.id" in statement for statement in reads)


def test_safe_database_failure_never_leaks_raw_exception(history):
    from sqlalchemy import event
    def fail(conn,cursor,statement,parameters,context,executemany):
        if "FROM experiences" in statement: raise __import__('sqlalchemy').exc.OperationalError("SECRET SQL",{},Exception("SECRET raw path"))
    event.listen(history[0][2],"before_cursor_execute",fail)
    try:
        with pytest.raises(ExperienceError) as error:history[5].retrieve(query(history))
    finally:event.remove(history[0][2],"before_cursor_execute",fail)
    assert str(error.value)=="EXPERIENCE_PERSISTENCE_ERROR" and "SECRET" not in str(error.value)


def test_stale_creation_missing_source_and_replay_after_tamper_fail_closed(history):
    late=ExperienceService(history[0][1],clock=lambda:history[2].recorded_at+timedelta(seconds=60))
    with pytest.raises(ExperienceError,match="STALE_SOURCE"):late.create(history[6])
    with pytest.raises(ExperienceError,match="INVALID_PROVENANCE"):
        history[5].create({**history[6].model_dump(),"evidence_ids":[uuid4()]})
    record=history[5].create(history[6])
    with history[0][2].begin() as db:db.execute(text("UPDATE qa_runs SET snapshot_hash=:h"),{"h":"0"*64})
    with pytest.raises(ExperienceError,match="INVALID_PROVENANCE"):history[5].create(history[6])


def test_future_sealed_record_remains_ineligible_and_missing_source_detected(history):
    later=history[4]+timedelta(seconds=5)
    record=seed_state(history,created_at=later,expires_at=later+timedelta(seconds=60))
    result=history[5].retrieve(query(history))
    assert next(d.reason for d in result.dispositions if d.experience_id==record.id)=="STALE"
    # Simulate offline privileged damage on the disposable database only.
    engine=history[0][2]
    with engine.connect() as db:
        db.connection.driver_connection.execute("PRAGMA foreign_keys=OFF")
        try:
            db.execute(text('DROP TRIGGER qa_run_evidence_no_delete'))
            db.execute(text('DELETE FROM qa_run_evidence'));db.commit()
        finally:db.connection.driver_connection.execute("PRAGMA foreign_keys=ON")
    later_service=ExperienceService(history[0][1],clock=lambda:later)
    result=later_service.retrieve(query(history))
    assert next(d.reason for d in result.dispositions if d.experience_id==record.id)=="INVALID_PROVENANCE"


def test_utc_offset_creation_replay_and_persisted_times_match(history):
    local_now=history[4].astimezone(timezone(timedelta(hours=7)))
    service=ExperienceService(history[0][1],clock=lambda:local_now)
    record=service.create(history[6])
    assert record.created_at.utcoffset()==timedelta(0)
    assert history[5].create(history[6])==record
    with UnitOfWork(history[0][1]) as uow:assert uow.experiences.get(history[3],record.id)==record


def test_real_browser_contract_provenance_with_mock_execution_and_zero_retrieval_calls(planning,monkeypatch):
    app,factory,_,_,p,c,spec,mock,executor,target=planning
    generation=app.generate_browser_plan(p.id,c.id,spec.id)  # Offline mock provider fixture.
    run=app.accept_browser_plan_generation(p.id,c.id,generation.id,idempotency_key="experience-fixture")
    app.start_browser_qa_run(p.id,c.id,run.id)  # Existing fake executor, not Chromium.
    evidence=app.get_qa_run_results(p.id,c.id,run.id).tests.items[0].evidence.items[0]
    assert evidence.source=="web-browser" and len(mock.calls)==1
    from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
    import subprocess,socket
    def forbidden(*args,**kwargs):raise AssertionError("Store must not use model/browser/network/process")
    monkeypatch.setattr(OpenAIModelAdapter,"generate",forbidden)
    monkeypatch.setattr(executor,"execute",forbidden)
    monkeypatch.setattr(subprocess,"Popen",forbidden)
    monkeypatch.setattr(socket,"getaddrinfo",forbidden)
    scope=ExperienceScope(project_id=p.id,campaign_id=c.id,target_id=target.id,target_snapshot_hash=digest(run.target_snapshot.model_dump(mode="json")))
    service=ExperienceService(factory,clock=lambda:evidence.recorded_at+timedelta(seconds=2))
    record=service.create(CreateExperience(scope=scope,idempotency_key=uuid4(),kind="APPROVAL_PROVENANCE",evidence_ids=[evidence.id]))
    assert record.references[0].executor_kind=="WEB_BROWSER"
    assert record.references[0].run_snapshot_hash==run.snapshot_hash
    assert service.get(scope,record.id)==record
    assert not service.retrieve(ExperienceQuery(scope=scope,kinds=["APPROVAL_PROVENANCE"])).candidates
    assert len(mock.calls)==1
    serialized=record.model_dump_json()
    assert "example.com" not in serialized and "Courses" not in serialized and "locator" not in serialized


def test_immutable_run_metadata_tamper_detected_even_without_changing_snapshot_hash(history):
    record=seed_state(history)
    with history[0][2].begin() as db:
        db.execute(text("UPDATE qa_runs SET idempotency_key='tampered-intent'"))
    result=history[5].retrieve(query(history))
    assert next(d.reason for d in result.dispositions if d.experience_id==record.id)=="INVALID_PROVENANCE"
