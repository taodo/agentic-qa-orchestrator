"""Durable immutable preparation snapshots, separate from Task/execution jobs."""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("qa_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("note", sa.String(1000), nullable=True),
        sa.Column("snapshot_version", sa.String(32), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("campaign_snapshot", sa.JSON(), nullable=False),
        sa.Column("readiness_at_creation", sa.JSON(), nullable=False),
        sa.Column("requirement_count", sa.Integer(), nullable=False),
        sa.Column("test_count", sa.Integer(), nullable=False),
        sa.Column("execution_status", sa.String(16), nullable=False),
        sa.Column("qa_outcome", sa.String(16), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["campaign_id", "project_id"], ["qa_campaigns.id", "qa_campaigns.project_id"], name="fk_qa_runs_owner", deferrable=True, initially="DEFERRED"),
        sa.UniqueConstraint("id", "campaign_id", "project_id", name="uq_qa_runs_owner"),
        sa.UniqueConstraint("campaign_id", "run_number", name="uq_qa_runs_number"),
        sa.UniqueConstraint("campaign_id", "idempotency_key", name="uq_qa_runs_idempotency"),
        sa.CheckConstraint("run_number >= 1 AND requirement_count BETWEEN 1 AND 1000 AND test_count BETWEEN 1 AND 1000", name="ck_qa_runs_counts"),
        sa.CheckConstraint("length(idempotency_key) BETWEEN 1 AND 128 AND length(snapshot_hash)=64 AND (note IS NULL OR length(note) BETWEEN 1 AND 1000)", name="ck_qa_runs_bounds"),
        sa.CheckConstraint("snapshot_version='qa-run-snapshot-v1'", name="ck_qa_runs_version"),
        sa.CheckConstraint("execution_status IN ('CREATED','QUEUED','RUNNING','COMPLETED','STOPPED','FAILED')", name="ck_qa_runs_execution"),
        sa.CheckConstraint("qa_outcome IN ('NOT_EVALUATED','PASS','FAIL','PARTIAL')", name="ck_qa_runs_outcome"))
    for table, original, prefix in (("qa_run_requirements", "original_requirement_id", "qa_run_requirements"),
                                     ("qa_run_tests", "original_test_specification_id", "qa_run_tests")):
        extra = []
        if table == "qa_run_tests":
            extra = [sa.Column("linked_requirement_snapshot_ids", sa.JSON(), nullable=False),
                sa.Column("execution_status", sa.String(16), nullable=False),
                sa.Column("qa_result", sa.String(16), nullable=False),
                sa.CheckConstraint("execution_status IN ('NOT_STARTED','RUNNING','COMPLETED','BLOCKED')", name="ck_qa_run_tests_execution"),
                sa.CheckConstraint("qa_result IN ('NOT_EVALUATED','PASS','FAIL','SKIP')", name="ck_qa_run_tests_result")]
        op.create_table(table,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("run_id", sa.String(36), nullable=False),
            sa.Column("project_id", sa.String(36), nullable=False),
            sa.Column("campaign_id", sa.String(36), nullable=False),
            sa.Column(original, sa.String(36), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("content", sa.JSON(), nullable=False),
            sa.Column("approval", sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(["run_id", "campaign_id", "project_id"], ["qa_runs.id", "qa_runs.campaign_id", "qa_runs.project_id"], name=f"fk_{prefix}_owner", deferrable=True, initially="DEFERRED"),
            sa.UniqueConstraint("run_id", original, name=f"uq_{prefix}_original"),
            sa.UniqueConstraint("run_id", "position", name=f"uq_{prefix}_order"),
            sa.CheckConstraint("position BETWEEN 1 AND 1000", name=f"ck_{prefix}_position"), *extra)


def downgrade():
    # Match 0007: an operator must explicitly handle historical evidence first.
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM qa_runs")):
        raise RuntimeError("0008 downgrade requires no persisted QA Runs")
    op.drop_table("qa_run_tests")
    op.drop_table("qa_run_requirements")
    op.drop_table("qa_runs")
