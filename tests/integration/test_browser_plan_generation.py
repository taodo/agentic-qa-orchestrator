"""Offline model generation, explicit acceptance and immutable browser provenance."""
import json
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from qa_sentinel.agents.browser_plan_generation import BrowserPlanGenerator
from qa_sentinel.models.base import ModelSettings
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from qa_sentinel.application import QASentinelApplication,ProjectExecutionResolver,ApplicationError
from qa_sentinel.projects import ProjectRuntimeRegistry
from qa_sentinel.execution.browser_policy import BrowserExecutionPolicy,digest
from qa_sentinel.domain.browser_execution import BrowserRuntimeIdentity
from qa_sentinel.domain.browser_generation import input_hash
from test_campaign_test_specifications import seed_requirement,case,csv_text
from test_playwright_runtime import site

LOC={'strategy':'ROLE','role':'heading','name':'Courses','exact':True}
FACTS={'contract_version':'browser-facts-v1','required_actions':[['NAVIGATE']],'locators':[LOC],'paths':['/courses'],'input_values':[]}
PLAN={'steps':[{'action':'NAVIGATE','path':'/courses'},{'action':'ASSERT_TEXT','locator':LOC,'text':'Courses'}],'redirect_limit':0}
OUTPUT={'disposition':'CANDIDATE','plan':PLAN,'step_bindings':[1,1],'unable_reason':None}

class Executor:
    identity=BrowserRuntimeIdentity(playwright_version='1.63.0',chromium_revision='1243',browser_version='153.0.8010.12')
    def __init__(self):self.calls=[]
    def policy_for(self,target):return BrowserExecutionPolicy()
    def execute(self,envelope,run,test):
        self.calls.append(envelope)
        from qa_sentinel.domain.qa_run_evidence import TestExecutionResult,EvidenceDraft
        from qa_sentinel.domain.evidence_variants import BrowserObservation
        observation=BrowserObservation(category='ASSERTION',run_test_id=test.id,plan_hash=envelope.plan_hash,step_number=2,action='ASSERT_TEXT',matched=True,outcome='PASS',browser_version=self.identity.browser_version)
        return TestExecutionResult(executor_kind='WEB_BROWSER',qa_result='PASS',evidence=(EvidenceDraft(source='web-browser',payload=observation,summary=observation.safe_summary()),))

@pytest.fixture
def planning(migrated_factory,mock_openai):
    factory,engine,config=migrated_factory
    mock=mock_openai([OUTPUT])
    executor=Executor()
    app=QASentinelApplication(factory,ProjectExecutionResolver(ProjectRuntimeRegistry([]),[]),browser_executor=executor,
        browser_plan_generator=BrowserPlanGenerator(OpenAIModelAdapter(client=mock.client),ModelSettings(model='configured-model')))
    p=app.create_project(key='plans',name='Planning');c=app.create_campaign(p.id,name='Black box')
    req=seed_requirement(factory,p,c);app.review_campaign_requirement(p.id,c.id,req.id,reviewer_label='qa')
    value=case(refs=[str(req.id)]);value.update(preconditions=[json.dumps(FACTS)],steps=[{'index':1,'action':'Navigate /courses and verify the supplied heading','expected':'Courses'}],overall_expected_result='Courses')
    app.import_campaign_tests(p.id,c.id,name='Browser test',format='CSV',content=csv_text([value]))
    spec=app.list_campaign_test_specifications(p.id,c.id).items[0];app.review_campaign_test_specification(p.id,c.id,spec.id,reviewer_label='qa')
    target=app.create_target(p.id,name='Approved WEB',environment='STAGING',configuration={'base_url':'https://example.com'})
    app.associate_campaign_target(p.id,c.id,target_id=target.id)
    return app,factory,engine,config,p,c,spec,mock,executor,target

def rows(engine):
    with engine.connect() as db:return tuple(db.scalar(text('SELECT count(*) FROM '+table)) for table in ('qa_runs','qa_run_evidence','tasks','execution_jobs'))

