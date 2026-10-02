from datetime import timedelta
from uuid import uuid4
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from qa_sentinel.domain.project import Project
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.event import Event
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.projects import ProjectWorkspaceBinding, ProjectRuntimeRegistry, ProjectWorkspaceGuard, ProjectBindingError
from qa_sentinel.repository.config import RepositoryReadConfig
from qa_sentinel.repository.service import RepositoryReadService
from qa_sentinel.mutation.contracts import MutationConfig
from qa_sentinel.mutation.service import MutationService


@pytest.mark.parametrize("key", ["", " ", "UPPER", " leading", "trailing ", "a_b", "-a", "a-", "a--b", "a/b", "x"*65, "a\n", "café"])
def test_project_keys_reject_without_normalization(key):
    with pytest.raises(ValidationError):
        Project(key=key, name="Project")


def test_project_requires_explicit_task_owner_and_frozen_identity():
    p = Project(key="payment-api", name="Payment API")
    assert p.key == "payment-api"
    for field, value in (("id", uuid4()), ("key", "different"), ("created_at", p.created_at+timedelta(seconds=1))):
        with pytest.raises(ValidationError):
            setattr(p, field, value)
    with pytest.raises(ValidationError):
        Task(title="No owner", requirement="Rejected")
    task = Task(project_id=p.id, title="Owned", requirement="Explicit")
    with pytest.raises(ValidationError):
        task.project_id = uuid4()
    with pytest.raises(ValidationError):
        Project(key="valid", name=" ")
    with pytest.raises(ValidationError):
        Project(key="valid", name="Valid", workspace_root="/machine/path")


def test_project_repository_updates_uniqueness_and_transaction_owner(factory):
    a, b = Project(key="a", name="A"), Project(key="b", name="B")
    with UnitOfWork(factory) as uow:
        uow.projects.add(b); uow.projects.add(a); uow.commit()
    with UnitOfWork(factory) as uow:
        assert uow.projects.list() == [a, b]
        assert uow.projects.get_by_key("a") == a
        assert uow.projects.get_by_key(" A ") is None
        assert uow.projects.get(uuid4()) is None
        a.name, a.description = "Updated", "Description"
        a.updated_at += timedelta(seconds=1)
        uow.projects.save(a); uow.commit()
    with UnitOfWork(factory) as uow:
        assert uow.projects.get(a.id) == a
        with pytest.raises(ValueError):
            uow.projects.save(a.model_copy(update={"key":"changed"}))
        with pytest.raises(ValueError):
            uow.projects.save(a.model_copy(update={"created_at":a.created_at+timedelta(seconds=1)}))
    with pytest.raises(IntegrityError):
        with UnitOfWork(factory) as uow:
            uow.projects.add(Project(key="a", name="Duplicate")); uow.commit()
    rolled_back = Project(key="rollback", name="Rollback")
    with UnitOfWork(factory) as uow:
        uow.projects.add(rolled_back)
    with UnitOfWork(factory) as uow:
        assert uow.projects.get(rolled_back.id) is None


def test_task_repository_rejects_ownership_reassignment(factory):
    a, b = Project(key="a", name="A"), Project(key="b", name="B")
    t = Task(project_id=a.id, title="Task", requirement="Ownership")
    with UnitOfWork(factory) as uow:
        uow.projects.add(a);uow.projects.add(b);uow.tasks.add(t);uow.commit()
    with UnitOfWork(factory) as uow:
        with pytest.raises(ValueError, match="ownership"):
            uow.tasks.save(t.model_copy(update={"project_id":b.id}))
        assert uow.tasks.get(t.id).project_id == a.id


def test_binding_canonical_registry_duplicate_missing_and_overlap(tmp_path):
    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; b.mkdir()
    owner = uuid4()
    binding = ProjectWorkspaceBinding(project_id=owner, workspace_root=a / ".." / "a")
    assert binding.workspace_root == a.resolve()
    assert binding.workspace_identity == ProjectWorkspaceBinding(project_id=owner, workspace_root=a).workspace_identity
    assert binding.workspace_identity != ProjectWorkspaceBinding(project_id=uuid4(), workspace_root=a).workspace_identity
    with pytest.raises(ValidationError):
        binding.project_id = uuid4()
    registry = ProjectRuntimeRegistry([binding, ProjectWorkspaceBinding(project_id=uuid4(), workspace_root=b)])
    assert registry.resolve(owner) == binding
    with pytest.raises(ProjectBindingError, match="MISSING"):
        registry.resolve(uuid4())
    with pytest.raises(ProjectBindingError, match="DUPLICATE"):
        ProjectRuntimeRegistry([binding, binding])
    with pytest.raises(ProjectBindingError, match="OVERLAPPING"):
        ProjectRuntimeRegistry([binding, ProjectWorkspaceBinding(project_id=uuid4(), workspace_root=tmp_path)])


