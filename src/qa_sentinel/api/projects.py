"""Project HTTP endpoints delegate one application use case each."""
from uuid import UUID
from fastapi import APIRouter
from qa_sentinel.application import ProjectView, TaskSummary, CollectionPage
from .dependencies import Application, CollectionLimit
from .models import CreateProjectRequest, UpdateProjectRequest, CreateTaskRequest
from .errors import ERROR_RESPONSES

router = APIRouter(prefix="/projects", tags=["Projects"], responses=ERROR_RESPONSES)


@router.get("", response_model=CollectionPage[ProjectView])
def list_projects(application: Application, limit: CollectionLimit = 50):
    return application.list_projects(limit=limit)


@router.post("", response_model=ProjectView, status_code=201)
def create_project(body: CreateProjectRequest, application: Application):
    return application.create_project(**body.model_dump())


@router.get("/{project_id}", response_model=ProjectView)
def get_project(project_id: UUID, application: Application):
    return application.get_project(project_id)


@router.patch("/{project_id}", response_model=ProjectView)
def update_project(project_id: UUID, body: UpdateProjectRequest, application: Application):
    return application.update_project(project_id, **body.model_dump(exclude_unset=True))


@router.get("/{project_id}/tasks", response_model=CollectionPage[TaskSummary])
def list_tasks(project_id: UUID, application: Application, limit: CollectionLimit = 50):
    return application.list_tasks_for_project(project_id, limit=limit)


@router.post("/{project_id}/tasks", response_model=TaskSummary, status_code=201)
def create_task(project_id: UUID, body: CreateTaskRequest, application: Application):
    return application.create_task(project_id=project_id, **body.model_dump())
