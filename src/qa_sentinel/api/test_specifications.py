"""Explicit deterministic import and reasoning-only test design routes."""
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from qa_sentinel.application.product_v2 import ExecutionCandidate, TestEditEvidence
from qa_sentinel.domain.test_specification import TestDesign
from qa_sentinel.domain.campaign_content import Hash
from fastapi import APIRouter
from qa_sentinel.application import TestImportView,TestImportDetail,TestSpecificationView,TestGenerationView,CollectionPage
from .models import ImportTestsRequest,GenerateTestsRequest
from .dependencies import Application,CollectionLimit
from .errors import ERROR_RESPONSES

router=APIRouter(prefix='/projects/{project_id}/campaigns/{campaign_id}',tags=['Campaign Test Specifications'],responses=ERROR_RESPONSES)

@router.post('/test-imports',response_model=TestImportView,status_code=201)
def import_tests(project_id:UUID,campaign_id:UUID,body:ImportTestsRequest,application:Application):
    return application.import_campaign_tests(project_id,campaign_id,**body.model_dump())

@router.get('/test-imports',response_model=CollectionPage[TestImportView])
def list_imports(project_id:UUID,campaign_id:UUID,application:Application,limit:CollectionLimit=50):
    return application.list_campaign_test_imports(project_id,campaign_id,limit=limit)

@router.get('/test-imports/{import_id}',response_model=TestImportDetail)
def get_import(project_id:UUID,campaign_id:UUID,import_id:UUID,application:Application):
    return application.get_campaign_test_import(project_id,campaign_id,import_id)

@router.post('/generate-tests',response_model=TestGenerationView)
def generate_tests(project_id:UUID,campaign_id:UUID,body:GenerateTestsRequest,application:Application):
    return application.generate_campaign_tests(project_id,campaign_id,**body.model_dump())

@router.get('/test-generations',response_model=CollectionPage[TestGenerationView])
def list_generations(project_id:UUID,campaign_id:UUID,application:Application,limit:CollectionLimit=50):
    return application.list_campaign_test_generations(project_id,campaign_id,limit=limit)

@router.get('/test-generations/{generation_id}',response_model=TestGenerationView)
def get_generation(project_id:UUID,campaign_id:UUID,generation_id:UUID,application:Application):
    return application.get_campaign_test_generation(project_id,campaign_id,generation_id)

@router.get('/test-specifications',response_model=CollectionPage[TestSpecificationView])
def list_specifications(project_id:UUID,campaign_id:UUID,application:Application,limit:CollectionLimit=50):
    return application.list_campaign_test_specifications(project_id,campaign_id,limit=limit)

@router.get('/test-specifications/{test_spec_id}',response_model=TestSpecificationView)
def get_specification(project_id:UUID,campaign_id:UUID,test_spec_id:UUID,application:Application):
    return application.get_campaign_test_specification(project_id,campaign_id,test_spec_id)



@router.get('/execution-candidates',response_model=CollectionPage[ExecutionCandidate])
def execution_candidates(project_id:UUID,campaign_id:UUID,application:Application,limit:CollectionLimit=50,after_id:UUID=UUID(int=0)):
    return application.list_execution_candidates(project_id,campaign_id,limit=limit,after_id=after_id)



class EditTestRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    design: TestDesign
    previous_hash: Hash
    reviewer_label: str=Field(min_length=1,max_length=64,strict=True)
    note: str=Field(min_length=1,max_length=1000,strict=True)

@router.post('/test-specifications/{test_spec_id}/edits',response_model=TestSpecificationView,status_code=201)
def edit_test(project_id:UUID,campaign_id:UUID,test_spec_id:UUID,body:EditTestRequest,application:Application):
    return application.edit_campaign_test(project_id,campaign_id,test_spec_id,**body.model_dump())


class ExportTestRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    test_specification_ids: tuple[UUID,...]=Field(min_length=1,max_length=200)
    format: Literal["CSV","XLSX"]

class TestExport(BaseModel):
    filename: str
    media_type: str
    content_base64: str
    count: int

@router.post('/test-exports',response_model=TestExport)
def export_test_design(project_id:UUID,campaign_id:UUID,body:ExportTestRequest,application:Application):
    return application.export_campaign_tests(project_id,campaign_id,**body.model_dump())


@router.get('/test-specifications/{test_spec_id}/edit-evidence',response_model=TestEditEvidence | None)
def edit_evidence(project_id:UUID,campaign_id:UUID,test_spec_id:UUID,application:Application):
    return application.get_test_edit_evidence(project_id,campaign_id,test_spec_id)
