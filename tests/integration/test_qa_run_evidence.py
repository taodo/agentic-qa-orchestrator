"""Offline evidence atomicity, bounded reads, ownership and migration durability."""
from uuid import uuid4
import pytest
from pydantic import ValidationError
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from alembic import command
from fastapi.testclient import TestClient
from qa_sentinel.api import create_api_app
from qa_sentinel.application import ApplicationError
from qa_sentinel.domain.qa_run_evidence import EvidenceDraft, QARunEvidence, TestExecutionResult as ResultContract
from qa_sentinel.domain.evidence_variants import SyntheticObservation, SyntheticEvidencePolicy
from qa_sentinel.execution.synthetic_run import SyntheticRunExecutor, execute_synthetic
from qa_sentinel.persistence.models import QARunEvidenceRow
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from test_qa_runs import ready, create, review
from test_qa_run_lifecycle import showcase, start, entries


def result_view(ready, run, **kwargs):
    app, _, _, _, p, c, _, _ = ready
    return app.get_qa_run_results(p.id, c.id, run.id, **kwargs)


def test_fail_continues_with_evidence_durable_before_next_test(showcase):
    ready, run = showcase
    app, _, engine, _, p, c, _, _ = ready
    observed = []
    class Recording(SyntheticRunExecutor):
        def evaluate(self, snapshot):
            saved = result_view(ready, run)
            assert saved.run.execution_status == 'RUNNING'
            for earlier in saved.tests.items[:snapshot.position-1]:
                assert earlier.execution_status == 'COMPLETED' and earlier.evidence_count == 1
                assert earlier.evidence.items[0].payload.outcome == earlier.qa_result
            observed.append(snapshot.position)
            return super().evaluate(snapshot)
    app._synthetic_run_executor = Recording()
    final = start(ready, run)
    view = result_view(ready, run)
    assert (final.execution_status, final.qa_outcome) == ('COMPLETED','FAIL')
    assert observed == [1,2,3] and [t.qa_result for t in view.tests.items] == ['PASS','FAIL','PASS']
    assert view.summary.model_dump() == dict(total=3,completed=3,passed=2,failed=1,skipped=0,not_evaluated=0,remaining=0)
    for test in view.tests.items:
        record = test.evidence.items[0]
        assert (record.project_id,record.campaign_id,record.run_id,record.run_test_id) == (p.id,c.id,run.id,test.id)
        assert record.source == 'synthetic' and record.sequence == 1
        assert record.payload.strategy == 'synthetic-position-v1' and record.payload.position == test.position
        assert record.summary == record.payload.safe_summary() and 'No external target' in record.summary
    engine.dispose()
    assert result_view(ready, run) == view


@pytest.mark.parametrize('position',[1,3])
def test_system_failure_retains_earlier_results_and_evidence(showcase,position):
    ready,run = showcase
    class Broken(SyntheticRunExecutor):
        def evaluate(self,snapshot):
            if snapshot.position == position: raise RuntimeError('SECRET raw exception')
            return super().evaluate(snapshot)
    ready[0]._synthetic_run_executor = Broken()
    start(ready,run)
    view = result_view(ready,run)
    assert view.run.execution_status == 'FAILED'
    assert view.run.qa_outcome == ('PARTIAL' if position>1 else 'NOT_EVALUATED')
    assert [t.evidence_count for t in view.tests.items] == [int(i<position) for i in [1,2,3]]
    assert view.summary.completed == position-1 and view.summary.remaining == 4-position
    assert view.tests.items[position-1].execution_status == 'RUNNING'
    assert 'SECRET' not in view.model_dump_json()


def test_evidence_insert_failure_rolls_back_same_test_result(showcase):
    ready,run = showcase
    def fail(mapper,connection,target):
        if target.payload['position'] == 2: raise RuntimeError('SECRET persistence failure')
    event.listen(QARunEvidenceRow,'before_insert',fail)
    try: start(ready,run)
    finally: event.remove(QARunEvidenceRow,'before_insert',fail)
    view=result_view(ready,run)
    assert (view.run.execution_status,view.run.qa_outcome)==('FAILED','PARTIAL')
    assert [(t.execution_status,t.qa_result,t.evidence_count) for t in view.tests.items] == [
        ('COMPLETED','PASS',1),('RUNNING','NOT_EVALUATED',0),('NOT_STARTED','NOT_EVALUATED',0)]


