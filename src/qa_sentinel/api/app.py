"""Explicit ASGI application factory; importing this module performs no host IO."""
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from qa_sentinel.application import QASentinelApplication, ApplicationError
from . import projects, tasks, executions, operations, campaigns, campaign_content, test_specifications
from .errors import (
    application_error_handler, validation_error_handler, http_error_handler, internal_error_handler,
)
from .models import HealthView
from .source_body_limit import SourceBodyLimit


def create_api_app(application: QASentinelApplication) -> FastAPI:
    app = FastAPI(title="QA Sentinel API", version="1.0.0", debug=False)
    app.state.application = application
    app.add_middleware(SourceBodyLimit)
    app.add_exception_handler(ApplicationError, application_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(Exception, internal_error_handler)
    app.include_router(projects.router, prefix="/api/v1")
    app.include_router(campaigns.router, prefix="/api/v1")
    app.include_router(campaign_content.router, prefix="/api/v1")
    app.include_router(test_specifications.router, prefix="/api/v1")
    app.include_router(tasks.router, prefix="/api/v1")
    app.include_router(executions.router, prefix="/api/v1")
    app.include_router(operations.router, prefix="/api/v1")

    @app.get("/health", response_model=HealthView, tags=["Health"])
    def health():
        return HealthView()

    return app
