"""Task HTTP endpoints; no orchestration, tool or database access."""
from uuid import UUID
from fastapi import APIRouter
from qa_sentinel.application import (
    TaskDetail, CollectionPage, TimelineEntry, ArtifactView, TestRunView,
    ErrorView, DecisionView, GateEvaluationView, InvocationView,
)
from .dependencies import Application, CollectionLimit, TimelineLimit
from .errors import ERROR_RESPONSES

router = APIRouter(prefix="/tasks", tags=["Tasks"], responses=ERROR_RESPONSES)


@router.get("/{task_id}", response_model=TaskDetail)
def get_task(task_id: UUID, application: Application):
    return application.get_task_detail(task_id)


@router.post("/{task_id}/run", response_model=TaskDetail)
def run_task(task_id: UUID, application: Application):
    return application.run_task(task_id)


@router.post("/{task_id}/resume", response_model=TaskDetail)
def resume_task(task_id: UUID, application: Application):
    return application.resume_task(task_id)


@router.get("/{task_id}/timeline", response_model=CollectionPage[TimelineEntry])
def timeline(task_id: UUID, application: Application, limit: TimelineLimit = 50):
    return application.get_task_timeline(task_id, limit=limit)


@router.get("/{task_id}/artifacts", response_model=CollectionPage[ArtifactView])
def artifacts(task_id: UUID, application: Application, limit: CollectionLimit = 50):
    return application.get_task_artifacts(task_id, limit=limit)


@router.get("/{task_id}/test-runs", response_model=CollectionPage[TestRunView])
def test_runs(task_id: UUID, application: Application, limit: CollectionLimit = 50):
    return application.get_task_test_runs(task_id, limit=limit)


@router.get("/{task_id}/errors", response_model=CollectionPage[ErrorView])
def errors(task_id: UUID, application: Application, limit: CollectionLimit = 50):
    return application.get_task_errors(task_id, limit=limit)


@router.get("/{task_id}/decisions", response_model=CollectionPage[DecisionView])
def decisions(task_id: UUID, application: Application, limit: CollectionLimit = 50):
    return application.get_task_decisions(task_id, limit=limit)


@router.get("/{task_id}/gates", response_model=CollectionPage[GateEvaluationView])
def gates(task_id: UUID, application: Application, limit: CollectionLimit = 50):
    return application.get_task_gate_evaluations(task_id, limit=limit)


@router.get("/{task_id}/invocations", response_model=CollectionPage[InvocationView])
def invocations(task_id: UUID, application: Application, limit: CollectionLimit = 50):
    return application.get_task_invocations(task_id, limit=limit)
