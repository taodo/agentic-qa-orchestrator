"""Offline read projections: exact action attribution, durable counts, no effects."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from qa_sentinel.api import create_api_app
from qa_sentinel.application import ApplicationError, QASentinelApplication, ProjectExecutionResolver
from qa_sentinel.projects import ProjectRuntimeRegistry
from qa_sentinel.models.base import ModelMetadata, ModelResponse, ModelError, ProviderErrorCategory
from qa_sentinel.persistence.ai_action_results import action_outputs
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from test_requirement_extraction import harness, put, response
from test_preparation_recovery import revised, setup_requirement
from test_campaign_test_specifications import harness as generation_harness, seed_requirement, generated


def metadata(**changes):
    return ModelMetadata(provider="fixture-provider", model="provider-reported-model", input_tokens=1169,
        output_tokens=1737, reasoning_tokens=516, total_tokens=2906, latency_ms=1, **changes)


def forbidden(*args, **kwargs):
    raise AssertionError("Read must not execute external work")


def test_extraction_counts_are_action_local_durable_and_creation_statuses(harness, monkeypatch):
    app, factory, engine, p, c, mock, extractor = harness
    def mixed(call):
        data = response(call)
        other = response(call, markers=True)["requirements"][0]
        other["key"] = "ERRORS"
        data["requirements"].append(other)
        return data
    mock.queue.clear(); mock.queue.append(mixed)
    original = extractor.extract
    extractor.extract = lambda request: ModelResponse(parsed_output=original(request).parsed_output, metadata=metadata())
    source = put(app,p,c)
    result = app.extract_campaign_requirements(p.id,c.id,source.id)
    assert result.output.generated_count == 2
    assert result.output.ready_for_review_count == result.output.needs_clarification_count == 1
    assert (result.configured_model,result.provider_model,result.provider)==("test-model","provider-reported-model","fixture-provider")
    assert [getattr(result.usage,k).total for k in ("input_tokens","output_tokens","reasoning_tokens","total_tokens")] == [1169,1737,516,2906]
    req = next(r for r in app.list_campaign_requirements(p.id,c.id).items if r.key=="LOGIN")
    app.review_campaign_requirement(p.id,c.id,req.id,reviewer_label="qa")
    seed_requirement(factory,p,c,"UNRELATED")
    monkeypatch.setattr(extractor,"extract",forbidden)
    monkeypatch.setattr(app._resolver,"resolve",forbidden)
    import subprocess
    monkeypatch.setattr(subprocess,"Popen",forbidden)
    assert app.list_campaign_extraction_attempts(p.id,c.id,source.id).items[0] == result
    assert next(s for s in app.list_campaign_sources(p.id,c.id).items if s.id==source.id).latest_extraction == result
    assert app.extract_campaign_requirements(p.id,c.id,source.id) == result  # terminal replay only
    engine.dispose()
    restarted=QASentinelApplication(factory,ProjectExecutionResolver(ProjectRuntimeRegistry([]),[]))
    assert restarted.list_campaign_extraction_attempts(p.id,c.id,source.id).items[0] == result
    client=TestClient(create_api_app(restarted));base=f"/api/v1/projects/{p.id}/campaigns/{c.id}"
    body=client.get(base+f"/sources/{source.id}/extractions").json()["items"][0]
    assert body["output"]["generated_count"]==2 and body["usage"]["reasoning_tokens"]["total"]==516
    foreign=app.create_project(key="foreign-results",name="Foreign")
    assert client.get(f"/api/v1/projects/{foreign.id}/campaigns/{c.id}/sources/{source.id}/extractions").status_code==409
    assert len(mock.calls)==1


@pytest.mark.parametrize("fields", [{"total_tokens":30},{},{"input_tokens":0,"output_tokens":0,"reasoning_tokens":0,"total_tokens":0}])
def test_partial_unknown_and_authoritative_zero_usage_survive_reads(harness,fields):
    app,_,_,p,c,_,extractor=harness
    original=extractor.extract
    extractor.extract=lambda request: ModelResponse(parsed_output=original(request).parsed_output,
        metadata=ModelMetadata(model="reported",latency_ms=1,**fields))
    source=put(app,p,c); result=app.extract_campaign_requirements(p.id,c.id,source.id)
    persisted=app.list_campaign_extraction_attempts(p.id,c.id,source.id).items[0]
    assert persisted==result
    for key in ("input_tokens","output_tokens","reasoning_tokens","total_tokens"):
        assert getattr(persisted.usage,key).total==fields.get(key)


def test_failed_usage_is_retained_and_started_counts_are_unknown(harness):
    app,factory,_,p,c,_,extractor=harness
    def fail(request):raise ModelError(ProviderErrorCategory.TIMEOUT,metadata=metadata())
    extractor.extract=fail;source=put(app,p,c)
    result=app.extract_campaign_requirements(p.id,c.id,source.id)
    assert result.status=="FAILED" and result.retryable and result.output.generated_count==0
    assert result.usage.total_tokens.total==2906 and result.error_code=="MODEL_TIMEOUT"
    assert app.list_campaign_sources(p.id,c.id).items[0].latest_extraction==result
    from qa_sentinel.domain.campaign_content import RequirementExtraction
    other=put(app,p,c,text_="Different source")
    attempt=RequirementExtraction(project_id=p.id,campaign_id=c.id,source_id=other.id,source_hash=other.content_hash,model="fixture")
    with UnitOfWork(factory) as uow:
        uow.campaign_content.reserve(attempt);uow.commit()
    started=app.list_campaign_extraction_attempts(p.id,c.id,other.id).items[0]
    assert started.output is None and started.usage.total_tokens.total is None and started.provider is None


@pytest.mark.parametrize("markers",[False,True])
def test_revision_identity_and_status_are_reconstructed_without_provider(harness,markers):
    app,_,_,p,c,mock,extractor=harness
    source,old=setup_requirement(harness)
    saved=app.add_requirement_clarification(p.id,c.id,old.id,request_key="summary-facts",content="Grounded facts")
    assert len(mock.calls)==1
    mock.queue.append(lambda call:revised(call,markers=markers))
    result=app.extract_campaign_requirements(p.id,c.id,saved.source_id)
    identity=result.output.revised_requirement
    assert identity.key==old.key and identity.version==2 and identity.id!=old.id
    assert identity.review_status==("NEEDS_CLARIFICATION" if markers else "READY_FOR_REVIEW")
    assert result.output.needs_clarification_count==int(markers)
    extractor.extract=forbidden
    assert app.list_campaign_extraction_attempts(p.id,c.id,saved.source_id).items[0]==result
    original=app.list_campaign_extraction_attempts(p.id,c.id,source.id).items[0]
    assert original.output.generated_count==1 and original.output.needs_clarification_count==1
    assert len(mock.calls)==2


def test_generation_history_reuses_existing_durable_attempts_and_inherited_facts(generation_harness,monkeypatch):
    app,factory,engine,p,c,requirements,mock=generation_harness
    blocked=seed_requirement(factory,p,c,"BLOCKED",markers=[dict(kind="AMBIGUITY",description="Missing expected result")])
    # Seed an immutable pre-3.10 generation: new unapproved requests are now rejected.
    from qa_sentinel.agents.test_generation import generation_identity,GeneratedTestsOutput
    from qa_sentinel.domain.test_specification import TestGeneration,TestMarker
    from qa_sentinel.application.test_specifications import canonical_spec
    from qa_sentinel.persistence.models import TestGenerationRow
    from qa_sentinel.persistence.unit_of_work import UnitOfWork
    from test_campaign_test_specifications import case
    versions,identity=generation_identity([blocked])
    attempt=TestGeneration(project_id=p.id,campaign_id=c.id,requirement_versions=versions,request_hash=identity,model='fixture')
    item=case();item.pop('requirement_refs');item['requirement_ids']=[blocked.id]
    parsed=GeneratedTestsOutput(selected_requirement_ids=[blocked.id],tests=[item])
    spec=canonical_spec(attempt,parsed.tests[0],[blocked.id],markers=[TestMarker(kind='AMBIGUITY',description='Missing expected result')])
    with UnitOfWork(factory) as uow:
        from qa_sentinel.persistence.test_specifications import row_values
        values=row_values(attempt);values['metadata_json']=values.pop('metadata')
        uow.session.add(TestGenerationRow(**values));uow.session.flush()
        completed=TestGeneration.model_validate(attempt.model_dump()|dict(status='SUCCEEDED',finished_at=datetime.now(timezone.utc)))
        uow.test_specifications.finish(completed,[spec]);uow.commit()
    result=app.get_campaign_test_generation(p.id,c.id,attempt.id)
    assert result.output.generated_count==result.output.needs_clarification_count==result.output.inherited_clarification_count==1
    assert result.output.ready_for_review_count==0 and result.output.revised_requirement is None
    monkeypatch.setattr(app._test_generator,"generate",forbidden)
    monkeypatch.setattr(app._resolver,"resolve",forbidden)
    import subprocess
    monkeypatch.setattr(subprocess,"Popen",forbidden)
    engine.dispose(); restarted=QASentinelApplication(factory,ProjectExecutionResolver(ProjectRuntimeRegistry([]),[]))
    client=TestClient(create_api_app(restarted));base=f"/api/v1/projects/{p.id}/campaigns/{c.id}"
    assert client.get(base+"/test-generations?limit=1").json()["items"][0]["output"]["inherited_clarification_count"]==1
    assert client.get(base+f"/test-generations/{result.id}").json()["output"]["generated_count"]==1
    assert restarted.get_campaign_test_generation(p.id,c.id,result.id)==result
    with pytest.raises(ApplicationError,match='GENERATION_REQUIREMENT_NOT_APPROVED'):
        app.generate_campaign_tests(p.id,c.id,requirement_ids=[blocked.id])
    foreign=app.create_project(key="foreign-generation",name="Foreign")
    assert client.get(f"/api/v1/projects/{foreign.id}/campaigns/{c.id}/test-generations").status_code==409
    with engine.connect() as connection:
        assert all(connection.scalar(text(f"SELECT count(*) FROM {name}"))==0 for name in ("tasks","execution_jobs","invocations","test_runs"))
    assert len(mock.calls)==0


def test_output_projection_rejects_unbounded_or_mixed_owners():
    record=SimpleNamespace(id=uuid4(),project_id=uuid4(),campaign_id=uuid4())
    with pytest.raises(ValueError,match="bound"):action_outputs(None,[record]*201)
    other=SimpleNamespace(id=uuid4(),project_id=uuid4(),campaign_id=record.campaign_id)
    with pytest.raises(ValueError,match="ownership"):action_outputs(None,[record,other])


def test_generation_creation_counts_survive_later_approval_and_bounded_listing(generation_harness):
    app,_,_,p,c,requirements,mock=generation_harness
    result=app.generate_campaign_tests(p.id,c.id,requirement_ids=[requirements[0].id])
    assert result.output.generated_count==result.output.ready_for_review_count==1
    assert result.output.needs_clarification_count==result.output.inherited_clarification_count==0
    spec=app.list_campaign_test_specifications(p.id,c.id).items[0]
    app.review_campaign_test_specification(p.id,c.id,spec.id,reviewer_label="qa")
    assert app.get_campaign_test_generation(p.id,c.id,result.id)==result
    mock.queue.append(generated)
    app.generate_campaign_tests(p.id,c.id,requirement_ids=[requirements[1].id])
    listed=app.list_campaign_test_generations(p.id,c.id,limit=1)
    assert listed.truncated and listed.total_returned==1
    assert listed.items[0].output.generated_count==1  # never Campaign-wide count two


def test_failed_generation_retains_known_usage_and_zero_accepted_outputs(generation_harness):
    app,_,_,p,c,requirements,mock=generation_harness
    def fail(request):raise ModelError(ProviderErrorCategory.SERVER_ERROR,metadata=metadata())
    app._test_generator.generate=fail
    result=app.generate_campaign_tests(p.id,c.id,requirement_ids=[requirements[0].id])
    assert result.status=="FAILED" and result.output.generated_count==0
    assert result.provider=="fixture-provider" and result.usage.reasoning_tokens.total==516
    assert app.list_campaign_test_generations(p.id,c.id).items[0]==result
    assert not mock.calls
