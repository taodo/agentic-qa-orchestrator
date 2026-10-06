"""Small durable execution requests, independent of workflow evidence."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("execution_jobs",
        sa.Column("sequence", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.Text(), nullable=True),
        sa.Column("safe_error_code", sa.String(32), nullable=True),
        sa.UniqueConstraint("id", name="uq_execution_jobs_id"),
        sa.CheckConstraint("status IN ('QUEUED','RUNNING','SUCCEEDED','STOPPED','FAILED')", name="ck_execution_jobs_status"),
        sa.CheckConstraint("(status = 'QUEUED' AND started_at IS NULL AND finished_at IS NULL AND safe_error_code IS NULL) OR "
            "(status = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL AND safe_error_code IS NULL) OR "
            "(status = 'SUCCEEDED' AND started_at IS NOT NULL AND finished_at IS NOT NULL AND safe_error_code IS NULL) OR "
            "(status = 'STOPPED' AND started_at IS NOT NULL AND finished_at IS NOT NULL AND safe_error_code IS NOT NULL AND safe_error_code IN ('RUNTIME_STOPPED','EXECUTION_INTERRUPTED')) OR "
            "(status = 'FAILED' AND started_at IS NOT NULL AND finished_at IS NOT NULL AND safe_error_code IS NOT NULL AND safe_error_code = 'EXECUTION_FAILED')",
            name="ck_execution_jobs_lifecycle"), sqlite_autoincrement=True)
    op.create_index("ix_execution_jobs_queue", "execution_jobs", ["status", "sequence"])
    op.create_index("ix_execution_jobs_task", "execution_jobs", ["task_id", "sequence"])
    op.create_index("uq_execution_jobs_active_task", "execution_jobs", ["task_id"], unique=True,
        sqlite_where=sa.text("status IN ('QUEUED','RUNNING')"))
    op.create_index("uq_execution_jobs_running", "execution_jobs", ["status"], unique=True,
        sqlite_where=sa.text("status = 'RUNNING'"))


def downgrade():
    op.drop_table("execution_jobs")
