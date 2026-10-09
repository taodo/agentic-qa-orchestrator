"""Campaign-scoped immutable QA Run creation, snapshot reads and explicit synthetic Start."""
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Query, Body
from pydantic import BaseModel, ConfigDict
from qa_sentinel.application.models import CollectionPage
from qa_sentinel.application import CreateQARun, QARun, QARunRequirement, QARunTest
from qa_sentinel.application import QARunResults, QARunEvidenceView, MAX_TEST_EVIDENCE
from .dependencies import Application, CollectionLimit
from .errors import ERROR_RESPONSES

router = APIRouter(prefix="/projects/{project_id}/campaigns/{campaign_id}/runs", tags=["QA Runs"], responses=ERROR_RESPONSES)
SnapshotPosition = Annotated[int, Query(ge=0, le=1000)]


@router.post("", response_model=QARun, status_code=201)
def create_run(project_id: UUID, campaign_id: UUID, body: CreateQARun, application: Application):
    return application.create_qa_run(project_id, campaign_id, **body.model_dump())


@router.get("", response_model=CollectionPage[QARun])
def list_runs(project_id: UUID, campaign_id: UUID, application: Application, limit: CollectionLimit = 50):
    return application.list_qa_runs(project_id, campaign_id, limit=limit)


@router.get("/{run_id}", response_model=QARun)
def get_run(project_id: UUID, campaign_id: UUID, run_id: UUID, application: Application):
    return application.get_qa_run(project_id, campaign_id, run_id)


@router.get("/{run_id}/tests", response_model=CollectionPage[QARunTest])
def list_tests(project_id: UUID, campaign_id: UUID, run_id: UUID, application: Application,
               limit: CollectionLimit = 50, after_position: SnapshotPosition = 0):
    return application.list_qa_run_tests(project_id, campaign_id, run_id, limit=limit, after_position=after_position)


@router.get("/{run_id}/requirements", response_model=CollectionPage[QARunRequirement])
def list_requirements(project_id: UUID, campaign_id: UUID, run_id: UUID, application: Application,
                      limit: CollectionLimit = 50, after_position: SnapshotPosition = 0):
    return application.list_qa_run_requirements(project_id, campaign_id, run_id, limit=limit, after_position=after_position)


class StartRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.post("/{run_id}/start", response_model=QARun)
def start_run(project_id: UUID, campaign_id: UUID, run_id: UUID, application: Application, body: StartRunBody | None = Body(default=None)):
    return application.start_qa_run(project_id, campaign_id, run_id)


@router.get("/{run_id}/results", response_model=QARunResults)
def get_results(project_id: UUID, campaign_id: UUID, run_id: UUID, application: Application,
                limit: CollectionLimit = 50, after_position: SnapshotPosition = 0):
    return application.get_qa_run_results(project_id, campaign_id, run_id, limit=limit, after_position=after_position)


@router.get("/{run_id}/tests/{test_id}/evidence", response_model=CollectionPage[QARunEvidenceView])
def get_evidence(project_id: UUID, campaign_id: UUID, run_id: UUID, test_id: UUID, application: Application,
                 limit: CollectionLimit = 50, after_sequence: Annotated[int, Query(ge=0, le=MAX_TEST_EVIDENCE)] = 0):
    return application.list_qa_run_test_evidence(project_id, campaign_id, run_id, test_id, limit=limit, after_sequence=after_sequence)
