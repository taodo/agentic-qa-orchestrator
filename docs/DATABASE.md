# Persistence foundation — Tasks 2, 2.1 and 11

Phase 1 persistence is implemented with SQLite, SQLAlchemy 2.x, and Alembic.
It stores records and supports transactions; it does not choose workflow
progression or implement agents, gates, retries, escalation, or execution.

## Boundary and schema

Domain Pydantic contracts remain independent of SQLAlchemy. Explicit functions
in persistence/mappers.py convert each contract to/from ORM rows, validate
contracts at the boundary, and detach nested JSON values to avoid aliasing.
Small frozen persistence records represent Requirement, AcceptanceCriterionRecord,
and FailureFingerprint because these have no existing first-class domain contracts.
Agent-output schemas stay inside artifacts rather than getting separate tables.

Tables: projects, tasks, invocations, artifacts, transitions, gate_evaluations, decisions,
errors, events, audit_records, test_runs, failure_fingerprints, requirements,
acceptance_criteria. Alembic also maintains alembic_version.

UUIDs use canonical 36-character strings, returning UUID objects through mappers.
Enums store their exact canonical strings; domain validation restores enum values.
ISO datetime text preserves supplied timezone offsets, microseconds, and naive
values. No automatic timestamp or workflow-state updates occur.

SQLAlchemy JSON stores artifact content, invocation context refs, gate checks and
blocking reasons, decision evidence refs, error source/evidence refs, event actor/
correlation/payload, and audit actor/metadata. JSON is copied at mapping boundaries.
Null, nested objects, lists, booleans, strings, and finite numbers round-trip;
the configured serializer rejects NaN/Infinity. Audit metadata uses the Python
attribute metadata_json because SQLAlchemy reserves metadata; the column is metadata.

## Acceptance criterion identity

AcceptanceCriterionRecord has persistence_id (UUID primary key), id (logical
nonblank string such as AC-1), requirement_id, text, and verification_method.
A unique constraint on (requirement_id, id) prevents duplicates within one
requirement while allowing AC-1 under other requirements/tasks. Repository get
uses persistence_id; get_by_logical_id requires requirement_id and logical ID.
PlannerOutput acceptance IDs remain strings and are unchanged.

## Repositories and mutability

Task 11 adds ProjectRepository add/get/get_by_key/list/save, with immutable id/key/
created_at and explicit mutable name/description/updated_at. Project keys are unique
and validated without normalization. Task.project_id is mandatory, indexed, FK-backed
and immutable through TaskRepository.save. Evidence stays task-scoped. See PROJECTS.md.

TaskRepository provides add/get/save for the mutable current task snapshot.
InvocationRepository supports add/get/save for lifecycle records, including
STARTED with null finished_at and later COMPLETED with a completion timestamp.
No lifecycle transition policy is encoded in storage.

ArtifactRepository exposes add/get/list_by_task without update/save/delete/remove.
HistoryRepository exposes append/get/list for transitions, gate evaluations,
decisions, errors, events, audits, and test runs. TestRun stores execution_status
and outcome independently. Supersession inserts a new artifact with a reference;
it does not alter earlier content.

Requirements and acceptance criteria have add/get/list APIs. Failure fingerprints
support add/get/list and update_occurrence, changing only occurrence_count and
last_seen_at. They contain caller-supplied fingerprints; no generation or loop
detection is implemented. History immutability is an API boundary, not a database
trigger or protection against callers using SQL/ORM directly.

## Transactions and integrity

create_engine and create_session_factory construct explicit instances; no global
mutable sessions/engines exist. SQLite foreign keys are enabled on every
connection. Foreign keys are deferred to commit to support task/current invocation
and invocation/error cycles in a single transaction. UUID links inside JSON are
not relational foreign keys. Count/attempt checks and primary-key uniqueness are
also enforced by SQLite. Duplicate IDs are rejected rather than silently inserted
again; no orchestrator idempotency framework is added.

UnitOfWork exposes session-scoped repositories. Repository writes flush but never
commit. Call uow.commit() explicitly. Context exit rolls back anything uncommitted
on success or failure and closes the session; uow.rollback() is also available.
SQLite transaction setup issues explicit BEGIN, including for DDL and savepoints.
Future callers can insert related history and save a task within one transaction,
without a workflow-specific transition method.

## Migration and verification

alembic/versions/0001_initial.py is the accepted initial schema migration.
It creates all 13 application tables with explicit columns, foreign keys, checks,
and acceptance identity constraints, independently of current ORM metadata.
Task 2.1 historically repaired the then-unreleased initial migration in place.
Task 11 assumes that accepted 0001 schema, leaves it unchanged, and upgrades it
with revision 0002. Older pre-Task-2.1 schema variants require separate reconciliation.

From the repository root, after installing the project and its test dependencies:

```shell
python -m alembic upgrade head
python -m pytest
```

The default Alembic URL creates qa-sentinel.db in the current directory. Tests
use isolated temporary databases. Unit tests use create_all for fast isolation;
integration tests actually upgrade an empty SQLite file with Alembic, compare
columns/types/nullability, FK targets/options, checks, unique constraints and PKs
against ORM metadata, and verify durable round-trips and foreign-key rejection.
No database payload logging or configuration secrets are added.

Task 11 adds 0002_projects.py without modifying 0001. Online upgrade creates Project
identity and non-null Task ownership, backfilling existing Tasks into one fixed
migration-only legacy-bootstrap Project. Empty databases have no bootstrap row.
Existing task data and incoming cyclic history links survive SQLite batch recreation.
Migration connections temporarily disable FK checks before BEGIN, verify all links
before commit and restore enforcement; normal connections keep enforcement enabled.
Task 11 tests upgraded to 0002 and compared schema/index integrity. See PROJECTS.md for
backfill identity, transaction constraints and runtime binding of migrated Tasks.

## Task 20 execution requests

Additive 0003_execution_jobs follows unchanged 0001/0002. Execution jobs persist
only request identity/ownership, operational status, lifecycle timestamps and fixed
safe error codes. Internal AUTOINCREMENT sequence orders committed queue insertion;
it is absent from DTOs. FK/lifecycle checks and partial unique indexes enforce one
active job per Task and one RUNNING job globally. Application validation proves
Task/Project ownership consistency before enqueue.

Short BEGIN IMMEDIATE job transactions serialize lifecycle writes before reading;
core transaction defaults remain unchanged. No transaction spans model/tool/test
work. Upgrade preserves all Tasks/evidence; downgrade removes only job records.
Tests compare migrated schema with ORM metadata, constraints, reopen durability
and 0002→0003 preservation/downgrade. [Execution jobs](EXECUTION_JOBS.md) defines
restart uncertainty and separate workflow truth.
