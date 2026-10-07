"""Bounded read-only usage, event deduplication, missing data and run windows."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import json
import pytest
from fastapi.testclient import TestClient
from qa_sentinel.api import create_api_app
from qa_sentinel.application import QASentinelApplication, ProjectExecutionResolver, ApplicationError
from qa_sentinel.projects import ProjectRuntimeRegistry
from qa_sentinel.domain.invocation import AgentInvocation
from qa_sentinel.domain.event import Event
from qa_sentinel.domain.enums import AgentName as A
from qa_sentinel.domain.execution_job import ExecutionJob
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.execution_jobs import values
from qa_sentinel.persistence.models import ExecutionJobRow
from qa_sentinel.models.base import ModelMetadata

NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)


@pytest.fixture
def harness(migrated_factory):
    factory, _, _ = migrated_factory
    app = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]), []))
    project = app.create_project(key="usage", name="Usage")
    task = app.create_task(project_id=project.id, title="Usage", requirement="Required")
    return app, factory, project, task


def invocation(uow, task, *, agent=A.RESEARCHER, model="configured", attempt=1, status="COMPLETED"):
    record = AgentInvocation(task_id=task.id, agent=agent, model=model, reasoning_effort="medium",
        attempt=attempt, status=status, started_at=NOW, finished_at=None if status == "STARTED" else NOW+timedelta(seconds=10))
    uow.invocations.add(record)
    return record


def event(uow, inv, name, metadata=None, *, index=None, seconds=1, extra=None):
    payload = dict(extra or {})
    if index is not None:
        payload["turn_index"] = index
    if metadata is not None:
        payload["model_metadata"] = metadata
    uow.history.append_event(Event(task_id=inv.task_id, event_type=name,
        timestamp=NOW+timedelta(seconds=seconds), actor=dict(type="ORCHESTRATOR", id="qa-sentinel"),
        correlation=dict(invocation_id=inv.id), payload=payload))


def metadata(total=30, *, model="provider-version", reasoning=7):
    return ModelMetadata(model=model, input_tokens=10, output_tokens=20, total_tokens=total,
                         reasoning_tokens=reasoning, provider_response_id="same-response-id", latency_ms=1).model_dump(mode="json")


def test_multiturn_final_event_not_double_counted_and_retries_remain_distinct(harness):
    app, factory, _, task = harness
    with UnitOfWork(factory) as uow:
        research = invocation(uow, task)
        event(uow, research, "REPOSITORY_SESSION_STARTED")
        for index in (1, 2):
            event(uow, research, "MODEL_TURN_STARTED", index=index)
            event(uow, research, "MODEL_TURN_COMPLETED", metadata(), index=index)
        event(uow, research, "AGENT_COMPLETED", metadata())
        planner = invocation(uow, task, agent=A.PLANNER)
        event(uow, planner, "AGENT_COMPLETED", metadata(50, model="other-version"))
        retry = invocation(uow, task, attempt=2, status="FAILED")
        event(uow, retry, "AGENT_FAILED", metadata(10))
        unknown = invocation(uow, task, attempt=3, status="FAILED")
        event(uow, unknown, "AGENT_FAILED")
        uow.commit()
    result = app.get_task_model_usage(task.id)
    assert result.usage.records == 5
    assert result.usage.total_tokens.known_sum == 120
    assert result.usage.total_tokens.total is None and result.usage.total_tokens.missing_records == 1
    assert result.invocations[0].usage.total_tokens.total == 60
    assert result.by_agent[0].identity == "RESEARCHER" and result.by_agent[0].usage.total_tokens.known_sum == 70
    assert result.by_model[0].identity == "provider-version" and result.by_model[0].usage.total_tokens.total == 70
    assert result.by_stage[0].identity == "RESEARCHING"
    assert result.top_invocations == (research.id, planner.id, retry.id)
    assert result.cost_status == "NOT_CONFIGURED" and result.estimated_cost is None
    assert not result.truncated


@pytest.mark.parametrize("mode", ["missing", "zero", "reasoning-absent", "invalid-number"])
def test_usage_fields_missing_zero_and_reasoning_subcount_are_honest(harness, mode):
    app, factory, _, task = harness
    meta = metadata(reasoning=7)
    if mode == "missing":
        meta = None
    elif mode == "zero":
        meta.update(input_tokens=0, output_tokens=0, total_tokens=0, reasoning_tokens=0)
    elif mode == "reasoning-absent":
        meta.pop("reasoning_tokens")
    else:
        meta["total_tokens"] = True
    with UnitOfWork(factory) as uow:
        inv = invocation(uow, task)
        event(uow, inv, "AGENT_COMPLETED", meta)
        uow.commit()
    usage = app.get_task_model_usage(task.id).usage
    if mode == "zero":
        assert usage.total_tokens.total == 0 and usage.reasoning_tokens.total == 0
    elif mode in {"missing", "invalid-number"}:
        assert usage.total_tokens.total is None and usage.total_tokens.known_sum is None
        assert usage.total_tokens.missing_records == 1
    else:
        assert usage.total_tokens.total == 30  # Reasoning is never added to provider total.
        assert usage.reasoning_tokens.total is None and usage.reasoning_tokens.missing_records == 1


def test_unresolved_turn_is_unknown_and_fake_invocation_is_not_provider_usage(harness):
    app, factory, _, task = harness
    with UnitOfWork(factory) as uow:
        real = invocation(uow, task, status="STARTED")
        event(uow, real, "MODEL_TURN_STARTED", index=1)
        fake = invocation(uow, task, agent=A.PLANNER, model="fake")
        event(uow, fake, "AGENT_COMPLETED")
        uow.commit()
    result = app.get_task_model_usage(task.id)
    assert result.invocations[0].unresolved_records == 1 and result.invocations[0].usage.records == 1
    assert result.invocations[1].applicable is False and result.invocations[1].usage.records == 0
    assert result.usage.total_tokens.total is None and result.top_invocations == ()


def test_duplicate_turn_records_fail_honestly_instead_of_double_counting(harness):
    app, factory, _, task = harness
    with UnitOfWork(factory) as uow:
        inv = invocation(uow, task)
        event(uow, inv, "MODEL_TURN_STARTED", index=1)
        event(uow, inv, "MODEL_TURN_COMPLETED", metadata(), index=1)
        event(uow, inv, "MODEL_TURN_COMPLETED", metadata(), index=1)
        uow.commit()
    result = app.get_task_model_usage(task.id)
    assert result.invocations[0].inconsistent_history
    assert result.usage.records == 1 and result.usage.total_tokens.total is None
    assert result.usage.total_tokens.known_sum is None


def test_execution_job_usage_is_explicit_record_time_window_without_canonical_duplication(harness):
    app, factory, project, task = harness
    job = ExecutionJob(task_id=task.id, project_id=project.id, status="SUCCEEDED", created_at=NOW,
                       started_at=NOW+timedelta(seconds=4), finished_at=NOW+timedelta(seconds=7))
    with UnitOfWork(factory) as uow:
        inv = invocation(uow, task)
        event(uow, inv, "REPOSITORY_SESSION_STARTED")
        event(uow, inv, "MODEL_TURN_STARTED", index=1, seconds=1)
        event(uow, inv, "MODEL_TURN_COMPLETED", metadata(), index=1, seconds=2)
        event(uow, inv, "MODEL_TURN_STARTED", index=2, seconds=5)
        event(uow, inv, "MODEL_TURN_COMPLETED", metadata(), index=2, seconds=6)
        event(uow, inv, "AGENT_COMPLETED", metadata(), seconds=7)
        uow.session.add(ExecutionJobRow(**values(job)))
        uow.commit()
    result = app.get_task_model_usage(task.id, execution_job_id=job.id)
    assert result.scope == "EXECUTION_JOB_WINDOW" and result.execution_job_id == job.id
    assert result.usage.total_tokens.total == 30 and result.usage.records == 1
    assert app.get_task_model_usage(task.id).usage.total_tokens.total == 60
    with pytest.raises(ApplicationError, match="EXECUTION_JOB_NOT_FOUND"):
        app.get_task_model_usage(task.id, execution_job_id=uuid4())
    other = app.create_task(project_id=project.id, title="Other", requirement="Other")
    with pytest.raises(ApplicationError, match="PROJECT_TASK_MISMATCH"):
        app.get_task_model_usage(other.id, execution_job_id=job.id)


def test_bounded_collections_never_present_selected_subset_as_full_task_totals(harness, monkeypatch):
    app, factory, _, task = harness
    with UnitOfWork(factory) as uow:
        for attempt in range(1, 5):
            inv = invocation(uow, task, attempt=attempt)
            event(uow, inv, "AGENT_COMPLETED", metadata())
        uow.commit()
    result = app.get_task_model_usage(task.id, limit=2)
    assert len(result.invocations) == 2 and result.truncated
    assert result.usage.total_tokens.known_sum == 60 and result.usage.total_tokens.total is None
    monkeypatch.setattr("qa_sentinel.application.service.MAX_USAGE_EVENTS", 1)
    capped = app.get_task_model_usage(task.id)
    assert capped.truncated and capped.usage.total_tokens.total is None
    with pytest.raises(ApplicationError, match="INVALID_LIST_LIMIT"):
        app.get_task_model_usage(task.id, limit=201)


def test_usage_http_is_metadata_only_read_only_scoped_and_legacy_contract_unchanged(harness, monkeypatch):
    app, factory, project, task = harness
    with UnitOfWork(factory) as uow:
        inv = invocation(uow, task)
        event(uow, inv, "MODEL_TURN_COMPLETED", metadata(), index=1,
              extra={"turn": {"sensitive-source-body": "DO-NOT-EXPOSE" * 5000}})
        uow.commit()
    other = app.create_project(key="other", name="Other")
    import subprocess
    from pathlib import Path
    from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("No process")))
    monkeypatch.setattr(Path, "open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("No files")))
    monkeypatch.setattr(OpenAIModelAdapter, "generate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("No model")))
    monkeypatch.setattr(app._resolver, "resolve", lambda *a, **k: (_ for _ in ()).throw(AssertionError("No runtime")))
    before = app.get_task_detail(task.id)
    with TestClient(create_api_app(app)) as client:
        response = client.get(f"/api/v1/tasks/{task.id}/model-usage")
        assert response.status_code == 200
        assert response.json()["usage"]["total_tokens"]["total"] == 30
        assert "DO-NOT-EXPOSE" not in response.text and "provider_response_id" not in response.text
        assert client.get(f"/api/v1/tasks/{uuid4()}/model-usage").status_code == 404
        assert client.get(f"/api/v1/tasks/{task.id}/model-usage?limit=201").status_code == 422
        assert "usage" not in client.get(f"/api/v1/tasks/{task.id}/invocations").json()["items"][0]
    assert app.get_task_detail(task.id) == before
    with pytest.raises(ApplicationError, match="PROJECT_TASK_MISMATCH"):
        app.get_task_model_usage(task.id, project_id=other.id)



def test_model_group_and_top_consumer_output_is_bounded_without_losing_total(harness):
    app, factory, _, task = harness
    with UnitOfWork(factory) as uow:
        for attempt in range(1, 22):
            inv = invocation(uow, task, attempt=attempt)
            event(uow, inv, "AGENT_COMPLETED", metadata(30 + attempt, model=f"provider-{attempt:02d}"))
        uow.commit()
    result = app.get_task_model_usage(task.id)
    assert len(result.by_model) == 20 and result.model_groups_truncated
    assert len(result.top_invocations) == 10
    assert result.usage.total_tokens.total == sum(30+i for i in range(1,22))
    assert result.by_model[0].identity == "provider-21" and not result.truncated