def test_bounded_ordered_evidence_preview_and_explicit_pages(ready):
    app,factory,_,_,p,c,_,_=ready
    run=create(ready)
    with UnitOfWork(factory) as uow:
        running=uow.qa_runs.start(run)
        test=uow.qa_runs.start_test(running,uow.qa_runs.all_entries(run,'tests')[0])
        result=execute_synthetic(SyntheticRunExecutor(),test)
        uow.qa_runs.complete_test(running,test,ResultContract(qa_result=result.qa_result,evidence=result.evidence*7))
        uow.qa_runs.finish(running)
        uow.commit()
    view=result_view(ready,run,limit=1)
    test=view.tests.items[0]
    assert test.evidence_count==7 and test.evidence.truncated
    assert [e.sequence for e in test.evidence.items]==[1,2,3,4,5]
    first=app.list_qa_run_test_evidence(p.id,c.id,run.id,test.id,limit=2)
    second=app.list_qa_run_test_evidence(p.id,c.id,run.id,test.id,limit=2,after_sequence=2)
    assert [e.sequence for e in first.items]==[1,2] and first.truncated
    assert [e.sequence for e in second.items]==[3,4] and second.truncated
    assert app.list_qa_run_test_evidence(p.id,c.id,run.id,test.id,after_sequence=7).items==()


@pytest.mark.parametrize('change',[
    {'summary':'secret environment dump'}, {'summary':'x'*513}, {'source':'browser'},
    {'payload':{'strategy':'synthetic-position-v1','position':1001,'outcome':'PASS'}},
    {'payload':{'strategy':'synthetic-position-v1','position':1,'outcome':'PASS','authorization':'secret'}},
    {'payload':{'strategy':'synthetic-position-v1','position':1,'outcome':'NOT_EVALUATED'}},
    {'payload':{'strategy':'synthetic-position-v1','position':1,'outcome':'PASS','path':'C:/secret'}},
    {'payload':{'variant':'unreviewed','strategy':'synthetic-position-v1','position':1,'outcome':'PASS'}},
    {'payload':{'strategy':'unsupported','position':1,'outcome':'PASS'}},
])
def test_closed_safe_payload_contract_rejects_unbounded_or_untrusted_data(change):
    observation=SyntheticObservation(position=1,outcome='PASS')
    data=EvidenceDraft(source="synthetic", payload=observation,summary=observation.safe_summary()).model_dump()
    with pytest.raises(ValidationError): EvidenceDraft.model_validate({**data,**change})


def test_result_bounds_and_frozen_contract():
    observation=SyntheticObservation(position=1,outcome='FAIL')
    draft=EvidenceDraft(source="synthetic", payload=observation,summary=observation.safe_summary())
    with pytest.raises(ValidationError): draft.summary='Changed'
    for result,evidence in [('PASS',(draft,)),('FAIL',()),('FAIL',(draft,)*21),('NOT_EVALUATED',(draft,))]:
        with pytest.raises(ValidationError): ResultContract(qa_result=result,evidence=evidence)


def test_immutable_and_composite_ownership_enforced_in_storage(ready):
    app,_,engine,_,p,c,_,_=ready
    run=create(ready);start(ready,run)
    item=result_view(ready,run).tests.items[0].evidence.items[0]
    for action in ['UPDATE qa_run_evidence SET summary=summary','DELETE FROM qa_run_evidence']:
        with pytest.raises(IntegrityError,match='immutable'),engine.begin() as connection:
            connection.execute(text(action))
    with pytest.raises(ValidationError): item.summary='Changed'
    for change in [{'run_id':str(uuid4())},{'run_test_id':str(uuid4())},{'campaign_id':str(uuid4())},{'project_id':str(uuid4())},{'sequence':21},{'summary':'x'*513},{'payload':{'padding':'x'*2049}}]:
        values={**item.model_dump(mode='json', exclude={'presentation'}),'id':str(uuid4()),'sequence':2,**change}
        with pytest.raises(IntegrityError),engine.begin() as connection:
            connection.execute(QARunEvidenceRow.__table__.insert().values(**values))
    assert result_view(ready,run).tests.items[0].evidence.items==(item,)