def test_generation_is_separate_durable_bounded_and_truthful(planning,monkeypatch):
    app,_,engine,_,p,c,spec,mock,executor,_=planning
    import subprocess,socket
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('No process during generation'))
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:pytest.fail('No Target resolution'))
    before=rows(engine)
    record=app.generate_browser_plan(p.id,c.id,spec.id)
    assert record.status=='SUCCEEDED' and record.origin=='AI' and executor.calls==[] and rows(engine)==before
    assert record.plan_hash==digest(record.output.plan) and record.test_hash==input_hash(record.test,record.approval) and record.target_hash==digest(record.target)
    assert record.settings.model=='configured-model' and record.metadata.model=='configured-model' and record.metadata.total_tokens==30
    assert len(mock.calls)==1 and mock.calls[0]['tools']==[] and mock.calls[0]['tool_choice']=='none' and mock.calls[0]['store'] is False
    context=json.loads(mock.calls[0]['input'][0]['content']);assert context['prompt_version']=='browser-plan-generator-v1' and context['approved_browser_facts']==FACTS
    assert record.metadata.context_selection.selected_chars==len(mock.calls[0]['input'][0]['content'])
    engine.dispose();assert app.get_browser_plan_generation(p.id,c.id,record.id)==record
    assert app.get_browser_plan_acceptance(p.id,c.id,record.id) is None
    assert app.list_browser_plan_generations(p.id,c.id,limit=1).items==(record,)


def test_explicit_acceptance_exact_seal_no_model_at_runtime_and_regeneration(planning):
    app,_,engine,_,p,c,spec,mock,executor,_=planning
    first=app.generate_browser_plan(p.id,c.id,spec.id)
    run=app.accept_browser_plan_generation(p.id,c.id,first.id,idempotency_key='accept')
    assert run.execution_status=='CREATED' and executor.calls==[] and len(mock.calls)==1
    test=app.list_qa_run_tests(p.id,c.id,run.id).items[0]
    assert test.browser_plan.plan==first.output.plan and test.browser_plan.origin=='AI' and test.browser_plan.plan_hash==first.plan_hash
    receipt=app.get_browser_plan_acceptance(p.id,c.id,first.id);assert receipt.run_id==run.id and receipt.run_test_id==test.id
    assert app.accept_browser_plan_generation(p.id,c.id,first.id,idempotency_key='accept')==run
    with pytest.raises(ApplicationError,match='BROWSER_PLAN_ALREADY_ACCEPTED'):app.accept_browser_plan_generation(p.id,c.id,first.id,idempotency_key='another')
    mock.queue.append(OUTPUT)
    next_record=app.generate_browser_plan(p.id,c.id,spec.id);assert next_record.id!=first.id and next_record.status=='SUCCEEDED'
    assert app.get_qa_run(p.id,c.id,run.id)==run and app.list_qa_run_tests(p.id,c.id,run.id).items[0]==test
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    assert final.qa_outcome=='PASS' and len(mock.calls)==2 and executor.calls==[test.browser_plan]
    for statement in ['UPDATE browser_plan_generations SET status=status','DELETE FROM browser_plan_generations','UPDATE browser_plan_acceptances SET plan_hash=plan_hash','DELETE FROM browser_plan_acceptances']:
        with pytest.raises(IntegrityError),engine.begin() as db:db.execute(text(statement))

