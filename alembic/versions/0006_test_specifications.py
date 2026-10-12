"""Immutable executor-neutral test imports, generation evidence and traceability."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('uq_campaign_requirements_owner', 'campaign_requirements', ['id', 'campaign_id', 'project_id'], unique=True)
    op.create_table('campaign_test_imports',
        sa.Column('id', sa.String(length=36), primary_key=True, nullable=False),
        sa.Column('project_id', sa.String(length=36), sa.ForeignKey('projects.id', deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('campaign_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('format', sa.String(length=16), nullable=False),
        sa.Column('raw_hash', sa.String(length=64), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('contract_version', sa.String(length=32), nullable=False),
        sa.Column('normalization_version', sa.String(length=32), nullable=False),
        sa.Column('original_bytes', sa.Integer(), nullable=False),
        sa.Column('normalized_text', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('error_code', sa.String(length=32), nullable=True),
        sa.Column('test_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.CheckConstraint('original_bytes BETWEEN 0 AND 65536', name='ck_test_imports_bounds'),
        sa.CheckConstraint("format IN ('CSV','MARKDOWN','XLSX')", name='ck_test_imports_format'),
        sa.CheckConstraint("(status='IMPORTED' AND normalized_text IS NOT NULL AND error_code IS NULL AND test_count BETWEEN 1 AND 100) OR (status='REJECTED' AND normalized_text IS NULL AND error_code IS NOT NULL AND test_count=0)", name='ck_test_imports_status'),
        sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['qa_campaigns.id', 'qa_campaigns.project_id'], name='fk_test_imports_owner', deferrable=True, initially="DEFERRED"),
        sa.UniqueConstraint('campaign_id', 'format', 'content_hash', 'contract_version', name='uq_test_imports_identity'),
        sa.UniqueConstraint('id', 'campaign_id', 'project_id', name='uq_test_imports_owner'))
    op.create_index('ix_test_imports_campaign', 'campaign_test_imports', ['campaign_id', 'created_at', 'id'], unique=False)
    op.create_table('campaign_test_generations',
        sa.Column('id', sa.String(length=36), primary_key=True, nullable=False),
        sa.Column('project_id', sa.String(length=36), sa.ForeignKey('projects.id', deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('campaign_id', sa.String(length=36), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('contract_version', sa.String(length=32), nullable=False),
        sa.Column('requirement_versions', sa.JSON(), nullable=False),
        sa.Column('agent', sa.String(length=16), nullable=False),
        sa.Column('model', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('started_at', sa.Text(), nullable=False),
        sa.Column('finished_at', sa.Text(), nullable=True),
        sa.Column('error_code', sa.String(length=64), nullable=True),
        sa.Column('metadata', sa.JSON(none_as_null=True), nullable=True),
        sa.CheckConstraint("(status='STARTED' AND finished_at IS NULL AND error_code IS NULL AND metadata IS NULL) OR (status='SUCCEEDED' AND finished_at IS NOT NULL AND error_code IS NULL) OR (status='FAILED' AND finished_at IS NOT NULL AND error_code IS NOT NULL)", name='ck_test_generations_lifecycle'),
        sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['qa_campaigns.id', 'qa_campaigns.project_id'], name='fk_test_generations_owner', deferrable=True, initially="DEFERRED"),
        sa.UniqueConstraint('campaign_id', 'request_hash', 'contract_version', name='uq_test_generations_identity'),
        sa.UniqueConstraint('id', 'campaign_id', 'project_id', name='uq_test_generations_owner'))
    op.create_index('ix_test_generations_campaign', 'campaign_test_generations', ['campaign_id', 'started_at', 'id'], unique=False)
    op.create_table('campaign_test_specifications',
        sa.Column('id', sa.String(length=36), primary_key=True, nullable=False),
        sa.Column('project_id', sa.String(length=36), sa.ForeignKey('projects.id', deferrable=True, initially="DEFERRED"), nullable=False),
        sa.Column('campaign_id', sa.String(length=36), nullable=False),
        sa.Column('import_id', sa.String(length=36), nullable=True),
        sa.Column('generation_id', sa.String(length=36), nullable=True),
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('logical_key', sa.String(length=128), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('test_type', sa.String(length=16), nullable=False),
        sa.Column('priority', sa.String(length=16), nullable=False),
        sa.Column('preconditions', sa.JSON(), nullable=False),
        sa.Column('steps', sa.JSON(), nullable=False),
        sa.Column('overall_expected_result', sa.Text(), nullable=True),
        sa.Column('required_evidence', sa.JSON(), nullable=False),
        sa.Column('information_markers', sa.JSON(), nullable=False),
        sa.Column('unresolved_requirement_refs', sa.JSON(), nullable=False),
        sa.Column('provenance', sa.JSON(), nullable=False),
        sa.Column('review_status', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.Text(), nullable=False),
        sa.CheckConstraint('(import_id IS NOT NULL AND generation_id IS NULL) OR (generation_id IS NOT NULL AND import_id IS NULL)', name='ck_test_specifications_origin'),
        sa.CheckConstraint("review_status IN ('DRAFT','NEEDS_CLARIFICATION','READY_FOR_REVIEW')", name='ck_test_specifications_review'),
        sa.ForeignKeyConstraint(['generation_id', 'campaign_id', 'project_id'], ['campaign_test_generations.id', 'campaign_test_generations.campaign_id', 'campaign_test_generations.project_id'], name='fk_test_specifications_generation', deferrable=True, initially="DEFERRED"),
        sa.ForeignKeyConstraint(['import_id', 'campaign_id', 'project_id'], ['campaign_test_imports.id', 'campaign_test_imports.campaign_id', 'campaign_test_imports.project_id'], name='fk_test_specifications_import', deferrable=True, initially="DEFERRED"),
        sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['qa_campaigns.id', 'qa_campaigns.project_id'], name='fk_test_specifications_owner', deferrable=True, initially="DEFERRED"),
        sa.UniqueConstraint('campaign_id', 'logical_key', name='uq_test_specifications_key'),
        sa.UniqueConstraint('import_id', 'key', name='uq_test_specifications_import_key'),
        sa.UniqueConstraint('generation_id', 'key', name='uq_test_specifications_generation_key'),
        sa.UniqueConstraint('id', 'campaign_id', 'project_id', name='uq_test_specifications_owner'))
    op.create_index('ix_test_specifications_campaign', 'campaign_test_specifications', ['campaign_id', 'created_at', 'id'], unique=False)
    op.create_table('campaign_test_requirement_links',
        sa.Column('test_spec_id', sa.String(length=36), primary_key=True, nullable=False),
        sa.Column('requirement_id', sa.String(length=36), primary_key=True, nullable=False),
        sa.Column('project_id', sa.String(length=36), nullable=False),
        sa.Column('campaign_id', sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(['requirement_id', 'campaign_id', 'project_id'], ['campaign_requirements.id', 'campaign_requirements.campaign_id', 'campaign_requirements.project_id'], name='fk_test_links_requirement_owner', deferrable=True, initially="DEFERRED"),
        sa.ForeignKeyConstraint(['test_spec_id', 'campaign_id', 'project_id'], ['campaign_test_specifications.id', 'campaign_test_specifications.campaign_id', 'campaign_test_specifications.project_id'], name='fk_test_links_spec_owner', deferrable=True, initially="DEFERRED"))


def downgrade():
    op.drop_table('campaign_test_requirement_links')
    op.drop_table('campaign_test_specifications')
    op.drop_table('campaign_test_generations')
    op.drop_table('campaign_test_imports')
    op.drop_index('uq_campaign_requirements_owner', table_name='campaign_requirements')
