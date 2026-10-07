"""Offline two-path design, traceability, replay protection and transport proof."""
import csv
import io
import json
from uuid import uuid4
from datetime import datetime,timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text,event
from qa_sentinel.application import QASentinelApplication,ProjectExecutionResolver,ApplicationError
from qa_sentinel.projects import ProjectRuntimeRegistry
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.domain.campaign_content import RequirementExtraction,CampaignRequirement
from qa_sentinel.agents.requirement_extraction import ingest
from qa_sentinel.agents.test_import import COLUMNS,JSON_COLUMNS
from qa_sentinel.agents.test_generation import TestSpecificationGenerator as Generator
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from qa_sentinel.models.base import ModelSettings
from qa_sentinel.api import create_api_app


def case(key='LOGIN',refs=()):
    return dict(key=key,title='Login',requirement_refs=list(refs),test_type='FUNCTIONAL',priority='HIGH',
        preconditions=['Existing user'],steps=[dict(index=1,action='Sign in',expected='User is signed in')],
        overall_expected_result='User is signed in',required_evidence=['Observed sign-in state'],information_markers=[])


def csv_text(cases):
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=COLUMNS,lineterminator='\n');writer.writeheader()
    for item in cases:writer.writerow({k:json.dumps(v) if k in JSON_COLUMNS else v for k,v in item.items()})
    return stream.getvalue()


def markdown_text(cases):
    return '# Test cases\n\n'+''.join('## '+item['key']+'\n```json\n'+json.dumps({k:v for k,v in item.items() if k!='key'})+'\n```\n\n' for item in cases)


def seed_requirement(factory,project,campaign,key='LOGIN',markers=(),criteria=None):
    source=ingest(project.id,campaign.id,name='PRD '+key,source_type='TEXT',content=key+' is required.')
    attempt=RequirementExtraction(project_id=project.id,campaign_id=campaign.id,source_id=source.id,source_hash=source.content_hash,model='fixture')
    requirement=CampaignRequirement(project_id=project.id,campaign_id=campaign.id,extraction_id=attempt.id,key=key,
        logical_key=f'REQ-{source.id.hex}-{key}',title=key,description=key+' is required.',
        acceptance_criteria=criteria if criteria is not None else [dict(key='C1',text=key+' is required.')],
        source_references=[dict(source_id=source.id,source_hash=source.content_hash,start_line=1,end_line=1,excerpt=key+' is required.')],
        information_markers=markers,review_status='NEEDS_CLARIFICATION' if markers else 'READY_FOR_REVIEW')
    with UnitOfWork(factory) as uow:
        uow.campaign_content.add_source(source);uow.campaign_content.reserve(attempt)
        uow.campaign_content.finish(RequirementExtraction.model_validate({**attempt.model_dump(),'status':'SUCCEEDED','finished_at':datetime.now(timezone.utc)}),[requirement]);uow.commit()
    return requirement


def generated(call):
    context=json.loads(call['input'][0]['content']);ids=context['selected_requirement_ids']
    item=case();item.pop('requirement_refs');item['requirement_ids']=ids
    return dict(selected_requirement_ids=ids,tests=[item])

@pytest.fixture
def harness(migrated_factory,mock_openai):
    factory,engine,_=migrated_factory;mock=mock_openai([generated])
    generator=Generator(OpenAIModelAdapter(client=mock.client),ModelSettings(model='test-model'))
    app=QASentinelApplication(factory,ProjectExecutionResolver(ProjectRuntimeRegistry([]),[]),test_generator=generator)
    project=app.create_project(key='design',name='Design');campaign=app.create_campaign(project.id,name='Black box QA')
    requirements=[seed_requirement(factory,project,campaign),seed_requirement(factory,project,campaign,'LOGOUT')]
    return app,factory,engine,project,campaign,requirements,mock


def put(harness,cases=None,format='CSV'):
    app,_,_,project,campaign,requirements,_=harness
    cases=cases or [case(refs=[str(requirements[0].id)])]
    return app.import_campaign_tests(project.id,campaign.id,name='Existing cases',format=format,
        content=csv_text(cases) if format=='CSV' else markdown_text(cases))

