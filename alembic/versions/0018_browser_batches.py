"""Durable browser submissions and per-item plan/materialization receipts."""
from alembic import op
import sqlalchemy as sa
revision="0018"
down_revision="0017"
branch_labels=depends_on=None


def upgrade():
    op.create_table("browser_batch_submissions",
        sa.Column("preparation_id",sa.String(36),nullable=False,primary_key=True),
        sa.Column("project_id",sa.String(36),nullable=False),
        sa.Column("campaign_id",sa.String(36),nullable=False),
        sa.Column("created_at",sa.Text(),nullable=False),
        sa.Column("payload",sa.JSON(),nullable=False),
        sa.UniqueConstraint("preparation_id","campaign_id","project_id",name="uq_batch_submission_owner"),
        sa.ForeignKeyConstraint(["preparation_id","campaign_id","project_id"],["browser_preparations.id","browser_preparations.campaign_id","browser_preparations.project_id"],name="fk_batch_submission_preparation",deferrable=True,initially="DEFERRED"),
        sa.CheckConstraint("json_extract(payload,'$.contract_version') IS 'browser-batch-submit-v1' AND json_extract(payload,'$.preparation_id') IS preparation_id AND json_extract(payload,'$.project_id') IS project_id AND json_extract(payload,'$.campaign_id') IS campaign_id AND length(CAST(payload AS BLOB))<=2048",name="ck_batch_submission_payload"),
    )
    op.execute("CREATE TRIGGER batch_submission_insert BEFORE INSERT ON browser_batch_submissions WHEN NOT EXISTS (SELECT 1 FROM browser_preparations p WHERE p.id=NEW.preparation_id AND p.project_id=NEW.project_id AND p.campaign_id=NEW.campaign_id AND p.status='CREATED' AND p.selection_hash=json_extract(NEW.payload,'$.selection_hash') AND p.browser_mode=json_extract(NEW.payload,'$.browser_mode')) BEGIN SELECT RAISE(ABORT,'Batch submission requires immutable created selection'); END")
    op.execute("CREATE TRIGGER batch_submission_ack BEFORE UPDATE ON browser_batch_submissions WHEN NEW.preparation_id!=OLD.preparation_id OR NEW.project_id!=OLD.project_id OR NEW.campaign_id!=OLD.campaign_id OR NEW.created_at!=OLD.created_at OR json_remove(NEW.payload,'$.interruption_acknowledged_at')!=json_remove(OLD.payload,'$.interruption_acknowledged_at') OR json_extract(OLD.payload,'$.interruption_acknowledged_at') IS NOT NULL OR julianday(json_extract(NEW.payload,'$.interruption_acknowledged_at')) IS NULL OR julianday(json_extract(NEW.payload,'$.interruption_acknowledged_at'))<julianday(OLD.created_at) BEGIN SELECT RAISE(ABORT,'Batch submission is immutable except explicit interruption acknowledgement'); END")
    op.execute("CREATE TRIGGER browser_batch_submissions_no_delete BEFORE DELETE ON browser_batch_submissions BEGIN SELECT RAISE(ABORT,'Batch provenance is immutable'); END")
    op.create_table("browser_batch_plans",
        sa.Column("id",sa.String(36),nullable=False,primary_key=True),
        sa.Column("project_id",sa.String(36),nullable=False),
        sa.Column("campaign_id",sa.String(36),nullable=False),
        sa.Column("preparation_id",sa.String(36),nullable=False),
        sa.Column("item_id",sa.String(36),nullable=False),
        sa.Column("attempt_id",sa.String(36),nullable=False),
        sa.Column("test_id",sa.String(36),nullable=False),
        sa.Column("grounding_id",sa.String(36),nullable=False),
        sa.Column("observation_id",sa.String(36),nullable=False),
        sa.Column("plan_hash",sa.String(64),nullable=False),
        sa.Column("payload",sa.JSON(),nullable=False),
        sa.UniqueConstraint("id","campaign_id","project_id",name="uq_batch_plan_owner"),
        sa.UniqueConstraint("preparation_id","item_id",name="uq_batch_plan_item"),
        sa.ForeignKeyConstraint(["preparation_id","campaign_id","project_id"],["browser_batch_submissions.preparation_id","browser_batch_submissions.campaign_id","browser_batch_submissions.project_id"],name="fk_batch_plan_submission",deferrable=True,initially="DEFERRED"),
        sa.ForeignKeyConstraint(["grounding_id","campaign_id","project_id"],["browser_groundings.id","browser_groundings.campaign_id","browser_groundings.project_id"],name="fk_batch_plan_grounding",deferrable=True,initially="DEFERRED"),
        sa.ForeignKeyConstraint(["observation_id","campaign_id","project_id"],["browser_grounding_observations.id","browser_grounding_observations.campaign_id","browser_grounding_observations.project_id"],name="fk_batch_plan_observation",deferrable=True,initially="DEFERRED"),
        sa.CheckConstraint("json_extract(payload,'$.contract_version') IS 'browser-batch-plan-v1' AND json_extract(payload,'$.id') IS id AND json_extract(payload,'$.scope.project_id') IS project_id AND json_extract(payload,'$.scope.campaign_id') IS campaign_id AND json_extract(payload,'$.scope.preparation_id') IS preparation_id AND json_extract(payload,'$.scope.item_id') IS item_id AND json_extract(payload,'$.scope.attempt_id') IS attempt_id AND json_extract(payload,'$.scope.test_id') IS test_id AND json_extract(payload,'$.grounding_id') IS grounding_id AND json_extract(payload,'$.observation_id') IS observation_id AND json_extract(payload,'$.plan_hash') IS plan_hash AND length(CAST(payload AS BLOB))<=1048576",name="ck_batch_plan_payload"),
    )
    op.execute("CREATE TRIGGER batch_plan_insert BEFORE INSERT ON browser_batch_plans WHEN NOT EXISTS (SELECT 1 FROM browser_groundings g,browser_grounding_observations o,browser_preparations p,json_each(p.payload,'$.items') i WHERE g.id=NEW.grounding_id AND g.status='GROUNDED' AND g.project_id=NEW.project_id AND g.campaign_id=NEW.campaign_id AND g.preparation_id=NEW.preparation_id AND g.item_id=NEW.item_id AND g.attempt_id=NEW.attempt_id AND g.test_id=NEW.test_id AND g.observation_id=NEW.observation_id AND json_extract(g.payload,'$.scope')=json_extract(NEW.payload,'$.scope') AND o.id=NEW.observation_id AND json_extract(o.payload,'$.observation_hash')=json_extract(NEW.payload,'$.observation_hash') AND p.id=NEW.preparation_id AND p.status='PREPARING' AND p.selection_hash=json_extract(NEW.payload,'$.selection_hash') AND p.browser_mode=json_extract(NEW.payload,'$.browser_mode') AND json_extract(i.value,'$.id')=NEW.item_id AND json_extract(i.value,'$.attempt_id')=NEW.attempt_id AND json_extract(i.value,'$.status')='PREPARING') BEGIN SELECT RAISE(ABORT,'Batch plan requires exact active persisted grounding'); END")
    op.execute("CREATE TRIGGER browser_batch_plans_no_delete BEFORE DELETE ON browser_batch_plans BEGIN SELECT RAISE(ABORT,'Batch provenance is immutable'); END")
    op.execute("CREATE TRIGGER browser_batch_plans_no_update BEFORE UPDATE ON browser_batch_plans BEGIN SELECT RAISE(ABORT,'Batch provenance is immutable'); END")
    op.execute("CREATE TRIGGER batch_runnable_proof BEFORE UPDATE ON browser_preparations WHEN EXISTS (SELECT 1 FROM browser_batch_submissions b WHERE b.preparation_id=NEW.id) AND EXISTS (SELECT 1 FROM json_each(NEW.payload,'$.items') i WHERE json_extract(i.value,'$.status')='RUNNABLE' AND NOT EXISTS (SELECT 1 FROM browser_batch_plans p WHERE p.preparation_id=NEW.id AND p.project_id=NEW.project_id AND p.campaign_id=NEW.campaign_id AND p.item_id=json_extract(i.value,'$.id') AND p.attempt_id=json_extract(i.value,'$.attempt_id') AND p.test_id=json_extract(i.value,'$.original_test_id') AND p.grounding_id=json_extract(i.value,'$.grounding_id') AND p.plan_hash=json_extract(i.value,'$.plan_hash') AND json_extract(p.payload,'$.observation_hash')=json_extract(i.value,'$.observation_hash'))) BEGIN SELECT RAISE(ABORT,'Runnable batch item requires durable plan proof'); END")
    op.create_table("browser_batch_run_items",
        sa.Column("run_test_id",sa.String(36),nullable=False,primary_key=True),
        sa.Column("project_id",sa.String(36),nullable=False),
        sa.Column("campaign_id",sa.String(36),nullable=False),
        sa.Column("run_id",sa.String(36),nullable=False),
        sa.Column("preparation_id",sa.String(36),nullable=False),
        sa.Column("item_id",sa.String(36),nullable=False),
        sa.Column("plan_receipt_id",sa.String(36),nullable=False),
        sa.UniqueConstraint("plan_receipt_id",name="uq_batch_materialized_plan"),
        sa.ForeignKeyConstraint(["run_test_id","run_id","campaign_id","project_id"],["qa_run_tests.id","qa_run_tests.run_id","qa_run_tests.campaign_id","qa_run_tests.project_id"],name="fk_batch_run_item_test",deferrable=True,initially="DEFERRED"),
        sa.ForeignKeyConstraint(["plan_receipt_id","campaign_id","project_id"],["browser_batch_plans.id","browser_batch_plans.campaign_id","browser_batch_plans.project_id"],name="fk_batch_run_item_plan",deferrable=True,initially="DEFERRED"),
    )
    op.execute("CREATE TRIGGER batch_run_item_insert BEFORE INSERT ON browser_batch_run_items WHEN NOT EXISTS (SELECT 1 FROM browser_batch_plans p,qa_run_tests t,qa_runs r WHERE p.id=NEW.plan_receipt_id AND p.project_id=NEW.project_id AND p.campaign_id=NEW.campaign_id AND p.preparation_id=NEW.preparation_id AND p.item_id=NEW.item_id AND t.id=NEW.run_test_id AND t.run_id=NEW.run_id AND t.project_id=NEW.project_id AND t.campaign_id=NEW.campaign_id AND t.original_test_specification_id=p.test_id AND json_extract(t.browser_plan,'$.plan_hash')=p.plan_hash AND r.id=NEW.run_id AND r.preparation_id=NEW.preparation_id) BEGIN SELECT RAISE(ABORT,'Batch Run item must bind the exact sealed plan'); END")
    op.execute("CREATE TRIGGER browser_batch_run_items_no_delete BEFORE DELETE ON browser_batch_run_items BEGIN SELECT RAISE(ABORT,'Batch provenance is immutable'); END")
    op.execute("CREATE TRIGGER browser_batch_run_items_no_update BEFORE UPDATE ON browser_batch_run_items BEGIN SELECT RAISE(ABORT,'Batch provenance is immutable'); END")


def downgrade():
    db=op.get_bind()
    for table in ("browser_batch_submissions","browser_batch_plans","browser_batch_run_items"):
        if db.scalar(sa.text("SELECT count(*) FROM "+table)):raise RuntimeError("0018 downgrade cannot erase browser batch provenance")
    op.execute("DROP TRIGGER batch_runnable_proof")
    op.drop_table("browser_batch_run_items")
    op.drop_table("browser_batch_plans")
    op.drop_table("browser_batch_submissions")