@pytest.mark.parametrize('variant',['code','version','action','locator','bound','path','invented-locator','loose','omitted','cannot','incomplete'])
def test_invalid_or_unavailable_plan_never_creates_execution(planning,variant):
    app,_,engine,_,p,c,spec,mock,executor,_=planning
    output=json.loads(json.dumps(OUTPUT))
    if variant=='code':output['script']='page.evaluate(secret)'
    elif variant=='version':output['plan']['version']='v99'
    elif variant=='action':output['plan']['steps'][1]['action']='EVALUATE'
    elif variant=='locator':output['plan']['steps'][1]['locator']['strategy']='XPATH'
    elif variant=='bound':output['plan']['steps'][0]['timeout_ms']=30001
    elif variant=='path':output['plan']['steps'][0]['path']='//private.example/path'
    elif variant=='invented-locator':output['plan']['steps'][1]['locator']['name']='Invented'
    elif variant=='loose':output['plan']['steps'][1]['exact']=False
    elif variant=='omitted':output['plan']['steps']=output['plan']['steps'][:1];output['step_bindings']=[1]
    elif variant=='cannot':output={'disposition':'CANNOT_PLAN','plan':None,'step_bindings':[],'unable_reason':'MISSING_LOCATOR'}
    from qa_sentinel.domain.browser_generation import BrowserPlanOutput
    from qa_sentinel.models.base import ModelResponse,ModelMetadata,ModelError,ProviderErrorCategory
    class Fake:
        def generate(self,request,output_type):
            if variant=='incomplete':raise ModelError(ProviderErrorCategory.INCOMPLETE_RESPONSE,metadata=ModelMetadata(model='reported',latency_ms=1,status='incomplete'))
            try:parsed=output_type.model_validate(output)
            except ValueError:raise ModelError(ProviderErrorCategory.MALFORMED_RESPONSE) from None
            return ModelResponse(parsed_output=parsed,metadata=ModelMetadata(model='reported',latency_ms=1))
    app._browser_plan_generator.adapter=Fake()
    before=rows(engine);record=app.generate_browser_plan(p.id,c.id,spec.id)
    assert record.status=='FAILED' and record.output is None and record.plan_hash is None and rows(engine)==before and executor.calls==[]
    assert 'secret' not in record.model_dump_json()
    with pytest.raises(ApplicationError):app.accept_browser_plan_generation(p.id,c.id,record.id,idempotency_key='bad')


def test_explicit_retry_bound_immutable_inputs_unknown_usage_and_scoping(planning):
    app,_,engine,_,p,c,spec,_,executor,_=planning
    from qa_sentinel.models.base import ModelError,ProviderErrorCategory
    calls=[]
    class Fake:
        def generate(self,request,output_type):calls.append(request);raise ModelError(ProviderErrorCategory.CONNECTION)
    app._browser_plan_generator.adapter=Fake()
    first=app.generate_browser_plan(p.id,c.id,spec.id)
    second=app.retry_browser_plan_generation(p.id,c.id,first.id)
    third=app.retry_browser_plan_generation(p.id,c.id,second.id)
    assert [r.attempt_number for r in (first,second,third)]==[1,2,3] and len(calls)==3 and all(r.metadata is None for r in (first,second,third))
    assert calls[0]==calls[1]==calls[2] and all(r.test_hash==first.test_hash and r.target_hash==first.target_hash for r in (second,third))
    with pytest.raises(ApplicationError,match='BROWSER_PLAN_RETRY_EXHAUSTED'):app.retry_browser_plan_generation(p.id,c.id,third.id)
    foreign=app.create_project(key='foreign',name='Foreign');campaign=app.create_campaign(foreign.id,name='Other')
    with pytest.raises(ApplicationError,match='BROWSER_PLAN_NOT_FOUND'):app.get_browser_plan_generation(foreign.id,campaign.id,first.id)
    with pytest.raises(ApplicationError):app.accept_browser_plan_generation(foreign.id,campaign.id,first.id,idempotency_key='foreign')
    assert rows(engine)==(0,0,0,0)


def test_acceptance_rejects_changed_target_atomically(planning):
    app,_,engine,_,p,c,spec,_,executor,target=planning
    record=app.generate_browser_plan(p.id,c.id,spec.id)
    app.update_target(p.id,target.id,name='Changed')
    with pytest.raises(ApplicationError,match='BROWSER_PLAN_PROVENANCE_MISMATCH'):app.accept_browser_plan_generation(p.id,c.id,record.id,idempotency_key='stale')
    assert rows(engine)==(0,0,0,0) and app.get_browser_plan_acceptance(p.id,c.id,record.id) is None


