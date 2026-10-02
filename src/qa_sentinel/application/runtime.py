"""Explicit trusted-host execution composition; never model-supplied configuration."""
from dataclasses import dataclass
from types import MappingProxyType
from collections.abc import Iterable
from uuid import UUID
from qa_sentinel.agents.base import AgentRuntime
from qa_sentinel.execution.base import TestResultProvider
from qa_sentinel.repository.service import RepositoryReadService
from qa_sentinel.mutation.service import MutationService
from qa_sentinel.projects import ProjectRuntimeRegistry, ProjectWorkspaceBinding, ProjectBindingError
from .errors import ApplicationError, ApplicationErrorCode as Code


@dataclass(frozen=True)
class ProjectExecutionBundle:
    binding: ProjectWorkspaceBinding
    runtime: AgentRuntime
    test_provider: TestResultProvider
    repository_service: RepositoryReadService | None = None
    mutation_service: MutationService | None = None


class ProjectExecutionResolver:
    def __init__(self, registry: ProjectRuntimeRegistry, bundles: Iterable[ProjectExecutionBundle]):
        self._registry = registry
        values = {}
        for bundle in bundles:
            if bundle.binding.project_id in values:
                raise ApplicationError(Code.PROJECT_RUNTIME_MISMATCH)
            values[bundle.binding.project_id] = bundle
        self._bundles = MappingProxyType(values)

    def resolve(self, project_id: UUID) -> ProjectExecutionBundle:
        try:
            binding = self._registry.resolve(project_id)
            bundle = self._bundles[project_id]
        except (KeyError, ProjectBindingError):
            raise ApplicationError(Code.PROJECT_RUNTIME_NOT_CONFIGURED) from None
        if bundle.binding != binding:
            raise ApplicationError(Code.PROJECT_RUNTIME_MISMATCH)
        return bundle
