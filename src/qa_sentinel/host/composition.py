"""Trusted host composition above API/application/core. No global instances."""
import os
from dataclasses import dataclass
from sqlalchemy import Engine
from qa_sentinel.application import QASentinelApplication, ProjectExecutionResolver, ProjectExecutionBundle
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.projects import ProjectRuntimeRegistry, ProjectWorkspaceBinding
from qa_sentinel.agents.real import RealAgentRuntime
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from qa_sentinel.models.config import RoleModelConfig
from qa_sentinel.execution.command_runner import CommandRunner
from qa_sentinel.execution.pytest_runner import PytestRunner
from qa_sentinel.execution.service import TestExecutionService, PytestTestResultProvider
from .config import HostConfig, HostError
from .database import bootstrap_database
from .demo import demo_bundle
from .preview import preview_credentials
from .preflight import real_components


@dataclass(frozen=True)
class HostComposition:
    application: QASentinelApplication
    engine: Engine
    resolver: ProjectExecutionResolver

    def close(self):
        self.engine.dispose()


def compose(config: HostConfig) -> HostComposition:
    engine = None
    try:
        if config.mode == "preview-demo":
            preview_credentials()  # Direct composition fails closed too, before DB IO.
        prepared = []
        if config.mode == "local":
            if not os.environ.get("OPENAI_API_KEY", "").strip():
                raise HostError("HOST_MODEL_KEY_REQUIRED")
            prepared = [(project, real_components(project)) for project in config.projects]
        engine, factory = bootstrap_database(config.database)
        if config.mode in {"demo", "preview-demo"}:
            bundles = [demo_bundle(factory, config.database)]
        else:
            bundles = []
            for project, (reader, mutation, execution, request) in prepared:
                with UnitOfWork(factory) as uow:
                    persisted = uow.projects.get_by_key(project.key)
                    if persisted is None:
                        raise HostError("HOST_PROJECT_NOT_FOUND")
                binding = ProjectWorkspaceBinding(project_id=persisted.id, workspace_root=project.workspace_root)
                service = TestExecutionService(factory, PytestRunner(CommandRunner(execution)), workspace_binding=binding)
                bundles.append(ProjectExecutionBundle(binding,
                    RealAgentRuntime(OpenAIModelAdapter(), RoleModelConfig(), repository_tools=True),
                    PytestTestResultProvider(service, request), reader, mutation))
        resolver = ProjectExecutionResolver(ProjectRuntimeRegistry([b.binding for b in bundles]), bundles)
        return HostComposition(QASentinelApplication(factory, resolver), engine, resolver)
    except Exception as exc:
        if engine is not None:
            engine.dispose()
        if isinstance(exc, HostError):
            raise
        raise HostError("HOST_COMPOSITION_FAILED") from None