def test_scoped_bounded_api_and_constant_query_count_without_live_reads(showcase,monkeypatch):
    ready,run=showcase
    app,_,engine,_,p,c,_,_=ready
    start(ready,run)
    import subprocess,socket
    original_connect=socket.socket.connect
    from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
    from qa_sentinel.mutation.service import MutationService
    from qa_sentinel.persistence.test_specifications import TestSpecificationRepository
    def forbidden(*args,**kwargs): raise AssertionError('External or live preparation read forbidden')
    for obj,name in [(subprocess,'Popen'),(socket.socket,'connect'),(OpenAIModelAdapter,'generate'),(MutationService,'apply'),(TestSpecificationRepository,'specifications')]:
        monkeypatch.setattr(obj,name,forbidden)
    counts=[]
    for limit in [1,3]:
        queries=[]
        def record(connection,cursor,statement,parameters,context,executemany):
            if statement.lstrip().upper().startswith('SELECT'):queries.append(statement)
        event.listen(engine,'before_cursor_execute',record)
        try: view=result_view(ready,run,limit=limit)
        finally:event.remove(engine,'before_cursor_execute',record)
        counts.append(len(queries))
        assert view.summary.total==3 and len(view.tests.items)==limit
        assert view.tests.truncated==(limit==1)
    assert counts[0]==counts[1] and counts[0]<=8
    other=app.create_campaign(p.id,name='Other')
    with pytest.raises(ApplicationError,match='RUN_CAMPAIGN_MISMATCH'):app.get_qa_run_results(p.id,other.id,run.id)
    foreign=app.create_project(key='foreign',name='Foreign')
    foreign_campaign=app.create_campaign(foreign.id,name='Foreign')
    with pytest.raises(ApplicationError,match='RUN_NOT_FOUND'):app.get_qa_run_results(foreign.id,foreign_campaign.id,run.id)
    path=f'/api/v1/projects/{p.id}/campaigns/{c.id}/runs/{run.id}'
    # Windows event-loop setup uses an internal socketpair; guard app reads after setup.
    monkeypatch.setattr(socket.socket,'connect',original_connect)
    with TestClient(create_api_app(app)) as client:
        monkeypatch.setattr(socket.socket,'connect',forbidden)
        data=client.get(path+'/results?limit=1').json()
        assert data['summary']['total']==3 and data['tests']['truncated']
        test=data['tests']['items'][0]
        assert test['evidence_count']==1 and test['qa_result']=='PASS'
        projection=test['evidence']['items'][0]['presentation']
        assert projection['variant']=='synthetic-observation-v1' and projection['display_label']=='SYNTHETIC'
        assert projection['details'][1]=={'label':'Snapshot position','value':'1'}
        explicit=client.get(path+f"/tests/{test['id']}/evidence").json()
        assert explicit['total_returned']==1 and explicit['items'][0]['presentation']==projection
        assert client.get(path+f'/tests/{uuid4()}/evidence').json()['error']['code']=='RUN_NOT_FOUND'
        assert client.get(path+'/results?limit=201').status_code==422
        assert client.get(path+'/results?after_position=-1').status_code==422
        assert client.get(path+f"/tests/{test['id']}/evidence?after_sequence=21").status_code==422


def test_0011_upgrade_reopen_empty_downgrade_and_evidence_guard(ready):
    app,_,engine,config,p,c,_,_=ready
    historical=create(ready)
    before=entries(ready,historical)
    command.downgrade(config,'0010')
    assert app.get_qa_run(p.id,c.id,historical.id)==historical
    command.upgrade(config,'head');command.check(config)
    engine.dispose()
    assert entries(ready,historical)==before
    assert result_view(ready,historical).summary.remaining==1
    assert result_view(ready,historical).tests.items[0].evidence_count==0
    command.downgrade(config,'0010');command.upgrade(config,'head')
    start(ready,historical)
    saved=result_view(ready,historical)
    with pytest.raises(RuntimeError,match='cannot erase persisted Run evidence'):command.downgrade(config,'0010')
    assert result_view(ready,historical)==saved
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version'))=='0011'
        assert not connection.exec_driver_sql('PRAGMA foreign_key_check').all()


def test_historical_completed_0010_run_gets_no_fabricated_evidence(ready):
    from qa_sentinel.domain.qa_run_lifecycle import finish_test
    from qa_sentinel.application import QASentinelApplication, ProjectExecutionResolver
    from qa_sentinel.projects import ProjectRuntimeRegistry
    from qa_sentinel.persistence.database import create_engine, create_session_factory
    app,factory,engine,config,p,c,_,_=ready
    run=create(ready)
    command.downgrade(config,'0010')
    # Reproduce the accepted pre-evidence lifecycle in the old schema only.
    with UnitOfWork(factory) as uow:
        running=uow.qa_runs.start(run)
        test=uow.qa_runs.start_test(running,uow.qa_runs.all_entries(run,'tests')[0])
        uow.qa_runs._save_test_state(running,test,finish_test(test,'FAIL'))
        historical=uow.qa_runs.finish(running)
        uow.commit()
    before=entries(ready,historical)
    command.upgrade(config,'head');command.check(config)
    url=str(engine.url);engine.dispose()
    reopened=create_engine(url)
    try:
        restarted=QASentinelApplication(create_session_factory(reopened),ProjectExecutionResolver(ProjectRuntimeRegistry([]),[]))
        view=restarted.get_qa_run_results(p.id,c.id,run.id)
        assert view.run==historical and view.run.qa_outcome=='FAIL'
        assert view.tests.items[0].model_dump(exclude={'evidence_count','evidence'})==before[0].model_dump()
        assert view.summary.completed==view.summary.failed==1 and view.summary.remaining==0
        assert view.tests.items[0].evidence_count==0 and not view.tests.items[0].evidence.items
    finally:reopened.dispose()


