"""Durable, immutable, exact-scope advisory experience and source bindings."""
from alembic import op
import sqlalchemy as sa
revision = "0019"
down_revision = "0018"
branch_labels = depends_on = None


def upgrade():
    op.create_table("experiences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("target_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("freshness_seconds", sa.Integer, nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.UniqueConstraint('id', 'campaign_id', 'project_id', name='uq_experience_owner'),
        sa.UniqueConstraint('campaign_id', 'idempotency_key', name='uq_experience_idempotency'),
        sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['qa_campaigns.id', 'qa_campaigns.project_id'], name='fk_experience_campaign', deferrable=True, initially='DEFERRED'),
        sa.ForeignKeyConstraint(['target_id', 'project_id'], ['targets_under_test.id', 'targets_under_test.project_id'], name='fk_experience_target', deferrable=True, initially='DEFERRED'),
        sa.CheckConstraint("state IN ('CANDIDATE','VALIDATED','PROMOTED','SUPERSEDED','RETIRED')", name='ck_experience_state'),
        sa.CheckConstraint("kind IN ('EVIDENCE_COMPLETENESS','PLAN_SEPARATION','FRESHNESS_PRECONDITION','QA_FAIL_CLASSIFICATION','APPROVAL_PROVENANCE')", name='ck_experience_kind'),
        sa.CheckConstraint('length(content_hash)=64 AND length(target_snapshot_hash)=64 AND length(idempotency_key)=36 AND freshness_seconds BETWEEN 1 AND 7776000', name='ck_experience_bounds'),
        sa.CheckConstraint('julianday(created_at) IS NOT NULL AND julianday(expires_at)>julianday(created_at) AND length(CAST(payload AS BLOB))<=8192', name='ck_experience_times'),
        sa.CheckConstraint("json_extract(payload,'$.schema_version') IS 'experience-v1' AND json_extract(payload,'$.id') IS id AND json_extract(payload,'$.scope.project_id') IS project_id AND json_extract(payload,'$.scope.campaign_id') IS campaign_id AND json_extract(payload,'$.scope.target_id') IS target_id AND json_extract(payload,'$.scope.target_snapshot_hash') IS target_snapshot_hash AND json_extract(payload,'$.state') IS state AND json_extract(payload,'$.kind') IS kind AND json_extract(payload,'$.idempotency_key') IS idempotency_key AND json_extract(payload,'$.content_hash') IS content_hash AND json_extract(payload,'$.freshness_seconds') IS freshness_seconds AND json_array_length(payload,'$.references') BETWEEN 1 AND 4", name='ck_experience_payload'),
    )
    op.create_index('ix_experience_scope', 'experiences', ['project_id', 'campaign_id', 'target_id', 'target_snapshot_hash', 'id'])
    op.create_table("experience_sources",
        sa.Column("experience_id", sa.String(36), primary_key=True),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("evidence_id", sa.String(36), sa.ForeignKey('qa_run_evidence.id', name='fk_experience_source_evidence', deferrable=True, initially='DEFERRED'), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("run_test_id", sa.String(36), nullable=False),
        sa.UniqueConstraint('experience_id', 'evidence_id', name='uq_experience_source'),
        sa.ForeignKeyConstraint(['experience_id', 'campaign_id', 'project_id'], ['experiences.id', 'experiences.campaign_id', 'experiences.project_id'], name='fk_experience_source_owner', deferrable=True, initially='DEFERRED'),
        sa.ForeignKeyConstraint(['run_test_id', 'run_id', 'campaign_id', 'project_id'], ['qa_run_tests.id', 'qa_run_tests.run_id', 'qa_run_tests.campaign_id', 'qa_run_tests.project_id'], name='fk_experience_source_test', deferrable=True, initially='DEFERRED'),
        sa.CheckConstraint('position BETWEEN 1 AND 4', name='ck_experience_source_position'),
    )
    op.execute("CREATE TRIGGER experience_source_insert BEFORE INSERT ON experience_sources WHEN NOT EXISTS (SELECT 1 FROM experiences x,qa_run_evidence e,json_each(x.payload,'$.references') r WHERE x.id=NEW.experience_id AND x.campaign_id=NEW.campaign_id AND x.project_id=NEW.project_id AND e.id=NEW.evidence_id AND e.run_id=NEW.run_id AND e.run_test_id=NEW.run_test_id AND e.campaign_id=NEW.campaign_id AND e.project_id=NEW.project_id AND CAST(r.key AS INTEGER)=NEW.position-1 AND json_extract(r.value,'$.source_type')='QA_RUN_EVIDENCE' AND json_extract(r.value,'$.evidence_id')=NEW.evidence_id AND json_extract(r.value,'$.run_id')=NEW.run_id AND json_extract(r.value,'$.run_test_id')=NEW.run_test_id) BEGIN SELECT RAISE(ABORT,'Experience source identity mismatch'); END")
    op.execute("CREATE TRIGGER experiences_no_update BEFORE UPDATE ON experiences BEGIN SELECT RAISE(ABORT,'Experience history is immutable'); END")
    op.execute("CREATE TRIGGER experiences_no_delete BEFORE DELETE ON experiences BEGIN SELECT RAISE(ABORT,'Experience history is immutable'); END")
    op.execute("CREATE TRIGGER experience_sources_no_update BEFORE UPDATE ON experience_sources BEGIN SELECT RAISE(ABORT,'Experience history is immutable'); END")
    op.execute("CREATE TRIGGER experience_sources_no_delete BEFORE DELETE ON experience_sources BEGIN SELECT RAISE(ABORT,'Experience history is immutable'); END")


def downgrade():
    db = op.get_bind()
    if db.scalar(sa.text("SELECT count(*) FROM experiences")) or db.scalar(sa.text("SELECT count(*) FROM experience_sources")):
        raise RuntimeError("0019 downgrade cannot erase Experience history")
    op.drop_table("experience_sources")
    op.drop_table("experiences")
