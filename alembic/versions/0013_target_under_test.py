"""Add explicit Targets and optional Campaign association/immutable Run context."""
from alembic import op
import sqlalchemy as sa
revision = "0013"
down_revision = "0012"
branch_labels = depends_on = None


def upgrade():
    op.create_table("targets_under_test",
        sa.Column("id",sa.String(36),primary_key=True), sa.Column("project_id",sa.String(36),nullable=False),
        sa.Column("name",sa.String(200),nullable=False), sa.Column("type",sa.String(16),nullable=False),
        sa.Column("environment",sa.String(16),nullable=False),sa.Column("configuration",sa.JSON(),nullable=False),
        sa.Column("created_at",sa.Text(),nullable=False),sa.Column("updated_at",sa.Text(),nullable=False),
        sa.ForeignKeyConstraint(["project_id"],["projects.id"],name="fk_targets_project",deferrable=True,initially="DEFERRED"),
        sa.UniqueConstraint("id","project_id",name="uq_targets_owner"),
        sa.CheckConstraint("type='WEB'",name="ck_targets_type"),
        sa.CheckConstraint("environment IN ('LOCAL','DEVELOPMENT','STAGING','PRODUCTION','OTHER')",name="ck_targets_environment"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 200 AND length(configuration) <= 4096",name="ck_targets_bounds"))
    op.create_index("ix_targets_project_id","targets_under_test",["project_id","id"])
    op.create_table("campaign_targets",
        sa.Column("campaign_id",sa.String(36),primary_key=True),sa.Column("project_id",sa.String(36),nullable=False),sa.Column("target_id",sa.String(36),nullable=False),
        sa.ForeignKeyConstraint(["campaign_id","project_id"],["qa_campaigns.id","qa_campaigns.project_id"],name="fk_campaign_target_campaign",deferrable=True,initially="DEFERRED"),
        sa.ForeignKeyConstraint(["target_id","project_id"],["targets_under_test.id","targets_under_test.project_id"],name="fk_campaign_target_target",deferrable=True,initially="DEFERRED"))
    op.add_column("qa_runs",sa.Column("target_snapshot",sa.JSON(none_as_null=True),nullable=True))
    op.execute("CREATE TRIGGER qa_run_target_no_update BEFORE UPDATE OF target_snapshot ON qa_runs WHEN NEW.target_snapshot IS NOT OLD.target_snapshot BEGIN SELECT RAISE(ABORT, 'Run target snapshot is immutable'); END")


def downgrade():
    connection=op.get_bind()
    if any(connection.scalar(sa.text(query)) for query in (
        "SELECT count(*) FROM targets_under_test", "SELECT count(*) FROM campaign_targets",
        "SELECT count(*) FROM qa_runs WHERE target_snapshot IS NOT NULL")):
        raise RuntimeError("0013 downgrade cannot discard Target configuration or Run target history")
    op.execute("DROP TRIGGER qa_run_target_no_update")
    with op.batch_alter_table("qa_runs") as batch: batch.drop_column("target_snapshot")
    op.drop_table("campaign_targets")
    op.drop_table("targets_under_test")