@pytest.mark.parametrize('format',['CSV','MARKDOWN'])
def test_import_is_pure_scoped_durable_idempotent_and_converges_with_generation(harness,monkeypatch,format):
    app,factory,engine,project,campaign,requirements,mock=harness
    def forbidden(*args,**kwargs):raise AssertionError('No external work in import or reads')
    monkeypatch.setattr(app._resolver,'resolve',forbidden)
    import subprocess
    monkeypatch.setattr(subprocess,'Popen',forbidden)
    record=put(harness,format=format);assert record.status=='IMPORTED' and not mock.calls
    assert put(harness,format=format)==record
    imported=app.list_campaign_test_specifications(project.id,campaign.id).items[0]
    assert imported.requirement_ids==(requirements[0].id,) and imported.provenance.origin=='IMPORT'
    assert imported.review_status=='READY_FOR_REVIEW' and imported.provenance.start_line>=2
    detail=app.get_campaign_test_import(project.id,campaign.id,record.id)
    equivalent=app.import_campaign_tests(project.id,campaign.id,name='Renamed',format=format,content='\ufeff'+detail.normalized_text.replace('\n','\r\n'))
    assert equivalent==record and app.get_campaign(project.id,campaign.id)==campaign
    result=app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[requirements[0].id])
    assert result.status=='SUCCEEDED' and result.usage.total_tokens.total==30
    specs=app.list_campaign_test_specifications(project.id,campaign.id).items
    assert len(specs)==2 and all(type(s)==type(imported) for s in specs)
    assert {s.provenance.origin for s in specs}=={'IMPORT','AI_GENERATED'}
    assert specs[1].steps==imported.steps and specs[1].requirement_ids==imported.requirement_ids
    engine.dispose();restarted=QASentinelApplication(factory,ProjectExecutionResolver(ProjectRuntimeRegistry([]),[]))
    assert restarted.get_campaign_test_import(project.id,campaign.id,record.id)==detail
    assert restarted.list_campaign_test_specifications(project.id,campaign.id).items==specs
    assert restarted.get_campaign_test_generation(project.id,campaign.id,result.id)==result
    with engine.connect() as connection:
        assert all(connection.scalar(text(f'SELECT count(*) FROM {name}'))==0 for name in ('tasks','execution_jobs','invocations','test_runs','events','artifacts'))

@pytest.mark.parametrize('reference',['id','logical','local','unknown','absent','foreign','ambiguous'])
def test_import_requirement_resolution_exact_and_unknown_never_guessed(harness,reference):
    app,factory,_,project,campaign,requirements,mock=harness;req=requirements[0]
    if reference=='foreign':
        p=app.create_project(key='foreign',name='Foreign');c=app.create_campaign(p.id,name='Foreign');ref=str(seed_requirement(factory,p,c).id)
    elif reference=='ambiguous':
        other_source=ingest(project.id,campaign.id,name='Second PRD',source_type='TEXT',content='Second login source.')
        # Same local key in a different immutable source is intentionally ambiguous.
        attempt=RequirementExtraction(project_id=project.id,campaign_id=campaign.id,source_id=other_source.id,source_hash=other_source.content_hash,model='fixture')
        duplicate=CampaignRequirement.model_validate({**req.model_dump(),'id':uuid4(),'extraction_id':attempt.id,'logical_key':'SECOND-LOGIN',
            'source_references':[dict(source_id=other_source.id,source_hash=other_source.content_hash,start_line=1,end_line=1,excerpt='Second login source.')]})
        with UnitOfWork(factory) as uow:
            uow.campaign_content.add_source(other_source);uow.campaign_content.reserve(attempt)
            uow.campaign_content.finish(RequirementExtraction.model_validate({**attempt.model_dump(),'status':'SUCCEEDED','finished_at':datetime.now(timezone.utc)}),[duplicate]);uow.commit()
        ref=req.key
    else:ref={'id':str(req.id),'logical':req.logical_key,'local':req.key,'unknown':'LOGI','absent':None}[reference]
    put(harness,[case(refs=[] if ref is None else [ref])])
    spec=app.list_campaign_test_specifications(project.id,campaign.id).items[0]
    if reference in {'id','logical','local'}:assert spec.requirement_ids==(req.id,) and spec.review_status=='READY_FOR_REVIEW'
    else:
        assert spec.requirement_ids==() and spec.review_status=='NEEDS_CLARIFICATION'
        assert any(m.kind=='MISSING_TRACEABILITY' for m in spec.information_markers)
        assert spec.unresolved_requirement_refs==(() if ref is None else (ref,))
    assert not mock.calls


