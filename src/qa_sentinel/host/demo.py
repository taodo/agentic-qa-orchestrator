"""Offline synthetic calculator evidence through accepted fake runtime paths."""
from qa_sentinel.agents.fake import FakeAgentRuntime
from qa_sentinel.agents.scenarios import division_scenario
from qa_sentinel.application import ProjectExecutionBundle
from qa_sentinel.domain.project import Project
from qa_sentinel.execution.fake import FakeTestResultProvider
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.projects import ProjectWorkspaceBinding
from .config import canonical_path, overlaps, HostError


def demo_bundle(factory, database):
    root = canonical_path(database.parent / "demo-workspace")
    # Even the identity-only workspace must not overlap platform source or assets/state.
    from pathlib import Path
    if overlaps(root, Path(__file__).resolve().parents[3]) or database.is_relative_to(root):
        raise HostError("HOST_DEMO_WORKSPACE_INVALID")
    root.mkdir(parents=True, exist_ok=True)
    root = canonical_path(root, exists=True)
    with UnitOfWork(factory) as uow:
        project = uow.projects.get_by_key("demo-calculator")
        if project is None:
            project = Project(key="demo-calculator", name="Demo Calculator",
                description="Offline demo: synthetic division evidence; no live AI, source writes or real tests.")
            uow.projects.add(project)
            uow.commit()
    binding = ProjectWorkspaceBinding(project_id=project.id, workspace_root=root)
    scenario, results = division_scenario()
    return ProjectExecutionBundle(binding, FakeAgentRuntime(scenario), FakeTestResultProvider(results))
