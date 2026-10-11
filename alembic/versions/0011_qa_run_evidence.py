"""Durable bounded Run Test evidence; preserve existing snapshots and lifecycle."""
from alembic import op
import sqlalchemy as sa
revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("qa_run_tests") as batch:
        batch.create_unique_constraint("uq_qa_run_tests_owner", ["id", "run_id", "campaign_id", "project_id"])
    op.create_table("qa_run_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("run_test_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_test_id", "run_id", "campaign_id", "project_id"],
            ["qa_run_tests.id", "qa_run_tests.run_id", "qa_run_tests.campaign_id", "qa_run_tests.project_id"],
            name="fk_qa_run_evidence_owner", deferrable=True, initially="DEFERRED"),
        sa.UniqueConstraint("run_test_id", "sequence", name="uq_qa_run_evidence_order"),
        sa.CheckConstraint("sequence BETWEEN 1 AND 20", name="ck_qa_run_evidence_order"),
        sa.CheckConstraint("schema_version='qa-run-evidence-v1' AND kind='EXECUTION_OBSERVATION' AND length(source) BETWEEN 1 AND 64", name="ck_qa_run_evidence_contract"),
        sa.CheckConstraint("length(summary) BETWEEN 1 AND 512 AND length(CAST(payload AS BLOB)) <= 2048", name="ck_qa_run_evidence_bounds"))
    for action in ("UPDATE", "DELETE"):
        op.execute(f"CREATE TRIGGER qa_run_evidence_no_{action.lower()} BEFORE {action} ON qa_run_evidence "
            "BEGIN SELECT RAISE(ABORT, 'Run evidence is immutable'); END")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM qa_run_evidence")):
        raise RuntimeError("0011 downgrade cannot erase persisted Run evidence")
    op.drop_table("qa_run_evidence")
    with op.batch_alter_table("qa_run_tests") as batch:
        batch.drop_constraint("uq_qa_run_tests_owner", type_="unique")