@pytest.mark.parametrize("resource,code", [("reader","REPOSITORY"),("mutation","MUTATION"),("test_provider","TEST"),("execution","TEST")])
def test_service_consistency_rejects_wrong_root_before_progress(factory, tmp_path, resource, code):
    a = tmp_path / "a";a.mkdir()
    b = tmp_path / "b";b.mkdir()
    project = Project(key="a", name="A")
    task = Task(project_id=project.id, title="Task", requirement="Isolate")
    with UnitOfWork(factory) as uow:
        uow.projects.add(project);uow.tasks.add(task);uow.commit()
    binding = ProjectWorkspaceBinding(project_id=project.id,workspace_root=a)
    values = dict(reader=RepositoryReadService(RepositoryReadConfig(b)),
        mutation=MutationService(MutationConfig(b)), test_provider=SimpleNamespace(workspace_root=b), execution=SimpleNamespace(workspace_root=b))
    guard = ProjectWorkspaceGuard(factory, binding, **{resource:values[resource]})
    with pytest.raises(ProjectBindingError,match=code+"_WORKSPACE_MISMATCH"):
        guard.check(task)
    with UnitOfWork(factory) as uow:
        assert not uow.history.list_events(task.id)
    with pytest.raises(ProjectBindingError,match="MISSING"):
        ProjectWorkspaceGuard(factory,None,**{resource:values[resource]}).check(task)


def test_fake_no_workspace_compatibility_and_wrong_project(factory,tmp_path):
    p=Project(key="a",name="A");t=Task(project_id=p.id,title="T",requirement="R")
    with UnitOfWork(factory) as uow:
        uow.projects.add(p);uow.tasks.add(t);uow.commit()
    ProjectWorkspaceGuard(factory,None,test_provider=SimpleNamespace(workspace_root=None)).check(t)
    binding=ProjectWorkspaceBinding(project_id=uuid4(),workspace_root=tmp_path)
    with pytest.raises(ProjectBindingError,match="PROJECT_BINDING_MISMATCH"):
        ProjectWorkspaceGuard(factory,binding).check(t)


@pytest.mark.parametrize("event_type", ["REPOSITORY_SESSION_STARTED", "IMPLEMENTATION_SOURCE_CAPTURED", "MUTATION_RESERVED", "MUTATION_APPLIED", "TEST_EXECUTION_STARTED"])
def test_legacy_workspace_evidence_cannot_be_rebound_without_validation(factory,tmp_path,event_type):
    a=tmp_path/"a";a.mkdir()
    b=tmp_path/"b";b.mkdir()
    p=Project(key="legacy-test",name="Legacy")
    t=Task(project_id=p.id,title="T",requirement="R")
    original_reader=RepositoryReadService(RepositoryReadConfig(a))
    original_mutation=MutationService(MutationConfig(a))
    payload=({"repository_config_identity":original_reader.config.identity} if event_type=="REPOSITORY_SESSION_STARTED" else
        {"workspace_identity":original_mutation.workspace_identity} if event_type!="TEST_EXECUTION_STARTED" else {})
    with UnitOfWork(factory) as uow:
        uow.projects.add(p);uow.tasks.add(t)
        uow.history.append_event(Event(task_id=t.id,event_type=event_type,
            actor=dict(type="ORCHESTRATOR",id="qa-sentinel"),correlation={},payload=payload))
        uow.commit()
    wrong=ProjectWorkspaceGuard(factory,ProjectWorkspaceBinding(project_id=p.id,workspace_root=b),
        reader=RepositoryReadService(RepositoryReadConfig(b)),mutation=MutationService(MutationConfig(b)))
    with pytest.raises(ProjectBindingError,match="REQUIRES_RECONCILIATION"):
        wrong.check(t)
    with UnitOfWork(factory) as uow:
        assert len(uow.history.list_events(t.id))==1
    correct=ProjectWorkspaceGuard(factory,ProjectWorkspaceBinding(project_id=p.id,workspace_root=a),
        reader=original_reader,mutation=original_mutation)
    if event_type=="TEST_EXECUTION_STARTED":
        with pytest.raises(ProjectBindingError,match="LEGACY_TEST_WORKSPACE"):
            correct.check(t)
    else:
        correct.check(t)
        correct.check(t)
        with UnitOfWork(factory) as uow:
            anchor,=[e for e in uow.history.list_events(t.id) if e.event_type=="PROJECT_WORKSPACE_BOUND"]
            assert anchor.payload=={"workspace_identity":correct.binding.workspace_identity}
            assert str(a) not in str(anchor.payload)
