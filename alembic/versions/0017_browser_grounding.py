"""Immutable scoped observation and grounding provenance; no execution history."""
from alembic import op
import sqlalchemy as sa
revision="0017"
down_revision="0016"
branch_labels=depends_on=None


def upgrade():
    op.create_table('browser_grounding_observations',
        sa.Column('id',sa.String(36),nullable=False,primary_key=True),
        sa.Column('project_id',sa.String(36),nullable=False),
        sa.Column('campaign_id',sa.String(36),nullable=False),
        sa.Column('preparation_id',sa.String(36),nullable=False),
        sa.Column('item_id',sa.String(36),nullable=False),
        sa.Column('attempt_id',sa.String(36),nullable=False),
        sa.Column('test_id',sa.String(36),nullable=False),
        sa.Column('observed_at',sa.Text(),nullable=False),
        sa.Column('payload',sa.JSON(),nullable=False),

        sa.UniqueConstraint("id", "campaign_id", "project_id", name="uq_browser_grounding_observations_owner"),
        sa.UniqueConstraint("preparation_id", "item_id", "attempt_id", name="uq_browser_grounding_observations_attempt"),
        sa.ForeignKeyConstraint(["preparation_id","campaign_id","project_id"], ["browser_preparations.id","browser_preparations.campaign_id","browser_preparations.project_id"], name="fk_browser_grounding_observations_preparation", deferrable=True, initially="DEFERRED"),
        sa.ForeignKeyConstraint(["test_id","campaign_id","project_id"], ["campaign_test_specifications.id","campaign_test_specifications.campaign_id","campaign_test_specifications.project_id"], name="fk_browser_grounding_observations_test", deferrable=True, initially="DEFERRED"),
        sa.CheckConstraint("json_extract(payload,'$.contract_version') IS 'browser-grounding-observation-v1' AND julianday(json_extract(payload,'$.started_at')) IS NOT NULL AND julianday(json_extract(payload,'$.finished_at')) IS NOT NULL AND julianday(json_extract(payload,'$.finished_at'))>=julianday(json_extract(payload,'$.started_at')) AND julianday(json_extract(payload,'$.finished_at'))=julianday(observed_at) AND json_extract(payload,'$.id') IS id AND json_extract(payload,'$.scope.project_id') IS project_id AND json_extract(payload,'$.scope.campaign_id') IS campaign_id AND json_extract(payload,'$.scope.preparation_id') IS preparation_id AND json_extract(payload,'$.scope.item_id') IS item_id AND json_extract(payload,'$.scope.attempt_id') IS attempt_id AND json_extract(payload,'$.scope.test_id') IS test_id AND length(CAST(payload AS BLOB))<=65536",name="ck_browser_grounding_observations_payload"),
    )
    op.create_table('browser_groundings',
        sa.Column('id',sa.String(36),nullable=False,primary_key=True),
        sa.Column('project_id',sa.String(36),nullable=False),
        sa.Column('campaign_id',sa.String(36),nullable=False),
        sa.Column('preparation_id',sa.String(36),nullable=False),
        sa.Column('item_id',sa.String(36),nullable=False),
        sa.Column('attempt_id',sa.String(36),nullable=False),
        sa.Column('test_id',sa.String(36),nullable=False),
        sa.Column('status',sa.String(24),nullable=False),
        sa.Column('started_at',sa.Text(),nullable=False),
        sa.Column('observation_id',sa.String(36),nullable=True),
        sa.Column('payload',sa.JSON(),nullable=False),

        sa.UniqueConstraint("id", "campaign_id", "project_id", name="uq_browser_groundings_owner"),
        sa.UniqueConstraint("preparation_id", "item_id", "attempt_id", name="uq_browser_groundings_attempt"),
        sa.ForeignKeyConstraint(["preparation_id","campaign_id","project_id"], ["browser_preparations.id","browser_preparations.campaign_id","browser_preparations.project_id"], name="fk_browser_groundings_preparation", deferrable=True, initially="DEFERRED"),
        sa.ForeignKeyConstraint(["test_id","campaign_id","project_id"], ["campaign_test_specifications.id","campaign_test_specifications.campaign_id","campaign_test_specifications.project_id"], name="fk_browser_groundings_test", deferrable=True, initially="DEFERRED"),
        sa.CheckConstraint("json_extract(payload,'$.contract_version') IS 'browser-grounding-v1' AND julianday(json_extract(payload,'$.started_at')) IS NOT NULL AND julianday(json_extract(payload,'$.started_at'))=julianday(started_at) AND ((status='STARTED' AND json_extract(payload,'$.finished_at') IS NULL AND json_extract(payload,'$.output') IS NULL AND json_extract(payload,'$.constraints') IS NULL AND json_extract(payload,'$.reason') IS NULL AND observation_id IS NULL) OR (status!='STARTED' AND julianday(json_extract(payload,'$.finished_at')) IS NOT NULL AND julianday(json_extract(payload,'$.finished_at'))>=julianday(started_at) AND ((status='GROUNDED' AND json_type(payload,'$.output') IS 'object' AND json_type(payload,'$.constraints') IS 'object' AND observation_id IS NOT NULL AND json_extract(payload,'$.reason') IS NULL) OR (status IN ('NEEDS_ATTENTION','SYSTEM_ERROR') AND json_type(payload,'$.reason') IS 'text' AND json_extract(payload,'$.output') IS NULL AND json_extract(payload,'$.constraints') IS NULL)))) AND json_extract(payload,'$.id') IS id AND json_extract(payload,'$.scope.project_id') IS project_id AND json_extract(payload,'$.scope.campaign_id') IS campaign_id AND json_extract(payload,'$.scope.preparation_id') IS preparation_id AND json_extract(payload,'$.scope.item_id') IS item_id AND json_extract(payload,'$.scope.attempt_id') IS attempt_id AND json_extract(payload,'$.scope.test_id') IS test_id AND length(CAST(payload AS BLOB))<=131072 AND status IN ('STARTED','GROUNDED','NEEDS_ATTENTION','SYSTEM_ERROR') AND json_extract(payload,'$.status') IS status AND json_extract(payload,'$.observation_id') IS observation_id",name="ck_browser_groundings_payload"),
        sa.ForeignKeyConstraint(["observation_id","campaign_id","project_id"], ["browser_grounding_observations.id","browser_grounding_observations.campaign_id","browser_grounding_observations.project_id"], name="fk_browser_grounding_observation", deferrable=True, initially="DEFERRED"),
    )
    op.execute("CREATE TRIGGER browser_grounding_active_attempt BEFORE INSERT ON browser_groundings WHEN NEW.status!='STARTED' OR NOT EXISTS (SELECT 1 FROM browser_preparations p,json_each(p.payload,'$.items') i WHERE p.id=NEW.preparation_id AND p.project_id=NEW.project_id AND p.campaign_id=NEW.campaign_id AND p.status='PREPARING' AND json_extract(i.value,'$.id')=NEW.item_id AND json_extract(i.value,'$.attempt_id')=NEW.attempt_id AND json_extract(i.value,'$.original_test_id')=NEW.test_id AND json_extract(i.value,'$.status')='PREPARING' AND json_extract(i.value,'$.test_hash')=json_extract(NEW.payload,'$.scope.test_hash')) BEGIN SELECT RAISE(ABORT,'Grounding requires active owned preparation attempt'); END")
    op.execute("CREATE TRIGGER browser_grounding_observation_attempt BEFORE INSERT ON browser_grounding_observations WHEN NOT EXISTS (SELECT 1 FROM browser_groundings g WHERE g.project_id=NEW.project_id AND g.campaign_id=NEW.campaign_id AND g.preparation_id=NEW.preparation_id AND g.item_id=NEW.item_id AND g.attempt_id=NEW.attempt_id AND g.status='STARTED' AND json_extract(g.payload,'$.scope')=json_extract(NEW.payload,'$.scope')) BEGIN SELECT RAISE(ABORT,'Observation requires the exact started grounding attempt'); END")
    op.execute("CREATE TRIGGER browser_grounding_seal BEFORE UPDATE ON browser_groundings WHEN OLD.status!='STARTED' OR NEW.status NOT IN ('GROUNDED','NEEDS_ATTENTION','SYSTEM_ERROR') OR NEW.id!=OLD.id OR NEW.project_id!=OLD.project_id OR NEW.campaign_id!=OLD.campaign_id OR NEW.preparation_id!=OLD.preparation_id OR NEW.item_id!=OLD.item_id OR NEW.attempt_id!=OLD.attempt_id OR NEW.test_id!=OLD.test_id OR NEW.started_at!=OLD.started_at OR json_remove(NEW.payload,'$.status','$.finished_at','$.observation_id','$.observation_hash','$.intent_hash','$.output','$.constraints','$.metadata','$.reason','$.affected_step','$.browser_error_code')!=json_remove(OLD.payload,'$.status','$.finished_at','$.observation_id','$.observation_hash','$.intent_hash','$.output','$.constraints','$.metadata','$.reason','$.affected_step','$.browser_error_code') OR (NEW.observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM browser_grounding_observations o WHERE o.id=NEW.observation_id AND o.project_id=NEW.project_id AND o.campaign_id=NEW.campaign_id AND o.preparation_id=NEW.preparation_id AND o.item_id=NEW.item_id AND o.attempt_id=NEW.attempt_id AND json_extract(o.payload,'$.scope')=json_extract(NEW.payload,'$.scope') AND json_extract(o.payload,'$.observation_hash')=json_extract(NEW.payload,'$.observation_hash'))) BEGIN SELECT RAISE(ABORT,'Grounding inputs/terminal history are immutable'); END")
    op.execute("CREATE TRIGGER browser_grounding_no_delete BEFORE DELETE ON browser_groundings BEGIN SELECT RAISE(ABORT,'Grounding history is immutable'); END")
    op.execute("CREATE TRIGGER browser_grounding_observation_no_update BEFORE UPDATE ON browser_grounding_observations BEGIN SELECT RAISE(ABORT,'Observation history is immutable'); END")
    op.execute("CREATE TRIGGER browser_grounding_observation_no_delete BEFORE DELETE ON browser_grounding_observations BEGIN SELECT RAISE(ABORT,'Observation history is immutable'); END")


def downgrade():
    db=op.get_bind()
    if db.scalar(sa.text("SELECT count(*) FROM browser_groundings")) or db.scalar(sa.text("SELECT count(*) FROM browser_grounding_observations")):
        raise RuntimeError("0017 downgrade cannot erase grounding/observation history")
    op.drop_table("browser_groundings")
    op.drop_table("browser_grounding_observations")
