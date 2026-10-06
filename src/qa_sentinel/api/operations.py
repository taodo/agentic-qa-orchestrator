"""GET-only operational snapshots; stricter queries do not alter existing APIs."""
import re
from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Query, Response
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from qa_sentinel.application import (
    CollectionPage, OperationalSummaryView, ProjectOperationalSummaryView,
    TaskOperationalSummaryView, OperationalActivityView, OperationalAttention,
)
from qa_sentinel.application.operations import TaskState, ExecutionJobStatus
from .dependencies import Application
from .errors import ERROR_RESPONSES, error_response
from .models import ErrorEnvelope


class OperationalRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        allowed = {param.name for param in self.dependant.query_params}

        async def strict(request):
            keys = [key for key, _ in request.query_params.multi_items()]
            if (set(keys) - allowed or len(keys) != len(set(keys)) or
                    "limit" in keys and not re.fullmatch(r"[0-9]{1,3}", request.query_params["limit"])):
                return error_response(400, "REQUEST_VALIDATION_ERROR", "Request validation failed")
            try:
                return await handler(request)
            except RequestValidationError:
                return error_response(400, "REQUEST_VALIDATION_ERROR", "Request validation failed")
        return strict


router = APIRouter(prefix="/operations", tags=["Operations"], route_class=OperationalRoute,
    responses={**ERROR_RESPONSES, 400: {"model": ErrorEnvelope}})
Limit = Annotated[int, Query(ge=1, le=100)]
BoolQuery = Literal["true", "false"]


def no_store(response):
    response.headers["Cache-Control"] = "no-store"


@router.get("/summary", response_model=OperationalSummaryView)
def summary(application: Application, response: Response):
    no_store(response)
    return application.get_operational_summary()


@router.get("/projects", response_model=CollectionPage[ProjectOperationalSummaryView])
def projects(application: Application, response: Response, limit: Limit = 50):
    no_store(response)
    return application.list_project_operational_summaries(limit=limit)


@router.get("/tasks", response_model=CollectionPage[TaskOperationalSummaryView])
def tasks(application: Application, response: Response, limit: Limit = 50, project_id: UUID | None = None,
        task_state: TaskState | None = None, execution_status: ExecutionJobStatus | None = None,
        attention: OperationalAttention | None = None, reconciliation_attention: BoolQuery | None = None,
        active_only: BoolQuery = "false", attention_only: BoolQuery = "false"):
    no_store(response)
    return application.list_task_operational_summaries(limit=limit, project_id=project_id,
        task_state=task_state, execution_status=execution_status, attention=attention,
        reconciliation_attention=None if reconciliation_attention is None else reconciliation_attention == "true",
        active_only=active_only == "true", attention_only=attention_only == "true")


@router.get("/activity", response_model=CollectionPage[OperationalActivityView])
def activity(application: Application, response: Response, limit: Limit = 50, project_id: UUID | None = None):
    no_store(response)
    return application.list_operational_activity(limit=limit, project_id=project_id)
