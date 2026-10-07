
from alembic import command
from sqlalchemy import inspect, text
from qa_sentinel.persistence.database import create_engine
from qa_sentinel.persistence.models import Base


EXPECTED={"qa_campaigns","execution_jobs","projects","tasks","invocations","artifacts","transitions","gate_evaluations","decisions",
          "errors","events","audit_records","test_runs","failure_fingerprints",
          "requirements","acceptance_criteria"}


def schema_signature(engine):
    inspector=inspect(engine)
    result={}
    for name in sorted(EXPECTED):
        columns=sorted((c["name"],str(c["type"]),c["nullable"],c["default"])
                 for c in inspector.get_columns(name))
        foreign_keys=sorted((tuple(f["constrained_columns"]),f["referred_table"],
                             tuple(f["referred_columns"]),tuple(sorted(f["options"].items())))
                            for f in inspector.get_foreign_keys(name))
        checks=sorted((c["name"],c["sqltext"]) for c in inspector.get_check_constraints(name))
        unique=sorted((u["name"],tuple(u["column_names"])) for u in inspector.get_unique_constraints(name))
        result[name]=(columns,foreign_keys,checks,unique,inspector.get_pk_constraint(name)["constrained_columns"])
    return result


def test_fresh_upgrade_tables_revision_and_schema_match(migrated_factory):
    factory,engine,config=migrated_factory
    assert set(inspect(engine).get_table_names())==EXPECTED|{"alembic_version"}
    with engine.connect() as connection:
        assert connection.scalar(text("select version_num from alembic_version"))=="0004"
    reference=create_engine()
    try:
        Base.metadata.create_all(reference)
        assert schema_signature(engine)==schema_signature(reference)
    finally:reference.dispose()
    command.upgrade(config,"head")
    assert set(inspect(engine).get_table_names())==EXPECTED|{"alembic_version"}


def test_initial_downgrade_then_upgrade_is_reproducible(migrated_factory):
    factory,engine,config=migrated_factory
    command.downgrade(config,"base")
    assert not set(inspect(engine).get_table_names()) & EXPECTED
    command.upgrade(config,"head")
    assert set(inspect(engine).get_table_names())==EXPECTED|{"alembic_version"}