def test_generation_selected_only_canonical_identity_no_transaction_and_usage(harness):
    app,factory,engine,project,campaign,requirements,mock=harness
    seed_requirement(factory,project,campaign,'UNRELATED')
    active=set()
    callbacks={'begin':lambda connection:active.add(id(connection)), 'commit':lambda connection:active.discard(id(connection)), 'rollback':lambda connection:active.discard(id(connection))}
    for name,fn in callbacks.items():event.listen(engine,name,fn)
    def checked(call):
        assert not active
        with UnitOfWork(factory) as uow:assert uow.test_specifications.generations(campaign.id,50)[0].status=='STARTED'
        return generated(call)
    mock.queue.clear();mock.queue.append(checked)
    try:
        result=app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[r.id for r in reversed(requirements)])
        assert app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[r.id for r in requirements])==result
    finally:
        for name,fn in callbacks.items():event.remove(engine,name,fn)
    assert len(mock.calls)==1
    call=mock.calls[0];context=json.loads(call['input'][0]['content'])
    assert {r['id'] for r in context['requirements']}=={str(r.id) for r in requirements}
    assert 'UNRELATED' not in call['input'][0]['content'] and 'normalized_text' not in call['input'][0]['content']
    assert call['tools']==[] and call['tool_choice']=='none' and call['store'] is False and call['text']['format']['strict']
    assert mock.client.max_retries==0 and 'previous_response_id' not in call
    assert result.context_selection.original_chars==result.context_selection.selected_chars
    usage=app.get_campaign_model_usage(project.id,campaign.id)
    assert {g.identity for g in usage.by_stage}=={'REQUIREMENT_EXTRACTION','TEST_SPEC_GENERATION'}
    assert {g.identity for g in usage.by_agent}=={'RESEARCHER','PLANNER'}
    assert usage.usage.total_tokens.known_sum==30 and usage.usage.total_tokens.total is None
    assert usage.usage.total_tokens.missing_records==3 and usage.cost_status=='NOT_CONFIGURED'
    assert result.id in usage.top_invocations


def test_requirement_ambiguity_is_inherited_even_if_model_omits_markers(harness):
    app,factory,_,project,campaign,_,_=harness
    req=seed_requirement(factory,project,campaign,'UNKNOWN',markers=[dict(kind='MISSING_INFORMATION',description='Error behavior not specified')])
    result=app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[req.id])
    assert result.status=='SUCCEEDED'
    spec=app.list_campaign_test_specifications(project.id,campaign.id).items[0]
    assert spec.review_status=='NEEDS_CLARIFICATION'
    assert [m.description for m in spec.information_markers]==['Error behavior not specified']
    assert app.get_campaign(project.id,campaign.id)==campaign

@pytest.mark.parametrize('variant',['invented','missing','duplicate','empty','executor','duplicate-behavior'])
def test_generated_output_validation_is_atomic(harness,variant):
    app,_,_,project,campaign,requirements,mock=harness
    def output(call):
        value=generated(call)
        if variant=='invented':value['tests'][0]['requirement_ids']=[str(uuid4())]
        elif variant=='missing':value['selected_requirement_ids']=[]
        elif variant=='duplicate':value['tests']*=2
        elif variant=='empty':value['tests']=[]
        elif variant=='executor':value['tests'][0]['shell']='pytest'
        else:
            duplicate={**value['tests'][0],'key':'DIFFERENT','title':'Different title'};value['tests'].append(duplicate)
        return value
    mock.queue.clear();mock.queue.append(output)
    result=app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[requirements[0].id])
    assert result.status==('SUCCEEDED' if variant=='empty' else 'FAILED')
    assert not app.list_campaign_test_specifications(project.id,campaign.id).items and len(mock.calls)==1
    assert app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[requirements[0].id])==result

@pytest.mark.parametrize('failure',['refusal',500,'timeout'])
def test_provider_failure_one_attempt_safe_errors_and_no_replay(harness,failure):
    app,_,_,project,campaign,requirements,mock=harness;mock.queue.clear();mock.queue.append(failure)
    result=app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[requirements[0].id])
    assert result.status=='FAILED' and result.error_code.startswith('MODEL_') and len(mock.calls)==1
    assert app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[requirements[0].id])==result
    assert 'sensitive' not in result.model_dump_json()

@pytest.mark.parametrize('usage',[None,dict(input_tokens=0,output_tokens=0,total_tokens=0)],ids=['unknown','zero'])
def test_missing_usage_is_unknown_and_provider_zero_preserved(harness,mock_openai,usage):
    app,_,_,project,campaign,requirements,_=harness;mock=mock_openai([generated],usage_override=usage)
    app._test_generator=Generator(OpenAIModelAdapter(client=mock.client),ModelSettings(model='test-model'))
    result=app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[requirements[0].id])
    assert result.usage.total_tokens.total==(None if usage is None else 0)
    assert result.usage.total_tokens.missing_records==(1 if usage is None else 0)

