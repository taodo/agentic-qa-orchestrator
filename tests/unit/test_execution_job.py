from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from pydantic import ValidationError
from qa_sentinel.domain.execution_job import ExecutionJob, ExecutionJobStatus as Status

NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)


def job(**values):
    return ExecutionJob(task_id=uuid4(), project_id=uuid4(), created_at=NOW, **values)


def test_small_frozen_queued_request_has_no_workflow_or_sensitive_fields():
    record = job()
    assert record.status == Status.QUEUED
    assert record.started_at is record.finished_at is record.safe_error_code is None
    assert set(ExecutionJob.model_fields) == {"id", "task_id", "project_id", "status", "created_at", "started_at", "finished_at", "safe_error_code"}
    with pytest.raises(ValidationError): record.status = Status.RUNNING


@pytest.mark.parametrize("values", [
    {"started_at": NOW}, {"finished_at": NOW}, {"safe_error_code": "EXECUTION_FAILED"},
    {"status": "RUNNING"}, {"status": "RUNNING", "started_at": NOW, "finished_at": NOW},
    {"status": "SUCCEEDED", "started_at": NOW}, {"status": "SUCCEEDED", "finished_at": NOW},
    {"status": "SUCCEEDED", "started_at": NOW, "finished_at": NOW, "safe_error_code": "RUNTIME_STOPPED"},
    {"status": "STOPPED", "started_at": NOW, "finished_at": NOW},
    {"status": "FAILED", "started_at": NOW, "finished_at": NOW},
    {"status": "STOPPED", "started_at": NOW, "finished_at": NOW, "safe_error_code": "raw-secret-exception"},
    {"status": "FAILED", "started_at": NOW, "finished_at": NOW, "safe_error_code": "RUNTIME_STOPPED"},
    {"status": "RUNNING", "started_at": NOW - timedelta(seconds=1)},
    {"status": "SUCCEEDED", "started_at": NOW, "finished_at": NOW - timedelta(seconds=1)},
    {"status": "RUNNING", "started_at": NOW.replace(tzinfo=None)},
    {"workspace_root": "/private/workspace"}, {"exception": "raw-secret"}, {"api_key": "raw-secret"},
])
def test_invalid_lifecycles_and_extra_fields_rejected(values):
    with pytest.raises(ValidationError): job(**values)


@pytest.mark.parametrize("status,error", [("RUNNING", None), ("SUCCEEDED", None),
    ("STOPPED", "RUNTIME_STOPPED"), ("STOPPED", "EXECUTION_INTERRUPTED"), ("FAILED", "EXECUTION_FAILED")])
def test_valid_lifecycle_timestamps_normalized(status, error):
    offset = timezone(timedelta(hours=7))
    record = job(status=status, started_at=NOW.astimezone(offset),
        finished_at=None if status == "RUNNING" else NOW.astimezone(offset), safe_error_code=error)
    assert record.started_at == NOW and record.started_at.tzinfo == timezone.utc
