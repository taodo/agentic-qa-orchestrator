"""Explicit immutable preparation approvals; no workflow/execution schema changes."""
from alembic import op
import sqlalchemy as sa
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def status_constraints(approved):
    statuses = "'DRAFT','NEEDS_CLARIFICATION','READY_FOR_REVIEW'" + (",'APPROVED'" if approved else "")
    for table, constraint in (("campaign_requirements", "ck_campaign_requirements_review"),
                              ("campaign_test_specifications", "ck_test_specifications_review")):
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.drop_constraint(constraint, type_="check")
            batch.create_check_constraint(constraint, f"review_status IN ({statuses})")


def upgrade():
    status_constraints(True)
    op.create_index("ix_test_links_campaign_requirement", "campaign_test_requirement_links", ["campaign_id", "requirement_id", "test_spec_id"], unique=False)
    for table, target, prefix in (("campaign_requirement_reviews", "campaign_requirements", "requirement_reviews"),
                                  ("campaign_test_reviews", "campaign_test_specifications", "test_reviews")):
        op.create_table(table,
            sa.Column("object_id", sa.String(36), primary_key=True, nullable=False),
            sa.Column("campaign_id", sa.String(36), nullable=False),
            sa.Column("project_id", sa.String(36), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("reviewer_label", sa.String(64), nullable=False),
            sa.Column("note", sa.String(1000), nullable=True),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("approved_at", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["object_id", "campaign_id", "project_id"], [f"{target}.id", f"{target}.campaign_id", f"{target}.project_id"], name=f"fk_{prefix}_object_owner", deferrable=True, initially="DEFERRED"),
            sa.CheckConstraint("status='APPROVED'", name=f"ck_{prefix}_status"),
            sa.CheckConstraint("length(reviewer_label) BETWEEN 1 AND 64 AND (note IS NULL OR length(note) BETWEEN 1 AND 1000) AND length(content_hash)=64", name=f"ck_{prefix}_bounds"))
        op.create_index(f"ix_{prefix}_campaign", table, ["campaign_id", "object_id"], unique=False)


def downgrade():
    # Refuse destructive downgrade rather than erase durable human approval.
    connection = op.get_bind()
    for table in ("campaign_requirement_reviews", "campaign_test_reviews"):
        if connection.scalar(sa.text(f"SELECT count(*) FROM {table}")):
            raise RuntimeError("0007 downgrade requires no persisted approval evidence")
    for table in ("campaign_requirements", "campaign_test_specifications"):
        if connection.scalar(sa.text(f"SELECT count(*) FROM {table} WHERE review_status='APPROVED'")):
            raise RuntimeError("0007 downgrade cannot erase APPROVED status")
    op.drop_table("campaign_test_reviews")
    op.drop_table("campaign_requirement_reviews")
    op.drop_index("ix_test_links_campaign_requirement", table_name="campaign_test_requirement_links")
    status_constraints(False)
