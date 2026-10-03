"""Minimal host-only projection. Never expose runtime objects or configuration."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from qa_sentinel.application import ApplicationError, ApplicationErrorCode
from qa_sentinel.domain.project import ProjectKey
from .onboarding import model_key_present


class RuntimeStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["local", "demo", "preview-demo", "hosted-demo"]
    project_id: UUID
    project_key: ProjectKey
    runtime_configured: bool
    model_ready: bool | None
    test_targets_configured: bool


def add_runtime_status(app, composed, mode):
    @app.get("/host/runtime-status/{project_id}", response_model=RuntimeStatus)
    def runtime_status(project_id: UUID):
        project = composed.application.get_project(project_id)
        configured = True
        try:
            composed.resolver.resolve(project.id)
        except ApplicationError as exc:
            if exc.code != ApplicationErrorCode.PROJECT_RUNTIME_NOT_CONFIGURED:
                raise
            configured = False
        # Fake modes never inspect real key presence; resolution identifies the seeded UUID.
        return RuntimeStatus(mode=mode, project_id=project.id, project_key=project.key,
            runtime_configured=configured,
            model_ready=model_key_present() if mode == "local" and configured else None,
            test_targets_configured=mode == "local" and configured)
