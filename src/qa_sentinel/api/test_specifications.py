"""Explicit deterministic import and reasoning-only test design routes."""
from uuid import UUID
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
