"""Source-free browser snapshots and separate durable pre-Run preparation."""
from alembic import op
import sqlalchemy as sa
revision = "0016"
down_revision = "0015"
branch_labels = depends_on = None


def rebuild_runs(upgrade):
    db = op.get_bind()
    triggers = list(db.execute(sa.text("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='qa_runs' AND name NOT IN ('qa_run_preparation_seal','qa_run_preparation_ready')")))
    with op.batch_alter_table("qa_runs") as b:
        b.drop_constraint("ck_qa_runs_counts", type_="check")
        b.drop_constraint("ck_qa_runs_version", type_="check")
        if upgrade:
            b.add_column(sa.Column("preparation_id", sa.String(36), nullable=True))
            b.create_unique_constraint("uq_qa_run_preparation", ["preparation_id"])
            b.create_foreign_key("fk_qa_run_preparation", "browser_preparations", ["preparation_id","campaign_id","project_id"], ["id","campaign_id","project_id"], deferrable=True, initially="DEFERRED")
            b.create_check_constraint("ck_qa_runs_browser_version", "snapshot_version!='qa-run-browser-v3' OR (executor_kind='WEB_BROWSER' AND runtime_identity IS NOT NULL AND target_snapshot IS NOT NULL)")
            b.create_check_constraint("ck_qa_run_preparation", "preparation_id IS NULL OR (snapshot_version='qa-run-browser-v3' AND executor_kind='WEB_BROWSER')")
            b.create_check_constraint("ck_qa_runs_counts", "run_number >= 1 AND requirement_count BETWEEN 0 AND 1000 AND test_count BETWEEN 1 AND 1000 AND (snapshot_version='qa-run-browser-v3' OR requirement_count>=1)")
            b.create_check_constraint("ck_qa_runs_version", "snapshot_version IN ('qa-run-snapshot-v1','qa-run-selection-v2','qa-run-browser-v3')")
        else:
            b.drop_constraint("uq_qa_run_preparation", type_="unique")
            b.drop_constraint("fk_qa_run_preparation", type_="foreignkey")
            b.drop_constraint("ck_qa_run_preparation", type_="check")
            b.drop_constraint("ck_qa_runs_browser_version", type_="check")
            b.drop_column("preparation_id")
            b.create_check_constraint("ck_qa_runs_counts", "run_number >= 1 AND requirement_count BETWEEN 1 AND 1000 AND test_count BETWEEN 1 AND 1000")
            b.create_check_constraint("ck_qa_runs_version", "snapshot_version IN ('qa-run-snapshot-v1','qa-run-selection-v2')")
    for name, ddl in triggers:
        if not db.scalar(sa.text("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name=:name"), {"name":name}):
            op.execute(ddl)


