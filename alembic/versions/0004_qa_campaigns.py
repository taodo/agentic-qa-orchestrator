"""Project-owned campaign preparation identity only."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("qa_campaigns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", name="fk_qa_campaigns_project_id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT','READY_FOR_REVIEW','APPROVED')", name="ck_qa_campaigns_status"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 200", name="ck_qa_campaigns_name"),
        sa.CheckConstraint("objective IS NULL OR length(objective) <= 4000", name="ck_qa_campaigns_objective"))
    op.create_index("ix_qa_campaigns_project_created", "qa_campaigns", ["project_id", "created_at", "id"])


def downgrade():
    op.drop_table("qa_campaigns")
