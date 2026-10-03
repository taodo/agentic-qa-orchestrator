"""Local read-only assessment composition, without SDK, test runner or worker creation."""
import sqlite3
from types import SimpleNamespace
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker
from qa_sentinel.application import QASentinelApplication, ProjectExecutionBundle, ProjectExecutionResolver
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.projects import ProjectWorkspaceBinding, ProjectRuntimeRegistry
from qa_sentinel.repository.config import RepositoryReadConfig
from qa_sentinel.repository.service import RepositoryReadService
from qa_sentinel.mutation.contracts import MutationConfig
from qa_sentinel.mutation.service import MutationService
from .config import HostError, canonical_path
from .database import CURRENT_REVISION


def assess_local(config, task_id):
    if config.mode != "local":
        raise HostError("HOST_CONFIG_INVALID")
    engine = None
    try:
        path = canonical_path(config.database, exists=True)
        if not path.is_file():
            raise HostError("HOST_LOCAL_DATABASE_NOT_READY")
        engine = create_engine("sqlite+pysqlite://", creator=lambda: sqlite3.connect(
            path.as_uri() + "?mode=ro", uri=True))
        @event.listens_for(engine, "connect")
        def configure(connection, record):
            connection.isolation_level = None
        @event.listens_for(engine, "begin")
        def begin(connection):
            connection.exec_driver_sql("BEGIN")  # Consistent read snapshot, still mode=ro.
        with engine.connect() as connection:
            if connection.execute(text("select version_num from alembic_version")).scalars().all() != [CURRENT_REVISION]:
                raise HostError("HOST_LOCAL_DATABASE_NOT_READY")
        factory = sessionmaker(engine)
        bundles = []
        for project in config.projects:
            with UnitOfWork(factory) as uow:
                persisted = uow.projects.get_by_key(project.key)
                if persisted is None:
                    raise HostError("HOST_PROJECT_NOT_FOUND")
            binding = ProjectWorkspaceBinding(project_id=persisted.id, workspace_root=project.workspace_root)
            # Inert trusted root descriptor. No runtime, SDK, pytest runner or target scans.
            probe = SimpleNamespace(workspace_root=binding.workspace_root, workspace_binding=binding)
            bundles.append(ProjectExecutionBundle(binding, None, probe,
                RepositoryReadService(RepositoryReadConfig(binding.workspace_root)),
                MutationService(MutationConfig(binding.workspace_root))))
        resolver = ProjectExecutionResolver(ProjectRuntimeRegistry([b.binding for b in bundles]), bundles)
        return QASentinelApplication(factory, resolver).assess_task_reconciliation(task_id)
    finally:
        if engine is not None:
            engine.dispose()


def reconcile_command(args):
    import sys
    from qa_sentinel.application import ApplicationError
    from .config import load_local_config
    try:
        assessment = assess_local(load_local_config(args.config), args.task)
        print(f"Reconciliation: {assessment.status.value}")
        print(f"Safe to Run: {'YES' if assessment.safe_to_run else 'NO'}")
        print(f"Safe to Resume: {'YES' if assessment.safe_to_resume else 'NO'}")
        print("Derived safety guidance; Task state remains authoritative. No effects are resolved.")
        for issue in assessment.issues:
            print(f"{issue.kind.value} ({issue.severity.value}): {issue.summary}")
            print(issue.operator_action)
            if issue.evidence_refs:
                print("Evidence IDs: " + ", ".join(issue.evidence_refs))
        return 0 if assessment.status.value in {"CLEAR", "RECOVERABLE"} and (assessment.safe_to_run or assessment.safe_to_resume) else 1
    except Exception as exc:
        code = str(exc) if isinstance(exc, HostError) else exc.code.value if isinstance(exc, ApplicationError) else "HOST_RECONCILIATION_FAILED"
        print(f"Reconciliation unavailable ({code}). No action taken.", file=sys.stderr)
        return 1
