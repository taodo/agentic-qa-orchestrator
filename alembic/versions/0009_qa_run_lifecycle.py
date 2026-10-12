"""Safe execution failure code; snapshot payloads are unchanged."""
from alembic import op
import sqlalchemy as sa
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("qa_runs") as batch:
        batch.add_column(sa.Column("execution_error_code", sa.String(32), nullable=True))
        batch.create_check_constraint("ck_qa_runs_error", "execution_error_code IS NULL OR execution_error_code='RUN_EXECUTION_FAILED'")


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM qa_runs WHERE execution_status != 'CREATED' OR execution_error_code IS NOT NULL")):
        raise RuntimeError("0009 downgrade cannot erase execution lifecycle evidence")
    with op.batch_alter_table("qa_runs") as batch:
        batch.drop_constraint("ck_qa_runs_error", type_="check")
        batch.drop_column("execution_error_code")
