from alembic import context
from qa_sentinel.persistence.database import create_engine
from qa_sentinel.persistence.models import Base

config = context.config


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"),
                      target_metadata=Base.metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def migrate(connection):
    # SQLite batch recreation replaces tasks, which has incoming cyclic FKs.
    # Disable checks only on this migration connection before BEGIN, then verify
    # every reference inside the migration transaction before committing.
    if connection.in_transaction():
        raise RuntimeError("SQLite migrations require a connection outside a transaction")
    raw = connection.connection.driver_connection
    raw.execute("PRAGMA foreign_keys=OFF")
    context.configure(connection=connection, target_metadata=Base.metadata,
                      render_as_batch=True, compare_type=True, transactional_ddl=True)
    try:
        with context.begin_transaction():
            context.run_migrations()
            if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
                raise RuntimeError("Migration foreign-key integrity check failed")
    finally:
        raw.execute("PRAGMA foreign_keys=ON")


def run_migrations_online():
    connection = config.attributes.get("connection")
    if connection is not None:
        migrate(connection)
        return
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        with engine.connect() as connection:
            migrate(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
