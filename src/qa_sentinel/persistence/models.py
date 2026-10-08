"""SQLAlchemy storage only; no domain or workflow behavior."""
from datetime import datetime
from typing import Any
from sqlalchemy import String, Text, Integer, Boolean, JSON, ForeignKey, CheckConstraint, UniqueConstraint, Index, ForeignKeyConstraint, text
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


class QACampaignRow(Base):
    __tablename__ = "qa_campaigns"
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT','READY_FOR_REVIEW','APPROVED')", name="ck_qa_campaigns_status"),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 200", name="ck_qa_campaigns_name"),
        CheckConstraint("objective IS NULL OR length(objective) <= 4000", name="ck_qa_campaigns_objective"),
        Index("ix_qa_campaigns_project_created", "project_id", "created_at", "id"),
        Index("uq_qa_campaigns_id_project", "id", "project_id", unique=True),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", name="fk_qa_campaigns_project_id", deferrable=True, initially="DEFERRED"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)


class CampaignSourceRow(Base):
    __tablename__ = "campaign_sources"
    __table_args__ = (
        ForeignKeyConstraint(["campaign_id", "project_id"], ["qa_campaigns.id", "qa_campaigns.project_id"], name="fk_campaign_sources_owner", deferrable=True, initially="DEFERRED"),
        UniqueConstraint("id", "campaign_id", "project_id", name="uq_campaign_sources_owner"),
        UniqueConstraint("campaign_id", "source_type", "content_hash", "normalization_version", name="uq_campaign_sources_content"),
        CheckConstraint("source_type IN ('TEXT','MARKDOWN','PDF')", name="ck_campaign_sources_type"),
        CheckConstraint("(status='INGESTED' AND normalized_text IS NOT NULL AND error_code IS NULL AND line_count>=1) OR (status='REJECTED' AND normalized_text IS NULL AND error_code IS NOT NULL AND line_count=0 AND normalized_chars=0)", name="ck_campaign_sources_ingestion"),
        CheckConstraint("original_bytes BETWEEN 0 AND 65536 AND normalized_chars BETWEEN 0 AND 65536 AND line_count BETWEEN 0 AND 4096", name="ck_campaign_sources_bounds"),
        Index("ix_campaign_sources_campaign", "campaign_id", "created_at", "id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", deferrable=True, initially="DEFERRED"), nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(32), nullable=False)
    original_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)