def test_migration_empty_downgrade_reupgrade_check_and_history_guard(planning):
    from alembic import command
    app,_,engine,config,p,c,spec,_,_,_=planning
    command.downgrade(config,'0014');command.upgrade(config,'head');command.check(config)
    record=app.generate_browser_plan(p.id,c.id,spec.id);engine.dispose()
    assert app.get_browser_plan_generation(p.id,c.id,record.id)==record
    with pytest.raises(RuntimeError,match='cannot erase browser planning history'):command.downgrade(config,'0014')
    assert app.get_browser_plan_generation(p.id,c.id,record.id)==record


@pytest.mark.parametrize('failure,code',[('timeout','MODEL_TIMEOUT'),('connection','MODEL_CONNECTION'),(401,'MODEL_AUTHENTICATION'),(429,'MODEL_RATE_LIMIT'),(500,'MODEL_SERVER_ERROR'),('refusal','MODEL_CONTENT_REFUSAL'),({'prose':'synthetic-sensitive-output'},'MODEL_MALFORMED_RESPONSE')])
def test_actual_adapter_failures_are_safe_single_call(planning,mock_openai,failure,code):
    app,_,engine,_,p,c,spec,_,executor,_=planning
    mock=mock_openai([failure]);app._browser_plan_generator.adapter=OpenAIModelAdapter(client=mock.client)
    record=app.generate_browser_plan(p.id,c.id,spec.id)
    assert record.status=='FAILED' and record.error_code==code and len(mock.calls)==1 and executor.calls==[]
    assert rows(engine)==(0,0,0,0) and 'synthetic-sensitive' not in record.model_dump_json()

@pytest.mark.parametrize('tokens',[None,0])
def test_reported_model_and_missing_vs_zero_usage_are_not_inferred(planning,tokens):
    from qa_sentinel.models.base import ModelResponse,ModelMetadata
    from qa_sentinel.domain.browser_generation import BrowserPlanOutput
    app,_,_,_,p,c,spec,_,_,_=planning
    class Fake:
        def generate(self,request,output_type):
            return ModelResponse(parsed_output=BrowserPlanOutput.model_validate(OUTPUT),metadata=ModelMetadata(provider='fake',model='provider-snapshot',latency_ms=1,
                input_tokens=tokens,output_tokens=tokens,reasoning_tokens=tokens,total_tokens=tokens,context_selection=request.context_selection))
    app._browser_plan_generator.adapter=Fake();record=app.generate_browser_plan(p.id,c.id,spec.id)
    assert record.status=='SUCCEEDED' and record.settings.model=='configured-model' and record.metadata.model=='provider-snapshot'
    assert record.metadata.total_tokens==tokens and record.metadata.reasoning_tokens==tokens


def test_started_precedes_provider_no_open_transaction_and_reads_do_not_call_model(planning):
    app,_,engine,_,p,c,spec,mock,executor,_=planning
    observed=[]
    def inspect(request):
        with engine.connect().execution_options(qa_job_write=True) as db:
            observed.append(db.scalar(text("SELECT status FROM browser_plan_generations")))
        return OUTPUT
    mock.queue.clear();mock.queue.append(inspect)
    record=app.generate_browser_plan(p.id,c.id,spec.id)
    assert observed==['STARTED'] and record.status=='SUCCEEDED'
    app.get_browser_plan_generation(p.id,c.id,record.id);app.list_browser_plan_generations(p.id,c.id);app.get_browser_plan_acceptance(p.id,c.id,record.id)
    assert len(mock.calls)==1 and executor.calls==[]