@pytest.mark.parametrize('failure',['crash','persistence'])
def test_uncertain_generation_never_silently_replays(harness,monkeypatch,failure):
    app,factory,_,project,campaign,requirements,mock=harness
    if failure=='crash':
        def crash(request):raise KeyboardInterrupt('simulated process interruption')
        monkeypatch.setattr(app._test_generator,'generate',crash)
        with pytest.raises(KeyboardInterrupt):app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[requirements[0].id])
    else:
        from qa_sentinel.persistence.test_specifications import TestSpecificationRepository
        def broken(*args,**kwargs):raise ValueError('Completion commit unavailable')
        monkeypatch.setattr(TestSpecificationRepository,'finish',broken)
        with pytest.raises(ApplicationError,match='PERSISTENCE_ERROR'):app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[requirements[0].id])
    calls=len(mock.calls)
    with pytest.raises(ApplicationError,match='GENERATION_RECONCILIATION_REQUIRED'):app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[requirements[0].id])
    assert len(mock.calls)==calls
    stored=app.list_campaign_test_generations(project.id,campaign.id).items[0]
    assert stored.status=='STARTED' and stored.usage.total_tokens.total is None and not app.list_campaign_test_specifications(project.id,campaign.id).items


def test_scope_input_bounds_and_full_context_fail_before_provider(harness):
    app,factory,engine,project,campaign,requirements,mock=harness
    foreign=app.create_project(key='other',name='Other');other=app.create_campaign(foreign.id,name='Other')
    record=put(harness)
    spec=app.list_campaign_test_specifications(project.id,campaign.id).items[0]
    for action in (lambda:app.get_campaign_test_import(foreign.id,other.id,record.id),lambda:app.get_campaign_test_specification(foreign.id,other.id,spec.id)):
        with pytest.raises(ApplicationError,match='CAMPAIGN_TEST_CHILD_MISMATCH'):action()
    with pytest.raises(ApplicationError,match='CAMPAIGN_REQUIREMENT_MISMATCH'):app.generate_campaign_tests(foreign.id,other.id,requirement_ids=[requirements[0].id])
    for selection in ([],[requirements[0].id]*2,[uuid4()]*21):
        with pytest.raises(ApplicationError,match='INVALID_INPUT'):app.generate_campaign_tests(project.id,campaign.id,requirement_ids=selection)
    large=seed_requirement(factory,project,campaign,'LARGE',criteria=[dict(key=f'C{i}',text='x'*4000) for i in range(20)])
    with pytest.raises(ApplicationError,match='GENERATION_CONTEXT_LIMIT'):app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[large.id])
    assert not mock.calls and not app.list_campaign_test_generations(project.id,campaign.id).items


def test_http_routes_are_explicit_bounded_and_preserve_lazy_import_data(harness):
    app,_,_,project,campaign,requirements,mock=harness;path=f'/api/v1/projects/{project.id}/campaigns/{campaign.id}'
    with TestClient(create_api_app(app)) as client:
        record=client.post(path+'/test-imports',json=dict(name='Existing',format='CSV',content=csv_text([case()])))
        assert record.status_code==201 and not mock.calls
        listing=client.get(path+'/test-imports').json();assert 'normalized_text' not in listing['items'][0]
        assert client.get(path+'/test-imports/'+record.json()['id']).json()['normalized_text']
        specs=client.get(path+'/test-specifications').json()['items'];assert specs[0]['review_status']=='NEEDS_CLARIFICATION'
        assert client.get(path+'/test-specifications/'+specs[0]['id']).status_code==200
        assert client.post(path+'/generate-tests',json=dict(requirement_ids=[str(requirements[0].id)],tools=['shell'])).status_code==422
        generated_result=client.post(path+'/generate-tests',json=dict(requirement_ids=[str(requirements[0].id)]))
        assert generated_result.status_code==200 and len(mock.calls)==1
        id=generated_result.json()['id'];assert client.get(path+'/test-generations/'+id).json()==generated_result.json()
        assert client.get(path+'/test-generations').json()['total_returned']==1
        assert client.get(path+'/model-usage').json()['invocations'][-1]['purpose']=='TEST_SPEC_GENERATION'
        for suffix in ('test-imports','test-generations','test-specifications'):
            assert client.get(path+'/'+suffix+'?limit=201').status_code==422
            assert client.get(path+'/'+suffix+'?limit=0').status_code==422
        for suffix in ('test-imports','generate-tests'):
            assert client.post(path+'/'+suffix,content=b'x'*524289,headers={'content-type':'application/json'}).status_code==413
        assert client.patch(path+'/test-specifications/'+specs[0]['id'],json={'review_status':'APPROVED'}).status_code==405
        assert client.get(path).json()['status']=='DRAFT'