class RequirementExtractionRow(Base):
    __tablename__ = "campaign_requirement_extractions"
    __table_args__ = (
        ForeignKeyConstraint(["source_id", "campaign_id", "project_id"], ["campaign_sources.id", "campaign_sources.campaign_id", "campaign_sources.project_id"], name="fk_requirement_extractions_source_owner", deferrable=True, initially="DEFERRED"),
        UniqueConstraint("source_id", "attempt_number", name="uq_requirement_extractions_attempt"),
        UniqueConstraint("parent_attempt_id", name="uq_requirement_extractions_parent"),
        ForeignKeyConstraint(["parent_attempt_id", "campaign_id", "project_id"], ["campaign_requirement_extractions.id", "campaign_requirement_extractions.campaign_id", "campaign_requirement_extractions.project_id"], name="fk_extraction_parent", deferrable=True, initially="DEFERRED"),
        CheckConstraint("attempt_number BETWEEN 1 AND 3 AND ((attempt_number=1 AND parent_attempt_id IS NULL) OR (attempt_number>1 AND parent_attempt_id IS NOT NULL))", name="ck_extraction_attempt"),
        UniqueConstraint("id", "campaign_id", "project_id", name="uq_requirement_extractions_owner"),
        CheckConstraint("(status='STARTED' AND finished_at IS NULL AND error_code IS NULL AND metadata IS NULL) OR (status='SUCCEEDED' AND finished_at IS NOT NULL AND error_code IS NULL) OR (status='FAILED' AND finished_at IS NOT NULL AND error_code IS NOT NULL)", name="ck_requirement_extractions_lifecycle"),
        Index("ix_requirement_extractions_campaign", "campaign_id", "started_at", "id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", deferrable=True, initially="DEFERRED"), nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    agent: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(ISODateTime(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Any] = mapped_column("metadata", JSON(none_as_null=True), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    parent_attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class CampaignRequirementRow(Base):
    __tablename__ = "campaign_requirements"
    __table_args__ = (
        ForeignKeyConstraint(["extraction_id", "campaign_id", "project_id"], ["campaign_requirement_extractions.id", "campaign_requirement_extractions.campaign_id", "campaign_requirement_extractions.project_id"], name="fk_campaign_requirements_extraction_owner", deferrable=True, initially="DEFERRED"),
        UniqueConstraint("campaign_id", "logical_key", name="uq_campaign_requirements_key"),
        UniqueConstraint("extraction_id", "key", name="uq_campaign_requirements_local_key"),
        CheckConstraint("review_status IN ('DRAFT','NEEDS_CLARIFICATION','READY_FOR_REVIEW','APPROVED')", name="ck_campaign_requirements_review"),
        Index("ix_campaign_requirements_campaign", "campaign_id", "created_at", "id"),
        Index("uq_campaign_requirements_owner", "id", "campaign_id", "project_id", unique=True),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", deferrable=True, initially="DEFERRED"), nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    extraction_id: Mapped[str] = mapped_column(String(36), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    logical_key: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    acceptance_criteria: Mapped[Any] = mapped_column(JSON, nullable=False)
    source_references: Mapped[Any] = mapped_column(JSON, nullable=False)
    information_markers: Mapped[Any] = mapped_column(JSON, nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False)
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


class TestImportRow(Base):
    __tablename__='campaign_test_imports'
    __table_args__=(
        ForeignKeyConstraint(['campaign_id','project_id'],['qa_campaigns.id','qa_campaigns.project_id'],name='fk_test_imports_owner',deferrable=True,initially='DEFERRED'),
        UniqueConstraint('id','campaign_id','project_id',name='uq_test_imports_owner'),
        UniqueConstraint('campaign_id','format','content_hash','contract_version',name='uq_test_imports_identity'),
        CheckConstraint("format IN ('CSV','MARKDOWN','XLSX')",name='ck_test_imports_format'),
        CheckConstraint("(status='IMPORTED' AND normalized_text IS NOT NULL AND error_code IS NULL AND test_count BETWEEN 1 AND 100) OR (status='REJECTED' AND normalized_text IS NULL AND error_code IS NOT NULL AND test_count=0)",name='ck_test_imports_status'),
        CheckConstraint('original_bytes BETWEEN 0 AND 65536',name='ck_test_imports_bounds'),
        Index('ix_test_imports_campaign','campaign_id','created_at','id'),
    )
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    project_id:Mapped[str]=mapped_column(String(36),ForeignKey('projects.id',deferrable=True,initially='DEFERRED'),nullable=False)
    campaign_id:Mapped[str]=mapped_column(String(36),nullable=False)
    name:Mapped[str]=mapped_column(String(200),nullable=False)
    format:Mapped[str]=mapped_column(String(16),nullable=False)
    raw_hash:Mapped[str]=mapped_column(String(64),nullable=False)
    content_hash:Mapped[str]=mapped_column(String(64),nullable=False)
    contract_version:Mapped[str]=mapped_column(String(32),nullable=False)
    normalization_version:Mapped[str]=mapped_column(String(32),nullable=False)
    original_bytes:Mapped[int]=mapped_column(Integer,nullable=False)
    normalized_text:Mapped[str | None]=mapped_column(Text,nullable=True)
    status:Mapped[str]=mapped_column(String(16),nullable=False)
    error_code:Mapped[str | None]=mapped_column(String(32),nullable=True)
    test_count:Mapped[int]=mapped_column(Integer,nullable=False)
    created_at:Mapped[datetime]=mapped_column(ISODateTime(),nullable=False)

class TestGenerationRow(Base):
    __tablename__='campaign_test_generations'
    __table_args__=(
        ForeignKeyConstraint(['campaign_id','project_id'],['qa_campaigns.id','qa_campaigns.project_id'],name='fk_test_generations_owner',deferrable=True,initially='DEFERRED'),
        UniqueConstraint('id','campaign_id','project_id',name='uq_test_generations_owner'),
        UniqueConstraint('campaign_id','request_hash','contract_version',name='uq_test_generations_identity'),
        CheckConstraint("(status='STARTED' AND finished_at IS NULL AND error_code IS NULL AND metadata IS NULL) OR (status='SUCCEEDED' AND finished_at IS NOT NULL AND error_code IS NULL) OR (status='FAILED' AND finished_at IS NOT NULL AND error_code IS NOT NULL)",name='ck_test_generations_lifecycle'),
        Index('ix_test_generations_campaign','campaign_id','started_at','id'),
    )
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    project_id:Mapped[str]=mapped_column(String(36),ForeignKey('projects.id',deferrable=True,initially='DEFERRED'),nullable=False)
    campaign_id:Mapped[str]=mapped_column(String(36),nullable=False)
    request_hash:Mapped[str]=mapped_column(String(64),nullable=False)
    contract_version:Mapped[str]=mapped_column(String(32),nullable=False)
    requirement_versions:Mapped[Any]=mapped_column(JSON,nullable=False)
    agent:Mapped[str]=mapped_column(String(16),nullable=False)
    model:Mapped[str]=mapped_column(String(128),nullable=False)
    status:Mapped[str]=mapped_column(String(16),nullable=False)
    started_at:Mapped[datetime]=mapped_column(ISODateTime(),nullable=False)
    finished_at:Mapped[datetime | None]=mapped_column(ISODateTime(),nullable=True)
    error_code:Mapped[str | None]=mapped_column(String(64),nullable=True)
    metadata_json:Mapped[Any]=mapped_column('metadata',JSON(none_as_null=True),nullable=True)

class TestSpecificationRow(Base):
    __tablename__='campaign_test_specifications'
    __table_args__=(
        ForeignKeyConstraint(['campaign_id','project_id'],['qa_campaigns.id','qa_campaigns.project_id'],name='fk_test_specifications_owner',deferrable=True,initially='DEFERRED'),
        ForeignKeyConstraint(['import_id','campaign_id','project_id'],['campaign_test_imports.id','campaign_test_imports.campaign_id','campaign_test_imports.project_id'],name='fk_test_specifications_import',deferrable=True,initially='DEFERRED'),
        ForeignKeyConstraint(['generation_id','campaign_id','project_id'],['campaign_test_generations.id','campaign_test_generations.campaign_id','campaign_test_generations.project_id'],name='fk_test_specifications_generation',deferrable=True,initially='DEFERRED'),
        UniqueConstraint('id','campaign_id','project_id',name='uq_test_specifications_owner'),
        UniqueConstraint('campaign_id','logical_key',name='uq_test_specifications_key'),
        UniqueConstraint('import_id','key',name='uq_test_specifications_import_key'),
        UniqueConstraint('generation_id','key',name='uq_test_specifications_generation_key'),
        CheckConstraint('(import_id IS NOT NULL AND generation_id IS NULL) OR (generation_id IS NOT NULL AND import_id IS NULL)',name='ck_test_specifications_origin'),
        CheckConstraint("review_status IN ('DRAFT','NEEDS_CLARIFICATION','READY_FOR_REVIEW','APPROVED')",name='ck_test_specifications_review'),
        Index('ix_test_specifications_campaign','campaign_id','created_at','id'),
    )
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    project_id:Mapped[str]=mapped_column(String(36),ForeignKey('projects.id',deferrable=True,initially='DEFERRED'),nullable=False)
    campaign_id:Mapped[str]=mapped_column(String(36),nullable=False)
    import_id:Mapped[str | None]=mapped_column(String(36),nullable=True)
    generation_id:Mapped[str | None]=mapped_column(String(36),nullable=True)
    key:Mapped[str]=mapped_column(String(64),nullable=False)
    logical_key:Mapped[str]=mapped_column(String(128),nullable=False)
    title:Mapped[str]=mapped_column(String(200),nullable=False)
    test_type:Mapped[str]=mapped_column(String(16),nullable=False)
    priority:Mapped[str]=mapped_column(String(16),nullable=False)
    preconditions:Mapped[Any]=mapped_column(JSON,nullable=False)
    steps:Mapped[Any]=mapped_column(JSON,nullable=False)
    overall_expected_result:Mapped[str | None]=mapped_column(Text,nullable=True)
    required_evidence:Mapped[Any]=mapped_column(JSON,nullable=False)
    information_markers:Mapped[Any]=mapped_column(JSON,nullable=False)
    unresolved_requirement_refs:Mapped[Any]=mapped_column(JSON,nullable=False)
    provenance:Mapped[Any]=mapped_column(JSON,nullable=False)
    review_status:Mapped[str]=mapped_column(String(32),nullable=False)
    created_at:Mapped[datetime]=mapped_column(ISODateTime(),nullable=False)
    updated_at:Mapped[datetime]=mapped_column(ISODateTime(),nullable=False)

class TestRequirementLinkRow(Base):
    __tablename__='campaign_test_requirement_links'
    __table_args__=(
        Index('ix_test_links_campaign_requirement','campaign_id','requirement_id','test_spec_id'),
        ForeignKeyConstraint(['test_spec_id','campaign_id','project_id'],['campaign_test_specifications.id','campaign_test_specifications.campaign_id','campaign_test_specifications.project_id'],name='fk_test_links_spec_owner',deferrable=True,initially='DEFERRED'),
        ForeignKeyConstraint(['requirement_id','campaign_id','project_id'],['campaign_requirements.id','campaign_requirements.campaign_id','campaign_requirements.project_id'],name='fk_test_links_requirement_owner',deferrable=True,initially='DEFERRED'),
    )
    test_spec_id:Mapped[str]=mapped_column(String(36),primary_key=True)
    requirement_id:Mapped[str]=mapped_column(String(36),primary_key=True)
    project_id:Mapped[str]=mapped_column(String(36),nullable=False)
    campaign_id:Mapped[str]=mapped_column(String(36),nullable=False)


class RequirementReviewRow(Base):
    __tablename__ = "campaign_requirement_reviews"
    __table_args__ = (
        ForeignKeyConstraint(["object_id", "campaign_id", "project_id"], ["campaign_requirements.id", "campaign_requirements.campaign_id", "campaign_requirements.project_id"], name="fk_requirement_reviews_object_owner", deferrable=True, initially="DEFERRED"),
        CheckConstraint("status='APPROVED'", name="ck_requirement_reviews_status"),
        CheckConstraint("length(reviewer_label) BETWEEN 1 AND 64 AND (note IS NULL OR length(note) BETWEEN 1 AND 1000) AND length(content_hash)=64", name="ck_requirement_reviews_bounds"),
        Index("ix_requirement_reviews_campaign", "campaign_id", "object_id"),
    )
    object_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewer_label: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)


class TestSpecificationReviewRow(Base):
    __tablename__ = "campaign_test_reviews"
    __table_args__ = (
        ForeignKeyConstraint(["object_id", "campaign_id", "project_id"], ["campaign_test_specifications.id", "campaign_test_specifications.campaign_id", "campaign_test_specifications.project_id"], name="fk_test_reviews_object_owner", deferrable=True, initially="DEFERRED"),
        CheckConstraint("status='APPROVED'", name="ck_test_reviews_status"),
        CheckConstraint("length(reviewer_label) BETWEEN 1 AND 64 AND (note IS NULL OR length(note) BETWEEN 1 AND 1000) AND length(content_hash)=64", name="ck_test_reviews_bounds"),
        Index("ix_test_reviews_campaign", "campaign_id", "object_id"),
    )
    object_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewer_label: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)


class QARunRow(Base):
    __tablename__ = "qa_runs"
    __table_args__ = (
        ForeignKeyConstraint(["campaign_id", "project_id"], ["qa_campaigns.id", "qa_campaigns.project_id"], name="fk_qa_runs_owner", deferrable=True, initially="DEFERRED"),
        UniqueConstraint("id", "campaign_id", "project_id", name="uq_qa_runs_owner"),
        UniqueConstraint("campaign_id", "run_number", name="uq_qa_runs_number"),
        UniqueConstraint("campaign_id", "idempotency_key", name="uq_qa_runs_idempotency"),
        CheckConstraint("run_number >= 1 AND requirement_count BETWEEN 1 AND 1000 AND test_count BETWEEN 1 AND 1000", name="ck_qa_runs_counts"),
        CheckConstraint("length(idempotency_key) BETWEEN 1 AND 128 AND length(snapshot_hash)=64 AND (note IS NULL OR length(note) BETWEEN 1 AND 1000)", name="ck_qa_runs_bounds"),
        CheckConstraint("snapshot_version='qa-run-snapshot-v1'", name="ck_qa_runs_version"),
        CheckConstraint("execution_error_code IS NULL OR execution_error_code='RUN_EXECUTION_FAILED'", name="ck_qa_runs_error"),
        CheckConstraint("execution_status IN ('CREATED','QUEUED','RUNNING','COMPLETED','STOPPED','FAILED')", name="ck_qa_runs_execution"),
        CheckConstraint("qa_outcome IN ('NOT_EVALUATED','PASS','FAIL','PARTIAL')", name="ck_qa_runs_outcome"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    snapshot_version: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    campaign_snapshot: Mapped[Any] = mapped_column(JSON, nullable=False)
    readiness_at_creation: Mapped[Any] = mapped_column(JSON, nullable=False)
    requirement_count: Mapped[int] = mapped_column(Integer, nullable=False)
    test_count: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_status: Mapped[str] = mapped_column(String(16), nullable=False)
    qa_outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(ISODateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(ISODateTime(), nullable=True)
    execution_error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)


class QARunRequirementRow(Base):
    __tablename__ = "qa_run_requirements"
    __table_args__ = (
        ForeignKeyConstraint(["run_id", "campaign_id", "project_id"], ["qa_runs.id", "qa_runs.campaign_id", "qa_runs.project_id"], name="fk_qa_run_requirements_owner", deferrable=True, initially="DEFERRED"),
        UniqueConstraint("run_id", "original_requirement_id", name="uq_qa_run_requirements_original"),
        UniqueConstraint("run_id", "position", name="uq_qa_run_requirements_order"),
        CheckConstraint("position BETWEEN 1 AND 1000", name="ck_qa_run_requirements_position"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    original_requirement_id: Mapped[str] = mapped_column(String(36), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[Any] = mapped_column(JSON, nullable=False)
    approval: Mapped[Any] = mapped_column(JSON, nullable=False)


class QARunTestRow(Base):
    __tablename__ = "qa_run_tests"
    __table_args__ = (
        ForeignKeyConstraint(["run_id", "campaign_id", "project_id"], ["qa_runs.id", "qa_runs.campaign_id", "qa_runs.project_id"], name="fk_qa_run_tests_owner", deferrable=True, initially="DEFERRED"),
        UniqueConstraint("run_id", "original_test_specification_id", name="uq_qa_run_tests_original"),
        UniqueConstraint("run_id", "position", name="uq_qa_run_tests_order"),
        CheckConstraint("position BETWEEN 1 AND 1000", name="ck_qa_run_tests_position"),
        CheckConstraint("execution_status IN ('NOT_STARTED','RUNNING','COMPLETED','BLOCKED')", name="ck_qa_run_tests_execution"),
        CheckConstraint("qa_result IN ('NOT_EVALUATED','PASS','FAIL','SKIP')", name="ck_qa_run_tests_result"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    original_test_specification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[Any] = mapped_column(JSON, nullable=False)
    approval: Mapped[Any] = mapped_column(JSON, nullable=False)
    linked_requirement_snapshot_ids: Mapped[Any] = mapped_column(JSON, nullable=False)
    execution_status: Mapped[str] = mapped_column(String(16), nullable=False)
    qa_result: Mapped[str] = mapped_column(String(16), nullable=False)


class ClarificationRow(Base):
    __tablename__ = "campaign_clarifications"
    __table_args__ = (
        ForeignKeyConstraint(["requirement_id", "campaign_id", "project_id"], ["campaign_requirements.id", "campaign_requirements.campaign_id", "campaign_requirements.project_id"], name="fk_clarification_requirement", deferrable=True, initially="DEFERRED"),
        ForeignKeyConstraint(["source_id", "campaign_id", "project_id"], ["campaign_sources.id", "campaign_sources.campaign_id", "campaign_sources.project_id"], name="fk_clarification_source", deferrable=True, initially="DEFERRED"),
        UniqueConstraint("campaign_id", "request_key", name="uq_clarification_request"),
        UniqueConstraint("source_id", name="uq_clarification_source"),
        UniqueConstraint("id", "campaign_id", "project_id", name="uq_clarification_owner"),
        CheckConstraint("length(request_key) BETWEEN 1 AND 128 AND length(facts_hash)=64 AND first_fact_line BETWEEN 1 AND 4096", name="ck_clarification_bounds"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    requirement_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    facts_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    first_fact_line: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(ISODateTime(), nullable=False)


class RequirementRevisionRow(Base):
    __tablename__ = "campaign_requirement_revisions"
    __table_args__ = (
        ForeignKeyConstraint(["requirement_id", "campaign_id", "project_id"], ["campaign_requirements.id", "campaign_requirements.campaign_id", "campaign_requirements.project_id"], name="fk_revision_current", deferrable=True, initially="DEFERRED"),
        ForeignKeyConstraint(["supersedes_id", "campaign_id", "project_id"], ["campaign_requirements.id", "campaign_requirements.campaign_id", "campaign_requirements.project_id"], name="fk_revision_previous", deferrable=True, initially="DEFERRED"),
        ForeignKeyConstraint(["clarification_id", "campaign_id", "project_id"], ["campaign_clarifications.id", "campaign_clarifications.campaign_id", "campaign_clarifications.project_id"], name="fk_revision_clarification", deferrable=True, initially="DEFERRED"),
        UniqueConstraint("supersedes_id", name="uq_revision_previous"),
        UniqueConstraint("clarification_id", name="uq_revision_clarification"),
        CheckConstraint("version BETWEEN 2 AND 10 AND requirement_id != supersedes_id", name="ck_revision_version"),
    )
    requirement_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    supersedes_id: Mapped[str] = mapped_column(String(36), nullable=False)
    clarification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
