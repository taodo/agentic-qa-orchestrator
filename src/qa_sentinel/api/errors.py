"""Deterministic safe HTTP mapping, independent of exception messages."""
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from qa_sentinel.application import ApplicationError, ApplicationErrorCode as Code
from .models import ErrorEnvelope, ErrorDetail


ERROR_MAPPING = {
    Code.REVIEW_SIZE_LIMIT: (413, "Review request exceeds supported size"),
    Code.REVIEW_NOT_REVIEWABLE: (409, "Object is not ready for explicit approval"),
    Code.REVIEW_CONFLICT: (409, "Approval intent conflicts with the immutable review evidence"),
    Code.REVIEW_EVIDENCE_INVALID: (409, "Review evidence does not match immutable content"),
    Code.CAMPAIGN_TEST_CHILD_NOT_FOUND: (404, "Campaign test record not found"),
    Code.CAMPAIGN_TEST_CHILD_MISMATCH: (409, "Test record does not belong to the requested Campaign"),
    Code.GENERATION_NOT_CONFIGURED: (409, "Test generation is not configured"),
    Code.GENERATION_CONTEXT_LIMIT: (422, "Selected Requirements exceed the generation context limit"),
    Code.GENERATION_RECONCILIATION_REQUIRED: (409, "Unresolved generation requires explicit reconciliation"),
    Code.CAMPAIGN_SOURCE_NOT_FOUND: (404, "Campaign source not found"),
    Code.CAMPAIGN_SOURCE_MISMATCH: (409, "Source does not belong to the requested Campaign"),
    Code.CAMPAIGN_REQUIREMENT_NOT_FOUND: (404, "Campaign requirement not found"),
    Code.CAMPAIGN_REQUIREMENT_MISMATCH: (409, "Requirement does not belong to the requested Campaign"),
    Code.SOURCE_SIZE_LIMIT: (413, "Source exceeds supported size"),
    Code.SOURCE_NOT_INGESTED: (409, "Source is not ingested"),
    Code.EXTRACTION_NOT_CONFIGURED: (409, "Requirement extraction is not configured"),
    Code.EXTRACTION_CONTEXT_LIMIT: (422, "Complete source exceeds the extraction context limit"),
    Code.EXTRACTION_RECONCILIATION_REQUIRED: (409, "Unresolved extraction requires explicit reconciliation"),

    Code.PROJECT_NOT_FOUND: (404, "Project not found"),
    Code.TASK_NOT_FOUND: (404, "Task not found"),
    Code.CAMPAIGN_NOT_FOUND: (404, "Campaign not found"),
    Code.PROJECT_CAMPAIGN_MISMATCH: (409, "Campaign does not belong to the requested Project"),
    Code.CAMPAIGN_INVALID_TRANSITION: (409, "Campaign preparation transition is invalid"),
    Code.PROJECT_KEY_EXISTS: (409, "Project key already exists"),
    Code.PROJECT_TASK_MISMATCH: (409, "Task does not belong to the requested Project"),
    Code.PROJECT_RUNTIME_NOT_CONFIGURED: (409, "Project runtime is not configured"),
    Code.PROJECT_RUNTIME_MISMATCH: (409, "Project runtime configuration does not match"),
    Code.TASK_NOT_BLOCKED: (409, "Task is not blocked"),
    Code.TASK_RESUME_STATE_MISSING: (409, "Task has no resume state"),
    Code.TASK_RESUME_STATE_INVALID: (409, "Task resume state is invalid"),
    Code.RUNTIME_STOPPED: (409, "Task execution stopped; inspect persisted evidence"),
    Code.TASK_RECONCILIATION_REQUIRED: (409, "Task reconciliation is required; inspect the assessment before continuing"),
    Code.EXECUTION_JOB_NOT_FOUND: (404, "Execution job not found"),
    Code.TASK_EXECUTION_ALREADY_ACTIVE: (409, "Task execution is already active"),
    Code.TASK_EXECUTION_TERMINAL: (409, "Task is terminal; use synchronous Run for the existing terminal check"),
    Code.EXECUTION_JOB_INVALID_STATE: (409, "Execution job state is invalid"),
    Code.INVALID_INPUT: (422, "Invalid application input"),
    Code.INVALID_LIST_LIMIT: (422, "Invalid collection limit"),
    Code.PERSISTENCE_ERROR: (500, "Persistence operation failed"),
}

ERROR_RESPONSES = {status: {"model": ErrorEnvelope} for status in (404, 409, 413, 422, 500)}


def error_response(status, code, message):
    envelope = ErrorEnvelope(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status, content=envelope.model_dump(mode="json"))


async def application_error_handler(request, exc: ApplicationError):
    status, message = ERROR_MAPPING[exc.code]
    return error_response(status, exc.code.value, message)


async def validation_error_handler(request, exc: RequestValidationError):
    return error_response(422, "REQUEST_VALIDATION_ERROR", "Request validation failed")


async def http_error_handler(request, exc: HTTPException):
    # Framework detail strings/headers are never echoed.
    message = {404: "Route not found", 405: "Method not allowed"}.get(exc.status_code, "HTTP request failed")
    return error_response(exc.status_code, "HTTP_ERROR", message)


async def internal_error_handler(request, exc: Exception):
    return error_response(500, "INTERNAL_ERROR", "Internal server error")