def upgrade():
    op.create_table("browser_preparations",
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('campaign_id', sa.String(36), nullable=False),
        sa.Column('target_id', sa.String(36), nullable=False),
        sa.Column('contract_version', sa.String(32), nullable=False),
        sa.Column('browser_mode', sa.String(16), nullable=False),
        sa.Column('idempotency_key', sa.String(128), nullable=False),
        sa.Column('selection_hash', sa.String(64), nullable=False),
        sa.Column('selected_count', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),

        sa.UniqueConstraint("id", "campaign_id", "project_id", name="uq_browser_preparation_owner"),
        sa.UniqueConstraint("campaign_id", "idempotency_key", name="uq_browser_preparation_key"),
        sa.ForeignKeyConstraint(["campaign_id", "project_id"], ["qa_campaigns.id", "qa_campaigns.project_id"], name="fk_browser_preparation_campaign", deferrable=True, initially="DEFERRED"),
        sa.ForeignKeyConstraint(["target_id", "project_id"], ["targets_under_test.id", "targets_under_test.project_id"], name="fk_browser_preparation_target", deferrable=True, initially="DEFERRED"),
        sa.CheckConstraint("contract_version='browser-preparation-v1' AND browser_mode IN ('HEADLESS','HEADED') AND selected_count BETWEEN 1 AND 500 AND length(selection_hash)=64 AND length(idempotency_key) BETWEEN 1 AND 128", name="ck_browser_preparation_bounds"),
        sa.CheckConstraint("status IN ('CREATED','PREPARING','COMPLETED','FAILED') AND json_extract(payload,'$.status')=status AND json_extract(payload,'$.id')=id AND json_extract(payload,'$.project_id')=project_id AND json_extract(payload,'$.campaign_id')=campaign_id AND json_extract(payload,'$.target_snapshot.target_id')=target_id AND json_extract(payload,'$.browser_mode')=browser_mode AND json_extract(payload,'$.idempotency_key')=idempotency_key AND json_extract(payload,'$.selection_hash')=selection_hash AND json_extract(payload,'$.contract_version')=contract_version AND json_extract(payload,'$.selected_count')=selected_count AND json_array_length(payload,'$.items')=selected_count AND length(CAST(payload AS BLOB))<=16777216", name="ck_browser_preparation_payload"),

    )
    op.create_index("ix_browser_preparation_owner", "browser_preparations", ["project_id","campaign_id","created_at","id"])
    rebuild_runs(True)
    op.execute("CREATE TRIGGER browser_preparation_no_delete BEFORE DELETE ON browser_preparations BEGIN SELECT RAISE(ABORT,'Preparation history is immutable'); END")
    op.execute("CREATE TRIGGER browser_preparation_insert BEFORE INSERT ON browser_preparations WHEN NEW.status!='CREATED' OR EXISTS (SELECT 1 FROM json_each(NEW.payload,'$.items') item WHERE json_extract(item.value,'$.status')!='PENDING' OR NOT EXISTS(SELECT 1 FROM campaign_test_specifications t WHERE t.id=json_extract(item.value,'$.original_test_id') AND t.project_id=NEW.project_id AND t.campaign_id=NEW.campaign_id)) BEGIN SELECT RAISE(ABORT,'Preparation requires pending owned Tests'); END")
    op.execute("CREATE TRIGGER browser_preparation_seal BEFORE UPDATE ON browser_preparations WHEN OLD.status IN ('COMPLETED','FAILED') OR NEW.id!=OLD.id OR NEW.project_id!=OLD.project_id OR NEW.campaign_id!=OLD.campaign_id OR NEW.target_id!=OLD.target_id OR NEW.contract_version!=OLD.contract_version OR NEW.browser_mode!=OLD.browser_mode OR NEW.idempotency_key!=OLD.idempotency_key OR NEW.selection_hash!=OLD.selection_hash OR NEW.selected_count!=OLD.selected_count OR NEW.created_at!=OLD.created_at OR (OLD.status='PREPARING' AND json_extract(NEW.payload,'$.started_at') IS NOT json_extract(OLD.payload,'$.started_at')) OR json_remove(NEW.payload,'$.items','$.status','$.started_at','$.finished_at','$.error_code')!=json_remove(OLD.payload,'$.items','$.status','$.started_at','$.finished_at','$.error_code') OR json_extract(NEW.payload,'$.started_at') IS NULL OR (NEW.status='COMPLETED' AND (json_extract(NEW.payload,'$.finished_at') IS NULL OR json_extract(NEW.payload,'$.error_code') IS NOT NULL OR EXISTS (SELECT 1 FROM json_each(NEW.payload,'$.items') i WHERE json_extract(i.value,'$.status') NOT IN ('RUNNABLE','NEEDS_ATTENTION','SYSTEM_ERROR')))) OR (NEW.status='FAILED' AND (json_extract(NEW.payload,'$.finished_at') IS NULL OR COALESCE(json_extract(NEW.payload,'$.error_code'),'') NOT IN ('PREPARATION_SYSTEM_ERROR','PREPARATION_INTERRUPTED'))) OR NOT ((OLD.status='CREATED' AND NEW.status='PREPARING') OR (OLD.status='PREPARING' AND NEW.status IN ('PREPARING','COMPLETED','FAILED'))) OR EXISTS (SELECT 1 FROM json_each(NEW.payload,'$.items') n JOIN json_each(OLD.payload,'$.items') o ON n.key=o.key WHERE json_remove(n.value,'$.status','$.attempt_id','$.started_at','$.finished_at','$.reason_code','$.grounding_id','$.observation_hash','$.plan_hash')!=json_remove(o.value,'$.status','$.attempt_id','$.started_at','$.finished_at','$.reason_code','$.grounding_id','$.observation_hash','$.plan_hash') OR (n.value!=o.value AND NOT (OLD.status='PREPARING' AND NEW.status='PREPARING' AND ((json_extract(o.value,'$.status')='PENDING' AND json_extract(n.value,'$.status')='PREPARING') OR (json_extract(o.value,'$.status')='PREPARING' AND json_extract(n.value,'$.status') IN ('RUNNABLE','NEEDS_ATTENTION','SYSTEM_ERROR') AND json_extract(n.value,'$.attempt_id')=json_extract(o.value,'$.attempt_id') AND json_extract(n.value,'$.started_at')=json_extract(o.value,'$.started_at')))))) BEGIN SELECT RAISE(ABORT,'Preparation seal or lifecycle violation'); END")
    op.execute("CREATE TRIGGER qa_run_preparation_seal BEFORE UPDATE OF preparation_id ON qa_runs WHEN NEW.preparation_id IS NOT OLD.preparation_id BEGIN SELECT RAISE(ABORT,'Run preparation link is immutable'); END")
    op.execute("CREATE TRIGGER qa_run_preparation_ready BEFORE INSERT ON qa_runs WHEN NEW.preparation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM browser_preparations p WHERE p.id=NEW.preparation_id AND p.project_id=NEW.project_id AND p.campaign_id=NEW.campaign_id AND p.status='COMPLETED' AND EXISTS (SELECT 1 FROM json_each(p.payload,'$.items') i WHERE json_extract(i.value,'$.status')='RUNNABLE')) BEGIN SELECT RAISE(ABORT,'Run requires completed runnable preparation'); END")


def downgrade():
    db = op.get_bind()
    if db.scalar(sa.text("SELECT count(*) FROM campaign_test_specifications t WHERE t.review_status='APPROVED' AND EXISTS (SELECT 1 FROM json_each(t.information_markers) m WHERE json_extract(m.value,'$.kind')='MISSING_TRACEABILITY')")):
        raise RuntimeError("0016 downgrade cannot erase source-free approval history")
    if db.scalar(sa.text("SELECT count(*) FROM browser_preparations")) or db.scalar(sa.text("SELECT count(*) FROM qa_runs WHERE snapshot_version='qa-run-browser-v3' OR preparation_id IS NOT NULL")):
        raise RuntimeError("0016 downgrade cannot erase preparation or browser-v3 history")
    op.execute("DROP TRIGGER qa_run_preparation_seal")
    op.execute("DROP TRIGGER qa_run_preparation_ready")
    rebuild_runs(False)
    op.drop_table("browser_preparations")
