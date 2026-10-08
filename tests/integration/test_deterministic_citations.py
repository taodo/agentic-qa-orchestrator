"""Offline StayFinder-style citation regression through the real extraction boundary."""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from qa_sentinel.api import create_api_app
from qa_sentinel.application import ApplicationError, QASentinelApplication, ProjectExecutionResolver
from qa_sentinel.projects import ProjectRuntimeRegistry
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.models import CampaignRequirementRow
from test_preparation_recovery import setup_requirement, revised
from test_requirement_extraction import harness, put, response


def test_stayfinder_valid_range_does_not_require_model_copied_excerpt(harness):
    app, _, _, project, campaign, mock, _ = harness
    content = (Path(__file__).parents[1] / "fixtures/stayfinder_availability.md").read_text(encoding="utf-8")
    source = put(app, project, campaign, content)
    def output(call):
        result = response(call)
        result["requirements"][0]["source_references"][0].update(
            start_line=7, end_line=9)
        return result
    mock.queue.clear(); mock.queue.append(output)
    result = app.extract_campaign_requirements(project.id, campaign.id, source.id)
    assert result.status == "SUCCEEDED", result.error_code
    requirement = app.list_campaign_requirements(project.id, campaign.id).items[0]
    assert requirement.source_references[0].excerpt == "\n".join(content.split("\n")[6:9])
    assert len(mock.calls) == 1
    call = mock.calls[0]
    assert call["tools"] == [] and call["tool_choice"] == "none" and not call["store"]
    assert "excerpt" not in call["text"]["format"]["schema"]["$defs"]["CitationRange"]["properties"]
    data = json.loads(call["input"][0]["content"])
    assert data["line_count"] == 100 and len(data["line_numbered_text"].split("\n")) == 100
    assert data["line_numbered_text"].split("\n")[7] == "0008 | " + content.split("\n")[7]
    assert result.context_selection.selected_chars == len(call["input"][0]["content"])
    assert result.usage.total_tokens.total == 30


def test_explicit_retry_preserves_historical_failure_and_one_call_per_attempt(harness):
    app, _, engine, p, c, mock, _ = harness
    source = put(app,p,c,"\n  Guests select dates  \n\nCheck-out must follow check-in.")
    def success(call):
        result = response(call)
        result["requirements"][0]["source_references"][0].update(start_line=1,end_line=3)
        return result
    mock.queue.clear(); mock.queue.extend([lambda call:response(call,invalid=True),success])
    first = app.extract_campaign_requirements(p.id,c.id,source.id)
    assert first.error_code == "EXTRACTION_INVALID_CITATION" and first.retryable
    assert len(mock.calls) == 1 and first.usage.total_tokens.total == 30
    assert app.extract_campaign_requirements(p.id,c.id,source.id) == first
    assert len(mock.calls) == 1
    second = app.retry_campaign_extraction(p.id,c.id,first.id)
    assert second.status == "SUCCEEDED" and second.attempt_number == 2 and second.parent_attempt_id == first.id
    assert len(mock.calls) == 2 and second.usage.total_tokens.total == 30
    assert app.retry_campaign_extraction(p.id,c.id,first.id) == second and len(mock.calls) == 2
    records = app.list_campaign_requirements(p.id,c.id).items
    assert records[0].source_references[0].excerpt == "\n  Guests select dates  \n"
    history = app.list_campaign_extraction_attempts(p.id,c.id,source.id).items
    assert history[1].error_code == first.error_code and history[1].usage == first.usage
    assert history[1].output.generated_count == 0
    engine.dispose()
    assert app.list_campaign_extraction_attempts(p.id,c.id,source.id).items == history
    assert len(mock.calls) == 2


