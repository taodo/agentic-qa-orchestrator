"""Immutable normalized sources, requirements and bounded extraction evidence."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    # Related parent identity index makes composite child ownership enforceable in SQLite.
    op.create_index("uq_qa_campaigns_id_project", "qa_campaigns", ["id", "project_id"], unique=True)
    op.create_table("campaign_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_hash", sa.String(64), nullable=False),
        sa.Column("normalization_version", sa.String(32), nullable=False),
        sa.Column("original_bytes", sa.Integer(), nullable=False),
        sa.Column("normalized_chars", sa.Integer(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id", "project_id"], ["qa_campaigns.id", "qa_campaigns.project_id"], name="fk_campaign_sources_owner", deferrable=True, initially="DEFERRED"),
        sa.UniqueConstraint("id", "campaign_id", "project_id", name="uq_campaign_sources_owner"),
        sa.UniqueConstraint("campaign_id", "source_type", "content_hash", "normalization_version", name="uq_campaign_sources_content"),
        sa.CheckConstraint("source_type IN ('TEXT','MARKDOWN','PDF')", name="ck_campaign_sources_type"),
        sa.CheckConstraint("(status='INGESTED' AND normalized_text IS NOT NULL AND error_code IS NULL AND line_count>=1) OR (status='REJECTED' AND normalized_text IS NULL AND error_code IS NOT NULL AND line_count=0 AND normalized_chars=0)", name="ck_campaign_sources_ingestion"),
        sa.CheckConstraint("original_bytes BETWEEN 0 AND 65536 AND normalized_chars BETWEEN 0 AND 65536 AND line_count BETWEEN 0 AND 4096", name="ck_campaign_sources_bounds"))
    op.create_index("ix_campaign_sources_campaign", "campaign_sources", ["campaign_id", "created_at", "id"])
    op.create_table("campaign_requirement_extractions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("contract_version", sa.String(32), nullable=False),
        sa.Column("agent", sa.String(16), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("finished_at", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("metadata", sa.JSON(none_as_null=True), nullable=True),
        sa.ForeignKeyConstraint(["source_id", "campaign_id", "project_id"], ["campaign_sources.id", "campaign_sources.campaign_id", "campaign_sources.project_id"], name="fk_requirement_extractions_source_owner", deferrable=True, initially="DEFERRED"),
        sa.UniqueConstraint("source_id", name="uq_requirement_extractions_source"),
        sa.UniqueConstraint("id", "campaign_id", "project_id", name="uq_requirement_extractions_owner"),
        sa.CheckConstraint("(status='STARTED' AND finished_at IS NULL AND error_code IS NULL AND metadata IS NULL) OR (status='SUCCEEDED' AND finished_at IS NOT NULL AND error_code IS NULL) OR (status='FAILED' AND finished_at IS NOT NULL AND error_code IS NOT NULL)", name="ck_requirement_extractions_lifecycle"))
    op.create_index("ix_requirement_extractions_campaign", "campaign_requirement_extractions", ["campaign_id", "started_at", "id"])
    op.create_table("campaign_requirements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("extraction_id", sa.String(36), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("logical_key", sa.String(128), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("acceptance_criteria", sa.JSON(), nullable=False),
        sa.Column("source_references", sa.JSON(), nullable=False),
        sa.Column("information_markers", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["extraction_id", "campaign_id", "project_id"], ["campaign_requirement_extractions.id", "campaign_requirement_extractions.campaign_id", "campaign_requirement_extractions.project_id"], name="fk_campaign_requirements_extraction_owner", deferrable=True, initially="DEFERRED"),
        sa.UniqueConstraint("campaign_id", "logical_key", name="uq_campaign_requirements_key"),
        sa.UniqueConstraint("extraction_id", "key", name="uq_campaign_requirements_local_key"),
        sa.CheckConstraint("review_status IN ('DRAFT','NEEDS_CLARIFICATION','READY_FOR_REVIEW')", name="ck_campaign_requirements_review"))
    op.create_index("ix_campaign_requirements_campaign", "campaign_requirements", ["campaign_id", "created_at", "id"])


def downgrade():
    op.drop_table("campaign_requirements")
    op.drop_table("campaign_requirement_extractions")
    op.drop_table("campaign_sources")
    op.drop_index("uq_qa_campaigns_id_project", table_name="qa_campaigns")
