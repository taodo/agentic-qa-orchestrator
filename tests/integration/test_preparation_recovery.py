"""Offline recovery, independent attempts/usage and evidence-driven immutable revisions."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4
import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import text
from qa_sentinel.api import create_api_app
from qa_sentinel.application import ApplicationError, QASentinelApplication, ProjectExecutionResolver
from qa_sentinel.projects import ProjectRuntimeRegistry
from qa_sentinel.models.base import ModelError, ProviderErrorCategory
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from test_requirement_extraction import harness, put, response
from test_campaign_test_specifications import case, csv_text, seed_requirement


def setup_failure(harness):
    app,_,_,p,c,mock,_=harness
    mock.queue.clear(); mock.queue.extend([lambda call:response(call,invalid=True),response])
    source=put(app,p,c)
    first=app.extract_campaign_requirements(p.id,c.id,source.id)
    assert first.error_code=='EXTRACTION_INVALID_CITATION' and first.retryable
    return source,first


def revised(call, *, markers=False, original_only=False, wrong_key=False):
    data=json.loads(call['input'][0]['content'])
    result=response(call,markers=markers)
    line=1 if original_only else data['clarification_first_fact_line']
    result['requirements'][0]['source_references'][0].update(start_line=line,end_line=line,excerpt=data['normalized_text'].split('\n')[line-1][:512])
    if wrong_key: result['requirements'][0]['key']='INVENTED'
    return result


def setup_requirement(harness):
    app,_,_,p,c,mock,_=harness
    mock.queue.clear();mock.queue.append(lambda call:response(call,markers=True))
    source=put(app,p,c)
    app.extract_campaign_requirements(p.id,c.id,source.id)
    requirement=app.list_campaign_requirements(p.id,c.id).items[0]
    return source,requirement


def test_retry_preserves_failure_initial_intent_and_independent_usage(harness):
    app,factory,engine,p,c,mock,_=harness
    source,first=setup_failure(harness)
    second=app.retry_campaign_extraction(p.id,c.id,first.id)
    assert second.id!=first.id and second.parent_attempt_id==first.id and second.attempt_number==2 and second.status=='SUCCEEDED'
    assert second.usage.total_tokens.total==first.usage.total_tokens.total==30
    usage = app.get_campaign_model_usage(p.id,c.id)
    assert usage.usage.total_tokens.total==60
    assert [(r.id,r.is_latest) for r in usage.invocations]==[(first.id,False),(second.id,True)]
    assert not app.get_campaign_model_usage(p.id,c.id,limit=1).invocations[0].is_latest
    assert app.extract_campaign_requirements(p.id,c.id,source.id).id==first.id
    assert app.retry_campaign_extraction(p.id,c.id,first.id).id==second.id and len(mock.calls)==2
    history=app.list_campaign_extraction_attempts(p.id,c.id,source.id).items
    assert history[0]==second and history[1].id==first.id and not history[1].is_latest
    assert history[1].model_dump(exclude={'is_latest'})==first.model_dump(exclude={'is_latest'})
    assert app.list_campaign_sources(p.id,c.id).items[0].latest_extraction==second
    engine.dispose()
    restarted=QASentinelApplication(factory,ProjectExecutionResolver(ProjectRuntimeRegistry([]),[]))
    assert restarted.list_campaign_extraction_attempts(p.id,c.id,source.id).items==history
    assert len(mock.calls)==2


def test_retry_concurrency_claim_and_terminal_replay(harness):
    app,_,_,p,c,mock,extractor=harness
    _,first=setup_failure(harness)
    entered,release=Event(),Event();original=extractor.extract
    def paused(request):
        entered.set(); assert release.wait(10); return original(request)
    extractor.extract=paused
    with ThreadPoolExecutor(max_workers=2) as pool:
        future=pool.submit(app.retry_campaign_extraction,p.id,c.id,first.id)
        try:
            assert entered.wait(10)
            with pytest.raises(ApplicationError,match='EXTRACTION_RETRY_CONFLICT'): app.retry_campaign_extraction(p.id,c.id,first.id)
        finally:release.set()
        second=future.result()
    assert app.retry_campaign_extraction(p.id,c.id,first.id)==second and len(mock.calls)==2


@pytest.mark.parametrize('category',['AUTHENTICATION','CONFIGURATION','CONTENT_REFUSAL','INVALID_REQUEST','CONTEXT_LIMIT','UNSUPPORTED_ROLE','UNKNOWN_PROVIDER_ERROR'])
def test_non_retryable_provider_failures_do_not_call_again(harness,category):
    app,_,_,p,c,mock,extractor=harness
    source=put(app,p,c)
    def fail(request): raise ModelError(ProviderErrorCategory(category))
    extractor.extract=fail
    first=app.extract_campaign_requirements(p.id,c.id,source.id)
    assert not first.retryable and first.usage.total_tokens.total is None
    with pytest.raises(ApplicationError,match='EXTRACTION_RETRY_NOT_ALLOWED'):app.retry_campaign_extraction(p.id,c.id,first.id)
    assert not mock.calls


def test_retry_bound_and_unknown_usage_remains_unknown(harness):
    app,_,_,p,c,mock,extractor=harness
    source=put(app,p,c)
    calls=[]
    def fail(request):calls.append(request);raise ModelError(ProviderErrorCategory.TIMEOUT)
    extractor.extract=fail
    first=app.extract_campaign_requirements(p.id,c.id,source.id)
    second=app.retry_campaign_extraction(p.id,c.id,first.id)
    third=app.retry_campaign_extraction(p.id,c.id,second.id)
    assert third.attempt_number==3 and not third.retryable and len(calls)==3
    assert app.get_campaign_model_usage(p.id,c.id).usage.total_tokens.total is None
    with pytest.raises(ApplicationError,match='EXTRACTION_RETRY_NOT_ALLOWED'):app.retry_campaign_extraction(p.id,c.id,third.id)
    assert len(calls)==3


def test_clarification_revision_requires_grounding_new_approval_and_new_test_coverage(harness):
    app,factory,engine,p,c,mock,_=harness
    _,old=setup_requirement(harness)
    app.import_campaign_tests(p.id,c.id,name='Historical test',format='CSV',content=csv_text([case(refs=[str(old.id)])]))
    test=app.list_campaign_test_specifications(p.id,c.id).items[0]
    receipt=app.review_campaign_test_specification(p.id,c.id,test.id,reviewer_label='qa')
    with pytest.raises(ApplicationError,match='REVIEW_NOT_REVIEWABLE'):app.review_campaign_requirement(p.id,c.id,old.id,reviewer_label='qa')
    evidence=app.add_requirement_clarification(p.id,c.id,old.id,request_key='facts-1',content='Errors are shown inline.\r\n')
    assert len(mock.calls)==1 and app.list_campaign_requirements(p.id,c.id).items==(old,)
    assert app.add_requirement_clarification(p.id,c.id,old.id,request_key='facts-1',content='Errors are shown inline.\n')==evidence
    combined=app.get_campaign_source(p.id,c.id,evidence.source_id)
    assert combined.normalized_text.endswith('Errors are shown inline.\n')
    assert next(s for s in app.list_campaign_sources(p.id,c.id).items if s.id==evidence.source_id).clarification_requirement_id==old.id
    mock.queue.append(revised)
    attempt=app.extract_campaign_requirements(p.id,c.id,evidence.source_id)
    assert attempt.status=='SUCCEEDED' and len(mock.calls)==2
    current=app.list_campaign_requirements(p.id,c.id).items[0]
    assert current.id!=old.id and current.review_status=='READY_FOR_REVIEW' and current.source_references[0].source_id==evidence.source_id
    assert app.get_campaign_requirement(p.id,c.id,old.id)==old
    history=app.get_requirement_history(p.id,c.id,current.id).items
    assert [item.version for item in history]==[1,2] and [item.is_current for item in history]==[False,True]
    assert history[1].supersedes_id==old.id
    assert app.get_campaign_requirement_review(p.id,c.id,current.id).evidence is None
    assert app.get_campaign_test_specification_review(p.id,c.id,test.id)==receipt
    assert app.list_campaign_test_specifications(p.id,c.id).items==()
    assert app.get_campaign_traceability(p.id,c.id).requirements.items[0].approved_test_count==0
    assert app.get_campaign_traceability(p.id,c.id).links.items==()
    with pytest.raises(ApplicationError,match='REVIEW_NOT_REVIEWABLE'):app.review_campaign_test_specification(p.id,c.id,test.id,reviewer_label='qa')
    with pytest.raises(ApplicationError,match='REQUIREMENT_REVISION_CONFLICT'):app.add_requirement_clarification(p.id,c.id,old.id,request_key='stale',content='More facts')
    app.review_campaign_requirement(p.id,c.id,current.id,reviewer_label='qa')
    app.import_campaign_tests(p.id,c.id,name='Replacement',format='CSV',content=csv_text([case('REPLACEMENT',refs=[str(current.id)])]))
    replacement=app.list_campaign_test_specifications(p.id,c.id).items[0]
    assert replacement.id!=test.id and replacement.review_status=='READY_FOR_REVIEW'
    app.review_campaign_test_specification(p.id,c.id,replacement.id,reviewer_label='qa')
    app.transition_campaign(p.id,c.id,status='READY_FOR_REVIEW');app.transition_campaign(p.id,c.id,status='APPROVED')
    assert app.get_campaign_readiness(p.id,c.id).status=='READY'
    # Snapshot creation selection is a direct dependency of current readiness, never execution.
    run=app.create_qa_run(p.id,c.id,idempotency_key='new-current')
    assert app.list_qa_run_tests(p.id,c.id,run.id).items[0].original_test_specification_id==replacement.id
    engine.dispose()
    restarted=QASentinelApplication(factory,ProjectExecutionResolver(ProjectRuntimeRegistry([]),[]))
    assert restarted.get_requirement_history(p.id,c.id,current.id).items[0].requirement==old
    assert restarted.get_campaign_readiness(p.id,c.id).status=='READY'


@pytest.mark.parametrize('output',[lambda call:revised(call,original_only=True),lambda call:revised(call,wrong_key=True),lambda call:revised(call,markers=True)])
def test_revision_never_bypasses_grounding_or_ambiguity(harness,output):
    app,_,_,p,c,mock,_=harness
    _,old=setup_requirement(harness)
    evidence=app.add_requirement_clarification(p.id,c.id,old.id,request_key='facts',content='More supplied facts')
    mock.queue.append(output)
    result=app.extract_campaign_requirements(p.id,c.id,evidence.source_id)
    if result.status=='FAILED':
        assert app.list_campaign_requirements(p.id,c.id).items==(old,)
    else:
        new=app.list_campaign_requirements(p.id,c.id).items[0]
        assert new.review_status=='NEEDS_CLARIFICATION'
        with pytest.raises(ApplicationError,match='REVIEW_NOT_REVIEWABLE'):app.review_campaign_requirement(p.id,c.id,new.id,reviewer_label='qa')
    assert app.get_campaign_readiness(p.id,c.id).status=='NOT_READY'


def test_clarification_concurrency_bounds_scope_and_no_side_effects(harness):
    app,_,_,p,c,mock,_=harness
    _,old=setup_requirement(harness)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(app.add_requirement_clarification,p.id,c.id,old.id,request_key='one',content='<script>inert</script> [link](https://invalid)') for _ in range(2)]
        assert jobs[0].result()==jobs[1].result()
    assert len(mock.calls)==1
    with pytest.raises(ApplicationError,match='REQUIREMENT_REVISION_CONFLICT'):app.add_requirement_clarification(p.id,c.id,old.id,request_key='one',content='changed')
    for content in ['', 'Ã©'*2001, '\x00', 'a'*4001]:
        with pytest.raises(ApplicationError,match='CLARIFICATION_INVALID'):app.add_requirement_clarification(p.id,c.id,old.id,request_key='invalid',content=content)
    foreign=app.create_project(key='foreign',name='Foreign'); other=app.create_campaign(foreign.id,name='Other')
    with pytest.raises(ApplicationError,match='EXTRACTION_ATTEMPT_NOT_FOUND'):app.retry_campaign_extraction(foreign.id,other.id,old.extraction_id)
    with TestClient(create_api_app(app)) as client:
        root=f'/api/v1/projects/{p.id}/campaigns/{c.id}'
        assert client.get(root+f'/requirements/{old.id}/history').status_code==200
        assert client.post(root+f'/requirements/{old.id}/clarifications',json={'request_key':'x','content':'facts','approve':True}).status_code==422
        assert client.post(root+f'/extractions/{uuid4()}/retry',json={}).status_code==404
    assert len(mock.calls)==1


def test_0010_roundtrip_preserves_initial_failed_attempt_and_refuses_history_loss(harness,migrated_factory):
    app,_,engine,p,c,_,_=harness
    config=migrated_factory[2]
    source,first=setup_failure(harness)
    command.downgrade(config,'0009');command.upgrade(config,'head');command.check(config)
    assert app.list_campaign_extraction_attempts(p.id,c.id,source.id).items[0]==first
    app.retry_campaign_extraction(p.id,c.id,first.id)
    with pytest.raises(RuntimeError,match='cannot erase preparation recovery audit history'):command.downgrade(config,'0009')
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version'))=='0010'
        assert not connection.exec_driver_sql('PRAGMA foreign_key_check').all()


def test_concurrent_distinct_clarification_revisions_cannot_fork_current_truth(harness):
    app,_,_,p,c,mock,extractor=harness
    _,old=setup_requirement(harness)
    one=app.add_requirement_clarification(p.id,c.id,old.id,request_key='one',content='First supplied facts')
    two=app.add_requirement_clarification(p.id,c.id,old.id,request_key='two',content='Other supplied facts')
    mock.queue.append(revised)
    entered,release=Event(),Event();original=extractor.extract
    def paused(request):
        entered.set();assert release.wait(10);return original(request)
    extractor.extract=paused
    with ThreadPoolExecutor(max_workers=2) as pool:
        future=pool.submit(app.extract_campaign_requirements,p.id,c.id,one.source_id)
        try:
            assert entered.wait(10)
            with pytest.raises(ApplicationError,match='REQUIREMENT_REVISION_CONFLICT'):
                app.extract_campaign_requirements(p.id,c.id,two.source_id)
        finally:release.set()
        assert future.result().status=='SUCCEEDED'
    with pytest.raises(ApplicationError,match='REQUIREMENT_REVISION_CONFLICT'):
        app.extract_campaign_requirements(p.id,c.id,two.source_id)
    assert len(mock.calls)==2 and len(app.get_requirement_history(p.id,c.id,old.id).items)==2


def test_downgrade_preserves_saved_clarification_before_any_revision(harness,migrated_factory):
    app,_,engine,p,c,mock,_=harness
    _,old=setup_requirement(harness)
    evidence=app.add_requirement_clarification(p.id,c.id,old.id,request_key='saved',content='Untrusted operator facts')
    with pytest.raises(RuntimeError,match='cannot erase preparation recovery audit history'):
        command.downgrade(migrated_factory[2],'0009')
    engine.dispose()
    assert app.get_campaign_source(p.id,c.id,evidence.source_id).normalized_text.endswith('Untrusted operator facts')
    assert len(mock.calls)==1


def test_multi_requirement_test_retires_from_all_current_traceability_after_revision(harness):
    app,factory,_,p,c,mock,_=harness
    _,old=setup_requirement(harness)
    unchanged=seed_requirement(factory,p,c,key='UNCHANGED')
    record=app.import_campaign_tests(p.id,c.id,name='Shared test',format='CSV',
        content=csv_text([case(refs=[str(old.id),str(unchanged.id)])]))
    test=app.list_campaign_test_specifications(p.id,c.id).items[0]
    app.review_campaign_test_specification(p.id,c.id,test.id,reviewer_label='qa')
    evidence=app.add_requirement_clarification(p.id,c.id,old.id,request_key='facts',content='Supplied facts')
    mock.queue.append(revised)
    assert app.extract_campaign_requirements(p.id,c.id,evidence.source_id).status=='SUCCEEDED'
    trace=app.get_campaign_traceability(p.id,c.id)
    row=next(r for r in trace.requirements.items if r.requirement_id==unchanged.id)
    assert row.linked_test_count==row.approved_test_count==0 and row.coverage=='NOT_COVERED'
    assert row.linked_test_review_states=={} and trace.links.items==()
    historical=app.get_campaign_test_specification(p.id,c.id,test.id)
    assert historical.requirement_ids==test.requirement_ids and set(historical.requirement_ids)=={old.id,unchanged.id}
    assert app.get_campaign_test_import(p.id,c.id,record.id).status=='IMPORTED'


def test_scoped_retry_api_returns_distinct_attempt_and_history_without_get_replay(harness):
    app,_,_,p,c,mock,_=harness
    source,first=setup_failure(harness)
    root=f'/api/v1/projects/{p.id}/campaigns/{c.id}'
    with TestClient(create_api_app(app)) as client:
        result=client.post(root+f'/extractions/{first.id}/retry',json={})
        assert result.status_code==200 and result.json()['parent_attempt_id']==str(first.id)
        second=result.json()['id']
        assert client.post(root+f'/extractions/{first.id}/retry',json={}).json()['id']==second
        history=client.get(root+f'/sources/{source.id}/extractions?limit=1').json()
        assert history['items'][0]['id']==second and history['truncated']
        assert client.get(root+f'/sources/{source.id}/extractions?limit=0').status_code==422
        assert client.post(root+f'/extractions/{first.id}/retry',json={'automatic':True}).status_code==422
        assert client.post(root+f'/extractions/{first.id}/retry',content=b'x'*8193).status_code==413
    assert len(mock.calls)==2


def test_clarification_api_keeps_ingestion_separate_from_explicit_revision(harness):
    app,_,_,p,c,mock,_=harness
    _,old=setup_requirement(harness)
    root=f'/api/v1/projects/{p.id}/campaigns/{c.id}'
    with TestClient(create_api_app(app)) as client:
        path=root+f'/requirements/{old.id}/clarifications'
        saved=client.post(path,json={'request_key':'api-facts','content':'Supplied missing facts'})
        assert saved.status_code==201 and len(mock.calls)==1
        assert client.post(path,json={'request_key':'api-facts','content':'Supplied missing facts'}).json()==saved.json()
        mock.queue.append(revised)
        result=client.post(root+f"/sources/{saved.json()['source_id']}/extract-requirements",json={})
        assert result.status_code==200 and result.json()['status']=='SUCCEEDED'
        history=client.get(root+f'/requirements/{old.id}/history').json()['items']
        assert [r['is_current'] for r in history]==[False,True] and len(mock.calls)==2
