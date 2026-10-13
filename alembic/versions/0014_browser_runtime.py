"""Immutable execution identity and sealed per-test plans; preserve synthetic history."""
from alembic import op
import sqlalchemy as sa
revision = "0014"
down_revision = "0013"
branch_labels = depends_on = None


def upgrade():
    op.add_column("qa_runs", sa.Column("executor_kind",sa.String(16),nullable=False,server_default="SYNTHETIC"))
    op.add_column("qa_runs", sa.Column("runtime_identity",sa.JSON(none_as_null=True),nullable=True))
    op.add_column("qa_runs", sa.Column("browser_error_code",sa.String(40),nullable=True))
    op.add_column("qa_run_tests", sa.Column("browser_plan",sa.JSON(none_as_null=True),nullable=True))
    op.execute("CREATE TRIGGER qa_runs_executor_seal BEFORE UPDATE OF executor_kind,runtime_identity ON qa_runs BEGIN SELECT RAISE(ABORT, 'Execution seal is immutable'); END")
    op.execute("CREATE TRIGGER qa_run_tests_executor_seal BEFORE UPDATE OF browser_plan ON qa_run_tests BEGIN SELECT RAISE(ABORT, 'Execution seal is immutable'); END")


def downgrade():
    db=op.get_bind()
    if (db.scalar(sa.text("SELECT count(*) FROM qa_runs WHERE executor_kind!='SYNTHETIC' OR runtime_identity IS NOT NULL OR browser_error_code IS NOT NULL")) or
            db.scalar(sa.text("SELECT count(*) FROM qa_run_tests WHERE browser_plan IS NOT NULL"))):
        raise RuntimeError("0014 downgrade cannot erase browser execution history")
    # SQLite batch column removal rebuilds tables: preserve every pre-existing trigger.
    preserved=list(db.execute(sa.text("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name IN ('qa_runs','qa_run_tests') AND name NOT IN ('qa_runs_executor_seal','qa_run_tests_executor_seal')")))
    op.execute("DROP TRIGGER qa_run_tests_executor_seal")
    op.execute("DROP TRIGGER qa_runs_executor_seal")
    with op.batch_alter_table("qa_run_tests") as batch: batch.drop_column("browser_plan")
    with op.batch_alter_table("qa_runs") as batch:
        batch.drop_column("browser_error_code")
        batch.drop_column("runtime_identity")
        batch.drop_column("executor_kind")

    for name,ddl in preserved:
        if not db.scalar(sa.text("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name=:name"),{"name":name}):
            op.execute(ddl)
