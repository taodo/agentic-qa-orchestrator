"""SQLAlchemy storage only; no domain or workflow behavior."""
from datetime import datetime
from typing import Any
from sqlalchemy import String, Text, Integer, Boolean, JSON, ForeignKey, CheckConstraint, UniqueConstraint, Index, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from .types import ISODateTime


class Base(DeclarativeBase):
    pass


class ExecutionJobRow(Base):
    __tablename__ = "execution_jobs"
    __table_args__ = (
        UniqueConstraint("id", name="uq_execution_jobs_id"),
        CheckConstraint("status IN ('QUEUED','RUNNING','SUCCEEDED','STOPPED','FAILED')", name="ck_execution_jobs_status"),
        CheckConstraint("(status = 'QUEUED' AND started_at IS NULL AND finished_at IS NULL AND safe_error_code IS NULL) OR "
            "(status = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL AND safe_error_code IS NULL) OR "
            "(status = 'SUCCEEDED' AND started_at IS NOT NULL AND finished_at IS NOT NULL AND safe_error_code IS NULL) OR "
            "(status = 'STOPPED' AND started_at IS NOT NULL AND finished_at IS NOT NULL AND safe_error_code IS NOT NULL AND safe_error_code IN ('RUNTIME_STOPPED','EXECUTION_INTERRUPTED')) OR "
            "(status = 'FAILED' AND started_at IS NOT NULL AND finished_at IS NOT NULL AND safe_error_code IS NOT NULL AND safe_error_code = 'EXECUTION_FAILED')",
            name="ck_execution_jobs_lifecycle"),
        Index("ix_execution_jobs_queue", "status", "sequence"),
        Index("ix_execution_jobs_task", "task_id", "sequence"),
        Index("uq_execution_jobs_active_task", "task_id", unique=True, sqlite_where=text("status IN ('QUEUED','RUNNING')")),
        Index("uq_execution_jobs_running", "status", unique=True, sqlite_where=text("status = 'RUNNING'")),
        {"sqlite_autoincrement": True},
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", deferrable=True, initially="DEFERRED"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(ISODateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(ISODateTime(), nullable=True)
    safe_error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)


class ProjectRow(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("key", name="uq_projects_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)


class TaskRow(Base):
    __tablename__ = "tasks"
    __table_args__ = (CheckConstraint("implementation_attempt >= 0", name="ck_tasks_implementation_attempt"), CheckConstraint("defect_cycle >= 0", name="ck_tasks_defect_cycle"), CheckConstraint("review_cycle >= 0", name="ck_tasks_review_cycle"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", name="fk_tasks_project_id", deferrable=True, initially="DEFERRED"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    requirement: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    resume_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(ISODateTime(), nullable=True)
    current_invocation_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("invocations.id", deferrable=True, initially="DEFERRED"), nullable=True)
    implementation_attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    defect_cycle: Mapped[int] = mapped_column(Integer, nullable=False)
    review_cycle: Mapped[int] = mapped_column(Integer, nullable=False)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class InvocationRow(Base):
    __tablename__ = "invocations"
    __table_args__ = (CheckConstraint("attempt >= 1", name="ck_invocations_attempt"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False)
    agent: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning_effort: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(ISODateTime(), nullable=True)
    input_context_refs: Mapped[Any] = mapped_column(JSON(none_as_null=False), nullable=False)
    error_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("errors.id", deferrable=True, initially="DEFERRED"), nullable=True)


class ArtifactRow(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False)
    invocation_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("invocations.id", deferrable=True, initially="DEFERRED"), nullable=True)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    producer_agent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    producer_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[Any] = mapped_column(JSON(none_as_null=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)
    supersedes_artifact_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("artifacts.id", deferrable=True, initially="DEFERRED"), nullable=True)


class TransitionRow(Base):
    __tablename__ = "transitions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False)
    from_state: Mapped[str] = mapped_column(String(64), nullable=False)
    to_state: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    gate_evaluation_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("gate_evaluations.id", deferrable=True, initially="DEFERRED"), nullable=True)
    decision_id: Mapped[str] = mapped_column(String(36), ForeignKey("decisions.id", deferrable=True, initially="DEFERRED"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)


class GateEvaluationRow(Base):
    __tablename__ = "gate_evaluations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False)
    gate_name: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str] = mapped_column(String(64), nullable=False)
    checks: Mapped[Any] = mapped_column(JSON(none_as_null=False), nullable=False)
    blocking_reasons: Mapped[Any] = mapped_column(JSON(none_as_null=False), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)


class DecisionRow(Base):
    __tablename__ = "decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_source: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    reason_details: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[Any] = mapped_column(JSON(none_as_null=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)


class ErrorRow(Base):
    __tablename__ = "errors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False)
    error_type: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(64), nullable=False)
    owner: Mapped[str] = mapped_column(String(64), nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[Any] = mapped_column(JSON(none_as_null=False), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[Any] = mapped_column(JSON(none_as_null=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)


class EventRow(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)
    actor: Mapped[Any] = mapped_column(JSON(none_as_null=False), nullable=False)
    correlation: Mapped[Any] = mapped_column(JSON(none_as_null=False), nullable=False)
    payload: Mapped[Any] = mapped_column(JSON(none_as_null=False), nullable=False)


class AuditRow(Base):
    __tablename__ = "audit_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False)
    actor: Mapped[Any] = mapped_column(JSON(none_as_null=False), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    policy: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Any] = mapped_column('metadata', JSON(none_as_null=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)


class TestRunRow(Base):
    __tablename__ = "test_runs"
    __table_args__ = (CheckConstraint("passed_count >= 0", name="ck_test_runs_passed_count"), CheckConstraint("failed_count >= 0", name="ck_test_runs_failed_count"), CheckConstraint("skipped_count >= 0", name="ck_test_runs_skipped_count"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False)
    implementation_artifact_id: Mapped[str] = mapped_column(String(36), ForeignKey("artifacts.id", deferrable=True, initially="DEFERRED"), nullable=False)
    execution_status: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False)
    report_artifact_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("artifacts.id", deferrable=True, initially="DEFERRED"), nullable=True)


class FailureFingerprintRow(Base):
    __tablename__ = "failure_fingerprints"
    __table_args__ = (CheckConstraint("occurrence_count >= 0", name="ck_failure_fingerprints_occurrence_count"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False)
    test_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("test_runs.id", deferrable=True, initially="DEFERRED"), nullable=False)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    test_name: Mapped[str] = mapped_column(Text, nullable=False)
    error_class: Mapped[str] = mapped_column(Text, nullable=False)
    component: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_signature: Mapped[str] = mapped_column(Text, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)


class RequirementRow(Base):
    __tablename__ = "requirements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class AcceptanceCriterionRow(Base):
    __tablename__ = "acceptance_criteria"
    __table_args__ = (UniqueConstraint("requirement_id", "id", name="uq_acceptance_requirement_id"),)
    persistence_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    id: Mapped[str] = mapped_column(Text, nullable=False)
    requirement_id: Mapped[str] = mapped_column(String(36), ForeignKey("requirements.id", deferrable=True, initially="DEFERRED"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    verification_method: Mapped[str] = mapped_column(Text, nullable=False)
