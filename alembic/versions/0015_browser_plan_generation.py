"""Durable bounded generation candidates and explicit acceptance receipts."""
from alembic import op
import sqlalchemy as sa
revision='0015'
down_revision='0014'
branch_labels=depends_on=None

def upgrade():
    op.create_table('browser_plan_generations',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('project_id',sa.String(36),nullable=False),sa.Column('campaign_id',sa.String(36),nullable=False),
        sa.Column('test_id',sa.String(36),nullable=False),sa.Column('target_id',sa.String(36),nullable=False),sa.Column('previous_id',sa.String(36)),
        sa.Column('status',sa.String(16),nullable=False),sa.Column('started_at',sa.Text(),nullable=False),sa.Column('payload',sa.JSON(),nullable=False),
        sa.UniqueConstraint('id','campaign_id','project_id',name='uq_browser_generation_owner'),sa.UniqueConstraint('previous_id',name='uq_browser_generation_retry'),
        sa.ForeignKeyConstraint(['test_id','campaign_id','project_id'],['campaign_test_specifications.id','campaign_test_specifications.campaign_id','campaign_test_specifications.project_id'],name='fk_browser_generation_test',deferrable=True,initially='DEFERRED'),
        sa.ForeignKeyConstraint(['target_id','project_id'],['targets_under_test.id','targets_under_test.project_id'],name='fk_browser_generation_target',deferrable=True,initially='DEFERRED'),
        sa.ForeignKeyConstraint(['previous_id','campaign_id','project_id'],['browser_plan_generations.id','browser_plan_generations.campaign_id','browser_plan_generations.project_id'],name='fk_browser_generation_retry',deferrable=True,initially='DEFERRED'),
        sa.CheckConstraint("status IN ('STARTED','SUCCEEDED','FAILED') AND json_extract(payload,'$.status')=status AND length(payload)<=1048576",name='ck_browser_generation_payload'))
    op.create_index('ix_browser_generation_owner','browser_plan_generations',['project_id','campaign_id','started_at','id'])
    op.create_table('browser_plan_acceptances',sa.Column('generation_id',sa.String(36),primary_key=True),sa.Column('project_id',sa.String(36),nullable=False),sa.Column('campaign_id',sa.String(36),nullable=False),
        sa.Column('run_id',sa.String(36),nullable=False),sa.Column('run_test_id',sa.String(36),nullable=False),sa.Column('plan_hash',sa.String(64),nullable=False),sa.Column('accepted_at',sa.Text(),nullable=False),
        sa.ForeignKeyConstraint(['generation_id','campaign_id','project_id'],['browser_plan_generations.id','browser_plan_generations.campaign_id','browser_plan_generations.project_id'],name='fk_browser_acceptance_generation',deferrable=True,initially='DEFERRED'),
        sa.ForeignKeyConstraint(['run_id','campaign_id','project_id'],['qa_runs.id','qa_runs.campaign_id','qa_runs.project_id'],name='fk_browser_acceptance_run',deferrable=True,initially='DEFERRED'),
        sa.ForeignKeyConstraint(['run_test_id'],['qa_run_tests.id'],deferrable=True,initially='DEFERRED'),sa.UniqueConstraint('run_test_id',name='uq_browser_acceptance_test'),sa.UniqueConstraint('run_id',name='uq_browser_acceptance_run'))
    # Fixed migration SQL, independent of future model revisions.
    fields="'$.status','$.finished_at','$.error_code','$.metadata','$.output','$.plan_hash'"
    op.execute("CREATE TRIGGER browser_generation_seal BEFORE UPDATE ON browser_plan_generations WHEN OLD.status!='STARTED' OR NEW.status NOT IN ('SUCCEEDED','FAILED') OR NEW.id!=OLD.id OR NEW.project_id!=OLD.project_id OR NEW.campaign_id!=OLD.campaign_id OR NEW.test_id!=OLD.test_id OR NEW.target_id!=OLD.target_id OR NEW.previous_id IS NOT OLD.previous_id OR NEW.started_at!=OLD.started_at OR "
        f"json_remove(NEW.payload,{fields})!=json_remove(OLD.payload,{fields}) BEGIN SELECT RAISE(ABORT,'Planning history is immutable'); END")
    for table in ('browser_plan_generations','browser_plan_acceptances'):
        op.execute(f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'Planning history is immutable'); END")
    op.execute("CREATE TRIGGER browser_acceptance_seal BEFORE UPDATE ON browser_plan_acceptances BEGIN SELECT RAISE(ABORT,'Acceptance is immutable'); END")

def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM browser_plan_generations')) or op.get_bind().scalar(sa.text('SELECT count(*) FROM browser_plan_acceptances')):
        raise RuntimeError('0015 downgrade cannot erase browser planning history')
    op.drop_table('browser_plan_acceptances');op.drop_table('browser_plan_generations')