@pytest.mark.parametrize("variant", ["resolved", "markers", "outside", "original-only"])
def test_revision_canonicalizes_combined_source_addendum_with_one_call(harness,variant):
    app, _, _, p, c, mock, _ = harness
    _, original = setup_requirement(harness)
    assert len(mock.calls) == 1
    facts = "  Stay 2026-10-10 → 2026-10-12  \r\n\r\nCheck-out is exclusive."
    clarification = app.add_requirement_clarification(p.id,c.id,original.id,request_key="grounding-revision",content=facts)
    assert len(mock.calls) == 1  # Clarification saving is no-model.
    combined = app.get_campaign_source(p.id,c.id,clarification.source_id)
    def revise(call):
        result = revised(call,markers=variant=="markers",original_only=variant=="original-only")
        ref = result["requirements"][0]["source_references"][0]
        if variant == "outside": ref["end_line"] = combined.line_count + 1
        elif variant != "original-only": ref["end_line"] = clarification.first_fact_line + 2
        return result
    mock.queue.append(revise)
    result = app.extract_campaign_requirements(p.id,c.id,combined.id)
    assert len(mock.calls) == 2
    request = json.loads(mock.calls[-1]["input"][0]["content"])
    assert request["clarification_first_fact_line"] == clarification.first_fact_line
    assert request["line_numbered_text"].split("\n")[clarification.first_fact_line-1] == f"{clarification.first_fact_line:04d} |   Stay 2026-10-10 → 2026-10-12  "
    assert result.context_selection.selected_chars == len(mock.calls[-1]["input"][0]["content"])
    assert result.context_selection.selected_bytes == len(mock.calls[-1]["input"][0]["content"].encode("utf-8"))
    assert result.usage.total_tokens.total == 30
    if variant in {"outside","original-only"}:
        assert result.error_code == "EXTRACTION_INVALID_CITATION"
        assert app.list_campaign_requirements(p.id,c.id).items[0].id == original.id
    else:
        assert result.status == "SUCCEEDED"
        requirement = app.list_campaign_requirements(p.id,c.id).items[0]
        assert requirement.key == original.key and requirement.id != original.id
        assert requirement.source_references[0].excerpt == combined.normalized_text.split("\n",clarification.first_fact_line-1)[-1]
        assert requirement.review_status == ("NEEDS_CLARIFICATION" if variant=="markers" else "READY_FOR_REVIEW")
        assert app.get_requirement_history(p.id,c.id,requirement.id).items[-1].version == 2
    assert app.extract_campaign_requirements(p.id,c.id,combined.id).id == result.id and len(mock.calls)==2


def test_existing_persisted_substring_citation_remains_readable_without_rewrite(harness):
    app, factory, engine, p, c, mock, _ = harness
    source = put(app,p,c)
    attempt = app.extract_campaign_requirements(p.id,c.id,source.id)
    requirement = app.list_campaign_requirements(p.id,c.id).items[0]
    # Simulate an already-persisted pre-3.9 citation (substring was valid before).
    with UnitOfWork(factory) as uow:
        row = uow.session.get(CampaignRequirementRow,str(requirement.id))
        references = json.loads(json.dumps(row.source_references))
        references[0]["excerpt"] = "must log in"
        row.source_references = references
        uow.commit()
    engine.dispose()
    restarted = QASentinelApplication(factory,ProjectExecutionResolver(ProjectRuntimeRegistry([]),[]))
    stored = restarted.get_campaign_requirement(p.id,c.id,requirement.id)
    assert stored.source_references[0].excerpt == "must log in"
    assert restarted.extract_campaign_requirements(p.id,c.id,source.id) == attempt and len(mock.calls)==1
    with TestClient(create_api_app(restarted)) as client:
        body = client.get(f"/api/v1/projects/{p.id}/campaigns/{c.id}/requirements/{requirement.id}").json()
        assert body["source_references"][0]["excerpt"] == "must log in"
    assert restarted.get_campaign_requirement(p.id,c.id,requirement.id) == stored


def test_numbered_context_overflow_blocks_before_attempt_and_provider(harness):
    app, _, engine, p, c, mock, _ = harness
    source = put(app,p,c,"\n".join(["x"*55]*1000))
    with pytest.raises(ApplicationError,match="EXTRACTION_CONTEXT_LIMIT"):
        app.extract_campaign_requirements(p.id,c.id,source.id)
    assert not mock.calls
    assert app.list_campaign_extraction_attempts(p.id,c.id,source.id).items == ()


def test_new_persistence_write_rechecks_exact_canonical_citation(harness):
    from datetime import datetime, timezone
    from qa_sentinel.domain.campaign_content import CampaignRequirement, RequirementExtraction
    app, factory, _, p, c, _, _ = harness
    source = put(app,p,c,"User must log in. Full source line.")
    attempt = RequirementExtraction(project_id=p.id,campaign_id=c.id,source_id=source.id,
        source_hash=source.content_hash,model="test-model")
    with UnitOfWork(factory) as uow:
        uow.campaign_content.reserve(attempt); uow.commit()
    requirement = CampaignRequirement(project_id=p.id,campaign_id=c.id,extraction_id=attempt.id,
        key="LOGIN",logical_key="legacy-substring-must-not-write",title="Login",description="Login required",
        acceptance_criteria=[dict(key="C1",text="Login required")],information_markers=[],review_status="READY_FOR_REVIEW",
        source_references=[dict(source_id=source.id,source_hash=source.content_hash,start_line=1,end_line=1,excerpt="User must log in.")])
    completed = RequirementExtraction.model_validate({**attempt.model_dump(),"status":"SUCCEEDED","finished_at":datetime.now(timezone.utc)})
    with UnitOfWork(factory) as uow:
        with pytest.raises(ValueError,match="EXTRACTION_INVALID_CITATION"):
            uow.campaign_content.finish(completed,[requirement])
    assert app.list_campaign_requirements(p.id,c.id).items == ()
    assert app.list_campaign_extraction_attempts(p.id,c.id,source.id).items[0].status == "STARTED"
