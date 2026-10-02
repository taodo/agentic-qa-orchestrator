"""Trusted host workspace composition. No model access, IO execution or global registry."""
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from uuid import UUID
from pydantic import BaseModel, ConfigDict, field_validator
from qa_sentinel.domain.event import Event
from qa_sentinel.persistence.unit_of_work import UnitOfWork


class ProjectBindingError(RuntimeError):
    """Fixed safe code; runtime stops without changing workflow state."""


class ProjectWorkspaceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: UUID
    workspace_root: Path

    @field_validator("workspace_root")
    @classmethod
    def canonical_root(cls, value):
        root = value.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Workspace root must be an existing directory")
        return root

    @property
    def workspace_identity(self):
        return sha256((str(self.project_id) + "\0" + str(self.workspace_root)).encode("utf-8")).hexdigest()


class ProjectRuntimeRegistry:
    def __init__(self, bindings):
        values = {}
        for binding in bindings:
            binding = ProjectWorkspaceBinding.model_validate(binding.model_dump())
            if binding.project_id in values:
                raise ProjectBindingError("DUPLICATE_PROJECT_BINDING")
            if any(binding.workspace_root == other.workspace_root or
                   binding.workspace_root.is_relative_to(other.workspace_root) or
                   other.workspace_root.is_relative_to(binding.workspace_root) for other in values.values()):
                raise ProjectBindingError("OVERLAPPING_PROJECT_WORKSPACES")
            values[binding.project_id] = binding
        self._bindings = MappingProxyType(values)

    def resolve(self, project_id):
        try:
            return self._bindings[project_id]
        except KeyError:
            raise ProjectBindingError("PROJECT_BINDING_MISSING") from None


class ProjectWorkspaceGuard:
    def __init__(self, factory, binding, *, reader=None, mutation=None, test_provider=None, execution=None):
        self.factory, self.binding = factory, binding
        self.reader, self.mutation = reader, mutation
        self.test_provider, self.execution = test_provider, execution

    def _identity(self, task):
        physical = self.reader is not None or self.mutation is not None or self.execution is not None
        test_root = getattr(self.test_provider, "workspace_root", None)
        physical = physical or test_root is not None
        if self.binding is None:
            if physical:
                raise ProjectBindingError("PROJECT_BINDING_MISSING")
            return None  # Pure supplied-context/fake workflows have no workspace access.
        try:
            binding = ProjectWorkspaceBinding.model_validate(self.binding.model_dump())
        except (OSError, ValueError):
            raise ProjectBindingError("PROJECT_WORKSPACE_UNAVAILABLE") from None
        if task.project_id != binding.project_id:
            raise ProjectBindingError("PROJECT_BINDING_MISMATCH")
        expected = binding.workspace_root
        for root, code in (
            (None if self.reader is None else self.reader.config.repository_root, "REPOSITORY_WORKSPACE_MISMATCH"),
            (None if self.mutation is None else self.mutation.config.workspace_root, "MUTATION_WORKSPACE_MISMATCH"),
            (test_root, "TEST_WORKSPACE_MISMATCH"),
            (None if self.execution is None else self.execution.workspace_root, "TEST_WORKSPACE_MISMATCH")):
            if root is not None and root != expected:
                raise ProjectBindingError(code)
        provider_binding = getattr(self.test_provider, "workspace_binding", None)
        if test_root is not None and (provider_binding is None or provider_binding != binding):
            raise ProjectBindingError("TEST_PROJECT_BINDING_MISMATCH")
        # The durable anchor binds logical ownership to the physical root without paths.
        # Service-specific configuration drift remains enforced by Tasks 9/10.
        return binding.workspace_identity

    def check(self, task):
        identity = self._identity(task)
        with UnitOfWork(self.factory) as uow:
            durable = uow.tasks.get(task.id)
            if durable is None or durable.project_id != task.project_id or uow.projects.get(task.project_id) is None:
                raise ProjectBindingError("PROJECT_OWNERSHIP_UNAVAILABLE")
            active = None if durable.current_invocation_id is None else uow.invocations.get(durable.current_invocation_id)
            if active is not None and active.task_id != task.id:
                raise ProjectBindingError("CROSS_TASK_INVOCATION")
            anchors = [e for e in uow.history.list_events(task.id) if e.event_type == "PROJECT_WORKSPACE_BOUND"]
            if anchors:
                if len(anchors) != 1 or anchors[0].payload != {"workspace_identity": identity}:
                    raise ProjectBindingError("PROJECT_WORKSPACE_REQUIRES_RECONCILIATION")
            elif identity is not None:
                # Adopt legacy Task 9/10 evidence only after validating its existing root identity.
                for event in uow.history.list_events(task.id):
                    if event.event_type == "TEST_EXECUTION_STARTED":
                        raise ProjectBindingError("LEGACY_TEST_WORKSPACE_REQUIRES_RECONCILIATION")
                    if event.event_type == "REPOSITORY_SESSION_STARTED" and (
                        self.reader is None or event.payload.get("repository_config_identity") != self.reader.config.identity):
                        raise ProjectBindingError("REPOSITORY_WORKSPACE_REQUIRES_RECONCILIATION")
                    if event.event_type in {"MUTATION_APPLIED", "MUTATION_RESERVED", "IMPLEMENTATION_SOURCE_CAPTURED"} and (
                        self.mutation is None or event.payload.get("workspace_identity") != self.mutation.workspace_identity):
                        raise ProjectBindingError("MUTATION_WORKSPACE_REQUIRES_RECONCILIATION")
                uow.history.append_event(Event(task_id=task.id, event_type="PROJECT_WORKSPACE_BOUND",
                    actor=dict(type="ORCHESTRATOR", id="qa-sentinel"), correlation={},
                    payload=dict(workspace_identity=identity)))
                uow.commit()