def test_changed_import_and_selection_create_new_snapshots_without_overwriting(harness):
    app,_,_,project,campaign,requirements,mock=harness
    original=put(harness);changed=case();changed['title']='New title'
    newer=put(harness,[changed]);assert original.id!=newer.id
    assert len(app.list_campaign_test_specifications(project.id,campaign.id).items)==2
    assert app.list_campaign_test_specifications(project.id,campaign.id,limit=1).truncated
    assert app.list_campaign_test_imports(project.id,campaign.id,limit=1).truncated
    mock.queue.append(generated)
    first=app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[requirements[0].id])
    second=app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[r.id for r in requirements])
    assert first.request_hash!=second.request_hash and first.id!=second.id and len(mock.calls)==2
    usage=app.get_campaign_model_usage(project.id,campaign.id)
    assert usage.usage.total_tokens.known_sum==60 and usage.usage.total_tokens.total is None
    assert app.get_campaign_model_usage(project.id,campaign.id,limit=1).truncated


def test_concurrent_equivalent_generation_has_one_provider_call(harness):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    app,_,_,project,campaign,requirements,mock=harness;entered=Event();release=Event()
    def blocked(call):
        entered.set();assert release.wait(5);return generated(call)
    mock.queue.clear();mock.queue.append(blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(app.generate_campaign_tests,project.id,campaign.id,requirement_ids=[requirements[0].id])
        try:
            assert entered.wait(5)
            with pytest.raises(ApplicationError,match='GENERATION_RECONCILIATION_REQUIRED'):app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[requirements[0].id])
        finally:release.set()
        assert future.result(timeout=5).status=='SUCCEEDED'
    assert len(mock.calls)==1 and app.list_campaign_test_generations(project.id,campaign.id).total_returned==1



def test_provider_reasoning_usage_and_context_diagnostics_are_authoritative(harness,mock_openai):
    app,_,_,project,campaign,requirements,_=harness
    mock=mock_openai([generated],usage_override=dict(input_tokens=11,output_tokens=19,total_tokens=30,output_tokens_details=dict(reasoning_tokens=7)))
    app._test_generator=Generator(OpenAIModelAdapter(client=mock.client),ModelSettings(model='test-model'))
    result=app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[requirements[0].id])
    assert result.usage.input_tokens.total==11 and result.usage.output_tokens.total==19
    assert result.usage.total_tokens.total==30 and result.usage.reasoning_tokens.total==7
    context=mock.calls[0]['input'][0]['content']
    assert result.context_selection.selected_bytes==len(context.encode('utf-8'))


def test_required_ambiguity_overflow_fails_atomically_without_truncation(harness):
    app,factory,_,project,campaign,_,mock=harness
    first=seed_requirement(factory,project,campaign,'FIRST',markers=[dict(kind='AMBIGUITY',description=f'Unknown first {i}') for i in range(15)])
    second=seed_requirement(factory,project,campaign,'SECOND',markers=[dict(kind='AMBIGUITY',description=f'Unknown second {i}') for i in range(15)])
    result=app.generate_campaign_tests(project.id,campaign.id,requirement_ids=[first.id,second.id])
    assert result.status=='FAILED' and result.error_code=='GENERATION_INVALID_OUTPUT'
    assert result.usage.total_tokens.total==30 and len(mock.calls)==1
    assert not app.list_campaign_test_specifications(project.id,campaign.id).items


def test_rejected_import_read_results_are_durable_and_idempotent(harness):
    app,_,_,project,campaign,_,mock=harness
    for format,content in [('XLSX',b'PK\x00unparsed'),('CSV','bad header'),('MARKDOWN','not the template')]:
        first=app.import_campaign_tests(project.id,campaign.id,name='Invalid existing tests',format=format,content=content)
        assert first.status=='REJECTED' and first.test_count==0
        assert app.import_campaign_tests(project.id,campaign.id,name='Repeated',format=format,content=content)==first
        assert app.get_campaign_test_import(project.id,campaign.id,first.id).normalized_text is None
    assert not app.list_campaign_test_specifications(project.id,campaign.id).items and not mock.calls
