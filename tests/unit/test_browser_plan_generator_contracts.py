"""Pure strict contracts/context/grounding: no provider or browser is required."""
import json
from uuid import uuid4
import pytest
from pydantic import ValidationError
from qa_sentinel.domain.browser_generation import BrowserPlanGeneration as Record,BrowserPlanOutput as Output,input_hash,ApprovedBrowserFacts
from qa_sentinel.domain.test_specification import CampaignTestSpecification
from qa_sentinel.domain.campaign_review import ApprovalEvidence,content_hash
from qa_sentinel.domain.target import TargetUnderTest,TargetSnapshot
from qa_sentinel.models.base import ModelSettings,ModelError
from qa_sentinel.agents.browser_plan_generation import BrowserPlanGenerator,validate_candidate
from qa_sentinel.execution.browser_policy import BrowserExecutionPolicy,digest

LOC={'strategy':'LABEL','value':'Result','exact':True}
FACTS={'contract_version':'browser-facts-v1','required_actions':[['NAVIGATE']],'locators':[LOC],'paths':['/known'],'input_values':[]}
PLAN={'steps':[{'action':'NAVIGATE','path':'/known'},{'action':'ASSERT_TEXT','locator':LOC,'text':'Expected'}],'redirect_limit':0}

@pytest.fixture
def record():
    p,c=uuid4(),uuid4()
    test=CampaignTestSpecification(project_id=p,campaign_id=c,key='CASE',logical_key='CASE',title='Approved test',test_type='WEB',priority='HIGH',
        preconditions=[json.dumps(FACTS)],steps=[{'index':1,'action':'Navigate and verify Result','expected':'Expected'}],overall_expected_result='Expected',required_evidence=['Observation'],information_markers=[],requirement_ids=[uuid4()],unresolved_requirement_refs=[],
        provenance={'origin':'IMPORT','record_id':uuid4(),'content_hash':'a'*64,'contract_version':'test-import-v1','start_line':1,'end_line':2},review_status='APPROVED')
    approval=ApprovalEvidence(object_id=test.id,object_kind='TEST_SPECIFICATION',project_id=p,campaign_id=c,reviewer_label='qa',content_hash=content_hash(test))
    target=TargetSnapshot.capture(TargetUnderTest(project_id=p,name='WEB',environment='STAGING',configuration={'base_url':'https://example.com'}))
    return Record(project_id=p,campaign_id=c,test=test,approval=approval,target=target,test_hash=input_hash(test,approval),target_hash=digest(target),settings=ModelSettings(model='configured'))

def output(plan=PLAN):return Output(disposition='CANDIDATE',plan=plan,step_bindings=[1]*len(plan['steps']),unable_reason=None)

def test_structured_request_full_accounting_and_facts(record):
    generator=BrowserPlanGenerator(object(),record.settings);request=generator.prepare(record)
    assert request.agent_name=='PLANNER' and request.model=='configured'
    assert request.context_selection.original_chars==request.context_selection.selected_chars==len(request.user_input)
    assert request.context_selection.selected_bytes==len(request.user_input.encode('utf-8'))
    assert json.loads(request.user_input)['approved_browser_facts']==FACTS
    assert validate_candidate(record,output(),BrowserExecutionPolicy())==output()

@pytest.mark.parametrize('field',['test_hash','target_hash','project_id'])
def test_input_provenance_cannot_be_forged(record,field):
    values=record.model_dump();values[field]=uuid4() if field=='project_id' else '0'*64
    with pytest.raises(ValueError):Record.model_validate(values)

@pytest.mark.parametrize('variant',['unknown','script','engine','scheme','extra-op','missing-op','missing-assert','wrong-expected','loose','screenshot','redirect','timeout'])
def test_strict_fail_closed_no_intent_changes(record,variant):
    plan=json.loads(json.dumps(PLAN))
    if variant=='unknown':plan['version']='unknown'
    elif variant=='script':plan['evaluate']='anything'
    elif variant=='engine':plan['steps'][1]['locator']={'strategy':'CSS','value':'xpath=//*'}
    elif variant=='scheme':plan['steps'][0]['path']='javascript:alert(1)'
    elif variant=='extra-op':plan['steps'].insert(1,{'action':'CLICK','locator':LOC})
    elif variant=='missing-op':plan['steps']=plan['steps'][1:]
    elif variant=='missing-assert':plan['steps']=plan['steps'][:1]
    elif variant=='wrong-expected':plan['steps'][1]['text']='Different'
    elif variant=='loose':plan['steps'][1]['exact']=False
    elif variant=='screenshot':plan['screenshot_limit']=1
    elif variant=='redirect':plan['redirect_limit']=1
    else:plan['steps'][0]['timeout_ms']=120001
    with pytest.raises(ValueError):validate_candidate(record,output(plan),BrowserExecutionPolicy())


def test_insufficient_facts_and_context_overflow_do_not_guess_or_truncate(record):
    test=record.test.model_copy(update={'preconditions':('ordinary human context',)})
    candidate=record.model_copy(update={'test':test})
    with pytest.raises(ValueError,match='INSUFFICIENT'):validate_candidate(candidate,output(),BrowserExecutionPolicy())
    test=record.test.model_copy(update={'preconditions':tuple('x'*1999 for _ in range(20)),
        'steps':tuple(record.test.steps[0].model_copy(update={'index':i,'action':'a'*1999,'expected':'b'*1999}) for i in range(1,21))})
    with pytest.raises(ModelError,match='MODEL_CONTEXT_LIMIT'):BrowserPlanGenerator(object(),record.settings).prepare(record.model_copy(update={'test':test}))


def test_facts_operation_count_bound_and_cannot_plan_shape():
    with pytest.raises(ValueError):ApprovedBrowserFacts.model_validate({**FACTS,'required_actions':[['CLICK']*51]})
    with pytest.raises(ValueError):Output(disposition='CANNOT_PLAN',plan=PLAN,step_bindings=[1,1],unable_reason='MISSING_LOCATOR')
