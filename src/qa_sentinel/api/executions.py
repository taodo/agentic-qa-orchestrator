"""Durable execution-request transport; worker lifecycle writes are not HTTP APIs."""
from uuid import UUID
from fastapi import APIRouter
from qa_sentinel.application import ExecutionJobView, CollectionPage
from .dependencies import Application, CollectionLimit
from .models import RequestModel
from .errors import ERROR_RESPONSES

router = APIRouter(tags=["Executions"], responses=ERROR_RESPONSES)


class ExecutionRequest(RequestModel):
    """No client-selected owner, workspace or job lifecycle fields."""


@router.post("/tasks/{task_id}/executions", response_model=ExecutionJobView, status_code=202)
def request_execution(task_id: UUID, application: Application, body: ExecutionRequest | None = None):
    return application.request_task_execution(task_id)


@router.get("/tasks/{task_id}/executions", response_model=CollectionPage[ExecutionJobView])
def list_executions(task_id: UUID, application: Application, limit: CollectionLimit = 50):
    return application.list_task_execution_jobs(task_id, limit=limit)


@router.get("/executions/{execution_id}", response_model=ExecutionJobView)
def get_execution(execution_id: UUID, application: Application):
    return application.get_execution_job(execution_id)
