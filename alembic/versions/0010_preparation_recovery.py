"""Explicit extraction attempts, inert clarification sources and immutable revisions."""
from alembic import op
import sqlalchemy as sa
revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("campaign_requirement_extractions") as batch:
        batch.drop_constraint("uq_requirement_extractions_source", type_="unique")
        batch.add_column(sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("parent_attempt_id", sa.String(36), nullable=True))
        batch.create_unique_constraint("uq_requirement_extractions_attempt", ["source_id", "attempt_number"])
        batch.create_unique_constraint("uq_requirement_extractions_parent", ["parent_attempt_id"])
        batch.create_foreign_key("fk_extraction_parent", "campaign_requirement_extractions", ["parent_attempt_id", "campaign_id", "project_id"], ["id", "campaign_id", "project_id"], deferrable=True, initially="DEFERRED")
        batch.create_check_constraint("ck_extraction_attempt", "attempt_number BETWEEN 1 AND 3 AND ((attempt_number=1 AND parent_attempt_id IS NULL) OR (attempt_number>1 AND parent_attempt_id IS NOT NULL))")
    op.create_table("campaign_clarifications",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("project_id",sa.String(36),nullable=False),
        sa.Column("campaign_id",sa.String(36),nullable=False),
        sa.Column("requirement_id",sa.String(36),nullable=False),
        sa.Column("source_id",sa.String(36),nullable=False),
        sa.Column("request_key",sa.String(128),nullable=False),
        sa.Column("facts_hash",sa.String(64),nullable=False),
        sa.Column("first_fact_line",sa.Integer(),nullable=False),
        sa.Column("created_at",sa.Text(),nullable=False),
        sa.ForeignKeyConstraint(["requirement_id","campaign_id","project_id"],["campaign_requirements.id","campaign_requirements.campaign_id","campaign_requirements.project_id"],name="fk_clarification_requirement",deferrable=True,initially="DEFERRED"),
        sa.ForeignKeyConstraint(["source_id","campaign_id","project_id"],["campaign_sources.id","campaign_sources.campaign_id","campaign_sources.project_id"],name="fk_clarification_source",deferrable=True,initially="DEFERRED"),
        sa.UniqueConstraint("campaign_id","request_key",name="uq_clarification_request"),
        sa.UniqueConstraint("source_id",name="uq_clarification_source"),
        sa.UniqueConstraint("id","campaign_id","project_id",name="uq_clarification_owner"),
        sa.CheckConstraint("length(request_key) BETWEEN 1 AND 128 AND length(facts_hash)=64 AND first_fact_line BETWEEN 1 AND 4096",name="ck_clarification_bounds"))
    op.create_table("campaign_requirement_revisions",
        sa.Column("requirement_id",sa.String(36),primary_key=True),
        sa.Column("project_id",sa.String(36),nullable=False),
        sa.Column("campaign_id",sa.String(36),nullable=False),
        sa.Column("supersedes_id",sa.String(36),nullable=False),
        sa.Column("clarification_id",sa.String(36),nullable=False),
        sa.Column("version",sa.Integer(),nullable=False),
        sa.ForeignKeyConstraint(["requirement_id","campaign_id","project_id"],["campaign_requirements.id","campaign_requirements.campaign_id","campaign_requirements.project_id"],name="fk_revision_current",deferrable=True,initially="DEFERRED"),
        sa.ForeignKeyConstraint(["supersedes_id","campaign_id","project_id"],["campaign_requirements.id","campaign_requirements.campaign_id","campaign_requirements.project_id"],name="fk_revision_previous",deferrable=True,initially="DEFERRED"),
        sa.ForeignKeyConstraint(["clarification_id","campaign_id","project_id"],["campaign_clarifications.id","campaign_clarifications.campaign_id","campaign_clarifications.project_id"],name="fk_revision_clarification",deferrable=True,initially="DEFERRED"),
        sa.UniqueConstraint("supersedes_id",name="uq_revision_previous"),
        sa.UniqueConstraint("clarification_id",name="uq_revision_clarification"),
        sa.CheckConstraint("version BETWEEN 2 AND 10 AND requirement_id != supersedes_id",name="ck_revision_version"))


def downgrade():
    connection = op.get_bind()
    if any(connection.scalar(sa.text(query)) for query in (
        "SELECT count(*) FROM campaign_requirement_extractions WHERE attempt_number != 1",
        "SELECT count(*) FROM campaign_clarifications", "SELECT count(*) FROM campaign_requirement_revisions")):
        raise RuntimeError("0010 downgrade cannot erase preparation recovery audit history")
    op.drop_table("campaign_requirement_revisions")
    op.drop_table("campaign_clarifications")
    with op.batch_alter_table("campaign_requirement_extractions") as batch:
        batch.drop_constraint("ck_extraction_attempt", type_="check")
        batch.drop_constraint("fk_extraction_parent", type_="foreignkey")
        batch.drop_constraint("uq_requirement_extractions_parent", type_="unique")
        batch.drop_constraint("uq_requirement_extractions_attempt", type_="unique")
        batch.drop_column("parent_attempt_id")
        batch.drop_column("attempt_number")
        batch.create_unique_constraint("uq_requirement_extractions_source", ["source_id"])
