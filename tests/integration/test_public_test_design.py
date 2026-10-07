"""New design routes preserve public synthetic-only, Basic/session and CSRF policy."""
import pytest
from fastapi.testclient import TestClient
from qa_sentinel.host import composition
from qa_sentinel.host.web import create_host_app
from test_host import config,offline
from test_hosted import hosted,login,csrf,USER as HUSER,PASSWORD as HPASS,SECRET
from test_preview import preview,header,USER as PUSER,PASSWORD as PPASS
from test_campaign_test_specifications import case,markdown_text,seed_requirement

@pytest.mark.parametrize('mode',['preview','hosted'])
def test_public_design_is_deterministic_authenticated_and_never_real(config,monkeypatch,mode):
    for key,value in [('QA_SENTINEL_OPERATOR_USERNAME',HUSER),('QA_SENTINEL_OPERATOR_PASSWORD',HPASS),('QA_SENTINEL_SESSION_SECRET',SECRET),
        ('QA_SENTINEL_PREVIEW_USERNAME',PUSER),('QA_SENTINEL_PREVIEW_PASSWORD',PPASS)]:monkeypatch.setenv(key,value)
    monkeypatch.setattr('qa_sentinel.host.hosted.tempfile.gettempdir',lambda:str(config.database.parent.parent))
    def forbidden(*args,**kwargs):pytest.fail('Public mode must never construct real generation/extraction/SDK')
    for cls in (composition.TestSpecificationGenerator,composition.RequirementExtractor,composition.OpenAIModelAdapter):monkeypatch.setattr(cls,'__init__',forbidden)
    web=create_host_app(hosted(config) if mode=='hosted' else preview(config));app=web.state.host_composition.application
    assert app._test_generator is None and app._requirement_extractor is None
    project=app.list_projects().items[0];campaign=app.create_campaign(project.id,name='Synthetic design')
    req=seed_requirement(app._factory,project,campaign)
    path=f'/api/v1/projects/{project.id}/campaigns/{campaign.id}'
    body=dict(name='Synthetic existing tests',format='MARKDOWN',content=markdown_text([case(refs=[str(req.id)])]))
    with TestClient(web,base_url='https://testserver') as client:
        assert client.post(path+'/test-imports',json=body).status_code==401
        if mode=='hosted':
            assert login(client).status_code==303
            assert client.post(path+'/test-imports',json=body).status_code==403
            assert client.post(path+'/generate-tests',json=dict(requirement_ids=[str(req.id)])).status_code==403
            headers=csrf(client)
        else:headers=header()
        result=client.post(path+'/test-imports',json=body,headers=headers)
        assert result.status_code==201 and result.json()['status']=='IMPORTED'
        generated=client.post(path+'/generate-tests',json=dict(requirement_ids=[str(req.id)]),headers=headers)
        assert generated.status_code==409 and generated.json()['error']['code']=='GENERATION_NOT_CONFIGURED'
        read_headers={} if mode=='hosted' else headers
        assert client.get(path+'/test-specifications',headers=read_headers).json()['total_returned']==1
        assert client.get(path+'/test-generations',headers=read_headers).json()['items']==[]
        assert app.get_campaign(project.id,campaign.id)==campaign
