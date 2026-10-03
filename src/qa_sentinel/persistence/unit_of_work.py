"""Explicit commit; otherwise all pending changes roll back on context exit."""
from sqlalchemy.orm import Session, sessionmaker
from .read_queries import ReadQueries
from .operations import OperationalQueries
from .execution_jobs import ExecutionJobRepository
from .repositories import (
    TaskRepository, ArtifactRepository, InvocationRepository, HistoryRepository,
    FailureFingerprintRepository, RequirementRepository, AcceptanceCriterionRepository,
    ProjectRepository,
)


class UnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory
        self.session: Session | None = None

    def __enter__(self):
        if self.session is not None:
            raise RuntimeError("UnitOfWork is already active")
        self.session = self.session_factory()
        self.tasks = TaskRepository(self.session)
        self.projects = ProjectRepository(self.session)
        self.execution_jobs = ExecutionJobRepository(self.session)
        self.reads = ReadQueries(self.session)
        self.operations = OperationalQueries(self.session)
        self.artifacts = ArtifactRepository(self.session)
        self.invocations = InvocationRepository(self.session)
        self.history = HistoryRepository(self.session)
        self.failure_fingerprints = FailureFingerprintRepository(self.session)
        self.requirements = RequirementRepository(self.session)
        self.acceptance_criteria = AcceptanceCriterionRepository(self.session)
        return self

    def commit(self) -> None:
        if self.session is None:
            raise RuntimeError("UnitOfWork is not active")
        self.session.commit()

    def rollback(self) -> None:
        if self.session is None:
            raise RuntimeError("UnitOfWork is not active")
        self.session.rollback()

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if self.session is not None:
                self.session.rollback()
        finally:
            if self.session is not None:
                self.session.close()
            self.session = None
