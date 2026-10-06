"""Initial persistence foundation.

Revision ID: 0001
Revises: None
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("tasks",
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('requirement', sa.Text(), nullable=False),
        sa.Column('state', sa.String(64), nullable=False),
        sa.Column('resume_state', sa.String(64), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.Text(), nullable=False),
        sa.Column('completed_at', sa.Text(), nullable=True),
        sa.Column('current_invocation_id', sa.String(36), sa.ForeignKey("invocations.id", deferrable=True, initially="DEFERRED"), nullable=True),
        sa.Column('implementation_attempt', sa.Integer(), nullable=False),
        sa.Column('defect_cycle', sa.Integer(), nullable=False),
        sa.Column('review_cycle', sa.Integer(), nullable=False),
        sa.Column('terminal_reason', sa.Text(), nullable=True),
        sa.CheckConstraint("implementation_attempt >= 0", name="ck_tasks_implementation_attempt"),
        sa.CheckConstraint("defect_cycle >= 0", name="ck_tasks_defect_cycle"),
        sa.CheckConstraint("review_cycle >= 0", name="ck_tasks_review_cycle"),
    )
    op.create_table("requirements",
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_id', sa.String(36), sa.ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
    )
    op.create_table("acceptance_criteria",
        sa.Column('persistence_id', sa.String(36), primary_key=True),
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('requirement_id', sa.String(36), sa.ForeignKey("requirements.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('verification_method', sa.Text(), nullable=False),
        sa.UniqueConstraint('requirement_id', 'id', name='uq_acceptance_requirement_id'),
    )
    op.create_table("invocations",
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_id', sa.String(36), sa.ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('agent', sa.String(64), nullable=False),
        sa.Column('model', sa.Text(), nullable=False),
        sa.Column('reasoning_effort', sa.Text(), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(64), nullable=False),
        sa.Column('started_at', sa.Text(), nullable=False),
        sa.Column('finished_at', sa.Text(), nullable=True),
        sa.Column('input_context_refs', sa.JSON(none_as_null=False), nullable=False),
        sa.Column('error_id', sa.String(36), sa.ForeignKey("errors.id", deferrable=True, initially="DEFERRED"), nullable=True),
        sa.CheckConstraint("attempt >= 1", name="ck_invocations_attempt"),
    )
    op.create_table("artifacts",
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_id', sa.String(36), sa.ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('invocation_id', sa.String(36), sa.ForeignKey("invocations.id", deferrable=True, initially="DEFERRED"), nullable=True),
        sa.Column('artifact_type', sa.String(64), nullable=False),
        sa.Column('schema_version', sa.Text(), nullable=False),
        sa.Column('producer_agent', sa.String(64), nullable=True),
        sa.Column('producer_model', sa.Text(), nullable=True),
        sa.Column('content', sa.JSON(none_as_null=False), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('supersedes_artifact_id', sa.String(36), sa.ForeignKey("artifacts.id", deferrable=True, initially="DEFERRED"), nullable=True),
    )
    op.create_table("gate_evaluations",
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_id', sa.String(36), sa.ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('gate_name', sa.Text(), nullable=False),
        sa.Column('result', sa.String(64), nullable=False),
        sa.Column('checks', sa.JSON(none_as_null=False), nullable=False),
        sa.Column('blocking_reasons', sa.JSON(none_as_null=False), nullable=False),
        sa.Column('evaluated_at', sa.Text(), nullable=False),
    )
    op.create_table("decisions",
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_id', sa.String(36), sa.ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('decision_type', sa.String(64), nullable=False),
        sa.Column('decision_source', sa.Text(), nullable=False),
        sa.Column('reason_code', sa.Text(), nullable=False),
        sa.Column('reason_details', sa.Text(), nullable=False),
        sa.Column('evidence_refs', sa.JSON(none_as_null=False), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False),
    )
    op.create_table("errors",
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_id', sa.String(36), sa.ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('error_type', sa.String(64), nullable=False),
        sa.Column('code', sa.Text(), nullable=False),
        sa.Column('severity', sa.String(64), nullable=False),
        sa.Column('owner', sa.String(64), nullable=False),
        sa.Column('retryable', sa.Boolean(), nullable=False),
        sa.Column('blocking', sa.Boolean(), nullable=False),
        sa.Column('source', sa.JSON(none_as_null=False), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('evidence_refs', sa.JSON(none_as_null=False), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False),
    )
    op.create_table("transitions",
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_id', sa.String(36), sa.ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('from_state', sa.String(64), nullable=False),
        sa.Column('to_state', sa.String(64), nullable=False),
        sa.Column('trigger', sa.Text(), nullable=False),
        sa.Column('gate_evaluation_id', sa.String(36), sa.ForeignKey("gate_evaluations.id", deferrable=True, initially="DEFERRED"), nullable=True),
        sa.Column('decision_id', sa.String(36), sa.ForeignKey("decisions.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False),
    )
    op.create_table("events",
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_id', sa.String(36), sa.ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('event_type', sa.Text(), nullable=False),
        sa.Column('timestamp', sa.Text(), nullable=False),
        sa.Column('actor', sa.JSON(none_as_null=False), nullable=False),
        sa.Column('correlation', sa.JSON(none_as_null=False), nullable=False),
        sa.Column('payload', sa.JSON(none_as_null=False), nullable=False),
    )
    op.create_table("audit_records",
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_id', sa.String(36), sa.ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('actor', sa.JSON(none_as_null=False), nullable=False),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('resource', sa.Text(), nullable=False),
        sa.Column('decision', sa.Text(), nullable=False),
        sa.Column('policy', sa.Text(), nullable=False),
        sa.Column('metadata', sa.JSON(none_as_null=False), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False),
    )
    op.create_table("test_runs",
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_id', sa.String(36), sa.ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('implementation_artifact_id', sa.String(36), sa.ForeignKey("artifacts.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('execution_status', sa.String(64), nullable=False),
        sa.Column('outcome', sa.String(64), nullable=False),
        sa.Column('environment', sa.Text(), nullable=False),
        sa.Column('started_at', sa.Text(), nullable=False),
        sa.Column('finished_at', sa.Text(), nullable=False),
        sa.Column('passed_count', sa.Integer(), nullable=False),
        sa.Column('failed_count', sa.Integer(), nullable=False),
        sa.Column('skipped_count', sa.Integer(), nullable=False),
        sa.Column('report_artifact_id', sa.String(36), sa.ForeignKey("artifacts.id", deferrable=True, initially="DEFERRED"), nullable=True),
        sa.CheckConstraint("passed_count >= 0", name="ck_test_runs_passed_count"),
        sa.CheckConstraint("failed_count >= 0", name="ck_test_runs_failed_count"),
        sa.CheckConstraint("skipped_count >= 0", name="ck_test_runs_skipped_count"),
    )
    op.create_table("failure_fingerprints",
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_id', sa.String(36), sa.ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('test_run_id', sa.String(36), sa.ForeignKey("test_runs.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('fingerprint', sa.Text(), nullable=False),
        sa.Column('test_name', sa.Text(), nullable=False),
        sa.Column('error_class', sa.Text(), nullable=False),
        sa.Column('component', sa.Text(), nullable=False),
        sa.Column('normalized_signature', sa.Text(), nullable=False),
        sa.Column('occurrence_count', sa.Integer(), nullable=False),
        sa.Column('first_seen_at', sa.Text(), nullable=False),
        sa.Column('last_seen_at', sa.Text(), nullable=False),
        sa.CheckConstraint("occurrence_count >= 0", name="ck_failure_fingerprints_occurrence_count"),
    )


def downgrade():
    op.drop_table("failure_fingerprints")
    op.drop_table("test_runs")
    op.drop_table("audit_records")
    op.drop_table("events")
    op.drop_table("transitions")
    op.drop_table("errors")
    op.drop_table("decisions")
    op.drop_table("gate_evaluations")
    op.drop_table("artifacts")
    op.drop_table("invocations")
    op.drop_table("acceptance_criteria")
    op.drop_table("requirements")
    op.drop_table("tasks")
