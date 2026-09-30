# Persistence boundary

Phase 1 will use SQLite + SQLAlchemy + Alembic.
Task 1 contains no database code, ORM models, migrations, or persistence logic.

Conceptual entities are Task, Artifact, AgentInvocation, DecisionRecord,
ErrorRecord, GateEvaluation (with structured checks), Transition, Event,
AuditRecord, and TestRun. UUID references express relationships without querying
or enforcing referential integrity. Artifacts can supersede earlier artifacts
without updating them. Accepted artifacts/history must remain immutable;
transitions must eventually be atomic and persistent execution must support
safe resume/idempotency. No table layout or migration design is specified here.
