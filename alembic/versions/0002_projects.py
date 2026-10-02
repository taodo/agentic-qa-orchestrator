"""Explicit task ownership; fixed migration-only backfill for legacy tasks."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

LEGACY_PROJECT_ID = "00000000-0000-4000-8000-000000000011"
LEGACY_PROJECT_KEY = "legacy-bootstrap"


def upgrade():
    op.create_table("projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("key", name="uq_projects_key"))
    op.add_column("tasks", sa.Column("project_id", sa.String(36), nullable=True))
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM tasks")):
        connection.execute(sa.text("INSERT INTO projects (id, key, name, description, created_at, updated_at) "
            "VALUES (:id, :key, 'Legacy bootstrap', 'Migration-only ownership of pre-Task-11 tasks', :time, :time)"),
            dict(id=LEGACY_PROJECT_ID, key=LEGACY_PROJECT_KEY, time="2026-10-02T00:00:00+00:00"))
        connection.execute(sa.text("UPDATE tasks SET project_id = :id"), dict(id=LEGACY_PROJECT_ID))
    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.alter_column("project_id", existing_type=sa.String(36), nullable=False)
        batch.create_foreign_key("fk_tasks_project_id", "projects", ["project_id"], ["id"],
            deferrable=True, initially="DEFERRED")
        batch.create_index("ix_tasks_project_id", ["project_id"])


def downgrade():
    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.drop_index("ix_tasks_project_id")
        batch.drop_constraint("fk_tasks_project_id", type_="foreignkey")
        batch.drop_column("project_id")
    op.drop_table("projects")