def test_common_result_persistence_and_reads_access_variant_fields_only_inside_policy(ready, monkeypatch):
    from contextvars import ContextVar
    from functools import wraps
    inside_policy = ContextVar('inside_evidence_policy', default=False)
    original_getattribute = SyntheticObservation.__getattribute__
    def guarded(payload, name):
        if name in {'position','outcome','strategy'} and not inside_policy.get():
            raise AssertionError('Generic infrastructure accessed variant-specific field')
        return original_getattribute(payload, name)
    def scoped(original):
        @wraps(original)
        def wrapped(*args, **kwargs):
            token = inside_policy.set(True)
            try: return original(*args, **kwargs)
            finally: inside_policy.reset(token)
        return wrapped
    observation = SyntheticObservation(position=1, outcome='FAIL')
    summary = observation.safe_summary()
    for name in ['validate_identity','validate_envelope','validate_result','validate_snapshot','presentation']:
        monkeypatch.setattr(SyntheticEvidencePolicy, name, scoped(getattr(SyntheticEvidencePolicy,name)))
    monkeypatch.setattr(SyntheticObservation, '__getattribute__', guarded)
    app,factory,_,_,p,c,_,_=ready
    run=create(ready)
    result=ResultContract(qa_result='FAIL', evidence=(EvidenceDraft(source='synthetic',payload=observation,summary=summary),))
    with UnitOfWork(factory) as uow:
        running=uow.qa_runs.start(run)
        test=uow.qa_runs.start_test(running,uow.qa_runs.all_entries(run,'tests')[0])
        uow.qa_runs.complete_test(running,test,result)
        uow.qa_runs.finish(running)
        uow.commit()
    view=result_view(ready,run)
    assert view.run.execution_status=='COMPLETED' and view.summary.failed==1
    record=view.tests.items[0].evidence.items[0]
    assert record.presentation.display_label=='SYNTHETIC'
    assert record.presentation.variant=='synthetic-observation-v1'
    assert record.presentation.details[1].value=='1'
    assert app.list_qa_run_test_evidence(p.id,c.id,run.id,test.id).items==(record,)


def test_synthetic_snapshot_mismatch_rejects_before_result_update(ready):
    app,factory,_,_,p,c,_,_=ready
    run=create(ready)
    observation=SyntheticObservation(position=2,outcome='FAIL')
    result=ResultContract(qa_result='FAIL',evidence=(EvidenceDraft(source='synthetic',payload=observation,summary=observation.safe_summary()),))
    with UnitOfWork(factory) as uow:
        running=uow.qa_runs.start(run)
        test=uow.qa_runs.start_test(running,uow.qa_runs.all_entries(run,'tests')[0])
        uow.commit()
    with pytest.raises(ValueError,match='snapshot'),UnitOfWork(factory) as uow:
        uow.qa_runs.complete_test(running,test,result)
        uow.commit()
    view=result_view(ready,run)
    assert view.tests.items[0].qa_result=='NOT_EVALUATED'
    assert view.tests.items[0].execution_status=='RUNNING' and view.tests.items[0].evidence_count==0


def test_legacy_0011_payload_without_discriminator_projects_without_storage_rewrite(ready):
    from qa_sentinel.domain.qa_run_lifecycle import finish_test
    from sqlalchemy import select
    _,factory,engine,_,p,c,_,_=ready
    run=create(ready)
    with UnitOfWork(factory) as uow:
        running=uow.qa_runs.start(run)
        test=uow.qa_runs.start_test(running,uow.qa_runs.all_entries(run,'tests')[0])
        draft=execute_synthetic(SyntheticRunExecutor(),test).evidence[0]
        record=QARunEvidence(**draft.model_dump(),project_id=p.id,campaign_id=c.id,run_id=run.id,run_test_id=test.id,sequence=1)
        values=record.model_dump(mode='json')
        values['payload'].pop('variant')
        uow.qa_runs._save_test_state(running,test,finish_test(test,'PASS'))
        uow.session.add(QARunEvidenceRow(**values))
        uow.qa_runs.finish(running)
        uow.commit()
    view=result_view(ready,run)
    saved=view.tests.items[0].evidence.items[0]
    assert saved.payload.variant=='synthetic-observation-v1' and saved.presentation.display_label=='SYNTHETIC'
    assert 'No external target was tested.' in saved.summary
    with engine.connect() as connection:
        assert connection.scalar(select(QARunEvidenceRow.payload))==values['payload']