def test_context_failure_retry_replay_and_unresolved_started_are_safe(planning,monkeypatch):
    from qa_sentinel.models.base import ModelError,ProviderErrorCategory
    from qa_sentinel.domain.browser_generation import BrowserPlanGeneration
    from qa_sentinel.persistence.unit_of_work import UnitOfWork
    app,factory,engine,_,p,c,spec,mock,executor,_=planning
    def too_large(record):raise ModelError(ProviderErrorCategory.CONTEXT_LIMIT)
    monkeypatch.setattr(app._browser_plan_generator,'prepare',too_large)
    record=app.generate_browser_plan(p.id,c.id,spec.id)
    assert record.error_code=='MODEL_CONTEXT_LIMIT' and not mock.calls and executor.calls==[]
    with pytest.raises(ApplicationError,match='BROWSER_PLAN_RETRY_NOT_ALLOWED'):app.retry_browser_plan_generation(p.id,c.id,record.id)
    pending=BrowserPlanGeneration(**record.model_dump(exclude={'id','status','started_at','finished_at','error_code','metadata','output','plan_hash'}))
    with UnitOfWork(factory) as uow:uow.browser_plans.reserve(pending);uow.commit()
    with pytest.raises(ApplicationError,match='BROWSER_PLAN_RECONCILIATION_REQUIRED'):app.retry_browser_plan_generation(p.id,c.id,pending.id)
    assert app.get_browser_plan_generation(p.id,c.id,pending.id).status=='STARTED' and rows(engine)==(0,0,0,0)


def test_duplicate_retry_and_cross_scope_generation_do_not_call_provider(planning):
    from qa_sentinel.models.base import ModelError,ProviderErrorCategory
    app,_,engine,_,p,c,spec,_,_,_=planning
    calls=[]
    class Fake:
        def generate(self,*args):calls.append(1);raise ModelError(ProviderErrorCategory.CONNECTION)
    app._browser_plan_generator.adapter=Fake()
    first=app.generate_browser_plan(p.id,c.id,spec.id);app.retry_browser_plan_generation(p.id,c.id,first.id)
    with pytest.raises(ApplicationError,match='BROWSER_PLAN_RETRY_NOT_ALLOWED'):app.retry_browser_plan_generation(p.id,c.id,first.id)
    other=app.create_campaign(p.id,name='Other')
    with pytest.raises(ApplicationError,match='CAMPAIGN_TEST_CHILD_MISMATCH'):app.generate_browser_plan(p.id,other.id,spec.id)
    assert len(calls)==2 and rows(engine)==(0,0,0,0)


def test_accepted_ai_plan_is_consumed_by_existing_real_runtime(planning,site):
    pytest.importorskip('playwright.async_api')
    from pathlib import Path
    from playwright.sync_api import sync_playwright
    from qa_sentinel.execution.playwright_browser import PlaywrightBrowserExecutor
    with sync_playwright() as runtime:
        if not Path(runtime.chromium.executable_path).is_file():pytest.skip('Chromium unavailable; explicit installation required')
    app,_,_,_,p,c,spec,mock,_,target=planning
    app.update_target(p.id,target.id,configuration={'base_url':site[0]})
    app._browser_executor=PlaywrightBrowserExecutor(trusted_local_origin=site[0])
    record=app.generate_browser_plan(p.id,c.id,spec.id)
    assert record.status=='SUCCEEDED' and site[1]==[] and len(mock.calls)==1
    run=app.accept_browser_plan_generation(p.id,c.id,record.id,idempotency_key='real-accept')
    assert site[1]==[] and len(mock.calls)==1 and run.execution_status=='CREATED'
    app._browser_plan_generator=None
    final=app.start_browser_qa_run(p.id,c.id,run.id)
    assert (final.execution_status,final.qa_outcome)==('COMPLETED','PASS') and len(mock.calls)==1
    result=app.get_qa_run_results(p.id,c.id,run.id).tests.items[0]
    assert result.browser_plan.origin=='AI' and result.browser_plan.plan==record.output.plan
    assert all(e.payload.plan_hash==record.plan_hash and e.executor_kind=='WEB_BROWSER' for e in result.evidence.items)
    assert '/courses' in site[1]
