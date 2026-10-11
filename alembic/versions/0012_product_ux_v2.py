"""Add document provenance and selective Run snapshot contract; preserve audit data."""
from alembic import op
import sqlalchemy as sa
revision = "0012"
down_revision = "0011"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("campaign_sources") as b:
        b.add_column(sa.Column("purpose",sa.String(32),nullable=False,server_default="SPECIFICATION"))
        b.add_column(sa.Column("document",sa.JSON(none_as_null=True),nullable=True))
        b.drop_constraint("uq_campaign_sources_content",type_="unique")
        b.create_unique_constraint("uq_campaign_sources_content",["campaign_id","source_type","content_hash","normalization_version","purpose","raw_hash"])
        b.drop_constraint("ck_campaign_sources_type",type_="check")
        b.create_check_constraint("ck_campaign_sources_type","source_type IN ('TEXT','MARKDOWN','PDF','DOCX')")
        b.drop_constraint("ck_campaign_sources_bounds",type_="check")
        b.create_check_constraint("ck_campaign_sources_bounds","original_bytes BETWEEN 0 AND 2097152 AND normalized_chars BETWEEN 0 AND 65536 AND line_count BETWEEN 0 AND 4096")
    op.execute("UPDATE campaign_sources SET purpose='CLARIFICATION' WHERE id IN (SELECT source_id FROM campaign_clarifications)")
    with op.batch_alter_table("qa_runs") as b:
        b.drop_constraint("ck_qa_runs_version",type_="check")
        b.create_check_constraint("ck_qa_runs_version","snapshot_version IN ('qa-run-snapshot-v1','qa-run-selection-v2')")


    with op.batch_alter_table("campaign_test_specifications") as b:
        b.drop_constraint("ck_test_specifications_origin",type_="check")
        b.create_check_constraint("ck_test_specifications_origin", "(import_id IS NOT NULL AND generation_id IS NULL) OR (generation_id IS NOT NULL AND import_id IS NULL) OR (generation_id IS NULL AND import_id IS NULL AND json_extract(provenance, '$.origin') = 'HUMAN_EDIT')")
    op.create_table("campaign_test_edits",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("project_id",sa.String(36),nullable=False),sa.Column("campaign_id",sa.String(36),nullable=False),
        sa.Column("test_id",sa.String(36),nullable=False),sa.Column("previous_id",sa.String(36),nullable=False),
        sa.Column("source_id",sa.String(36),nullable=False),sa.Column("version",sa.Integer(),nullable=False),
        sa.Column("reviewer_label",sa.String(128),nullable=False),sa.Column("note",sa.Text(),nullable=False),
        sa.Column("previous_hash",sa.String(64),nullable=False),sa.Column("created_at",sa.Text(),nullable=False),
        sa.ForeignKeyConstraint(["test_id","campaign_id","project_id"],["campaign_test_specifications.id","campaign_test_specifications.campaign_id","campaign_test_specifications.project_id"],name="fk_test_edit_new",deferrable=True,initially="DEFERRED"),
        sa.ForeignKeyConstraint(["previous_id","campaign_id","project_id"],["campaign_test_specifications.id","campaign_test_specifications.campaign_id","campaign_test_specifications.project_id"],name="fk_test_edit_previous",deferrable=True,initially="DEFERRED"),
        sa.ForeignKeyConstraint(["source_id","campaign_id","project_id"],["campaign_sources.id","campaign_sources.campaign_id","campaign_sources.project_id"],name="fk_test_edit_source",deferrable=True,initially="DEFERRED"),
        sa.UniqueConstraint("previous_id",name="uq_test_edit_previous"),sa.UniqueConstraint("test_id",name="uq_test_edit_new"),
        sa.CheckConstraint("version BETWEEN 2 AND 10 AND test_id != previous_id",name="ck_test_edit_version"))
    for action in ("UPDATE","DELETE"):
        op.execute(f"CREATE TRIGGER test_edits_no_{action.lower()} BEFORE {action} ON campaign_test_edits BEGIN SELECT RAISE(ABORT, 'Test review evidence is immutable'); END")


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM campaign_test_edits")) or connection.scalar(sa.text("SELECT count(*) FROM campaign_sources WHERE document IS NOT NULL OR source_type='DOCX' OR original_bytes>65536 OR purpose = 'TEST_REVIEW'")) or connection.scalar(sa.text("SELECT count(*) FROM qa_runs WHERE snapshot_version='qa-run-selection-v2'")):
        raise RuntimeError("0012 downgrade cannot discard V2 document or selected Run audit data")
    if connection.scalar(sa.text("SELECT count(*) FROM (SELECT 1 FROM campaign_sources GROUP BY campaign_id,source_type,content_hash,normalization_version HAVING count(*)>1)")):
        raise RuntimeError("0012 downgrade cannot collapse distinct source provenance")
    op.drop_table("campaign_test_edits")
    with op.batch_alter_table("campaign_test_specifications") as b:
        b.drop_constraint("ck_test_specifications_origin",type_="check")
        b.create_check_constraint("ck_test_specifications_origin","(import_id IS NOT NULL AND generation_id IS NULL) OR (generation_id IS NOT NULL AND import_id IS NULL)")
    with op.batch_alter_table("qa_runs") as b:
        b.drop_constraint("ck_qa_runs_version",type_="check")
        b.create_check_constraint("ck_qa_runs_version","snapshot_version='qa-run-snapshot-v1'")
    with op.batch_alter_table("campaign_sources") as b:
        b.drop_constraint("ck_campaign_sources_type",type_="check")
        b.create_check_constraint("ck_campaign_sources_type","source_type IN ('TEXT','MARKDOWN','PDF')")
        b.drop_constraint("ck_campaign_sources_bounds",type_="check")
        b.create_check_constraint("ck_campaign_sources_bounds","original_bytes BETWEEN 0 AND 65536 AND normalized_chars BETWEEN 0 AND 65536 AND line_count BETWEEN 0 AND 4096")
        b.drop_constraint("uq_campaign_sources_content",type_="unique")
        b.create_unique_constraint("uq_campaign_sources_content",["campaign_id","source_type","content_hash","normalization_version"])
        b.drop_column("document")
        b.drop_column("purpose")
