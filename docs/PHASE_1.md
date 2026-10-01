# Phase 1 bootstrap status and assumptions

Task 1 implements the package skeleton, enums, Pydantic domain/agent-output
contracts, validation tests, and initial documentation. Task 1.1 hardens lifecycle,
structured evidence, routing/coverage fields, and record references.

Task 2 implements SQLite persistence with SQLAlchemy ORM, explicit mappers,
repositories, Alembic revision 0001, and UnitOfWork. Task 2.1 repairs the invalid
TaskRepository list method and acceptance criterion identity, adds persistence
unit/integration tests, and verifies migrations and transactions. See DATABASE.md.

Runtime orchestration, gates, retries, escalation, agents, model calls, execution
services, CLI, and UI remain unimplemented. No Task 3 work is included.

Contract hardening:

- Invocations support STARTED, COMPLETED, BLOCKED, FAILED. finished_at is optional
  and defaults to null for every status. No lifecycle transition behavior or
  status/timestamp coupling is enforced. TestRun retains required finished_at.
- Planner steps are structured (id, description, files, depends_on). Acceptance
  criteria require nonblank verification. Test strategy retains acceptance refs.
- Implementation evidence contains step IDs/statuses, file paths/change types/
  reasons, and command text/integer exit codes. Strict integers reject booleans,
  floats, and numeric strings. Exit codes are stored without semantic interpretation.
- Investigation actions have a canonical type and explanatory description;
  routing does not depend on interpreting the description. No routing is implemented.
- Review coverage includes COVERED, NOT_COVERED, or UNVERIFIED for each criterion.
- Event and audit actors use ActorRef (type, id). Actor IDs are nonblank strings
  because agents, tools, systems, and humans may use named identifiers.
- Event correlation uses CorrelationRef with optional invocation_id, artifact_id,
  test_run_id, decision_id UUIDs. ErrorSource carries optional actor, invocation_id,
  and nonblank tool. Empty correlation/source objects are valid; the enclosing
  Event.correlation and ErrorRecord.source fields remain required.
- TestRun replaces status with execution_status (COMPLETED, INCOMPLETE, FAILED)
  and outcome (PASS, FAIL, UNKNOWN). COMPLETED + FAIL represents completed
  execution with failing product tests; FAILED + UNKNOWN represents an execution
  failure without a test conclusion. These are independent contract fields;
  no combinations, counts, or workflow consequences are semantically inferred.

Retained assumptions:

- Enum values use canonical uppercase names. ImplementationStatus remains
  COMPLETED/BLOCKED/FAILED. TestAnalysisOutput uses GateResult for overall_result.
- Attempts start at one; task cycle/attempt counters start at zero.
- External evidence/context refs are nonblank strings; entity IDs are UUIDs.
  Producer and invocation fields are optional on artifacts for deterministic
  producers. Transition gate refs are optional; decision refs are required.
- Output collections, including planner files/dependencies, are required tuples;
  empty collections are valid. No dependency existence, uniqueness, completeness,
  coverage gate, retry policy, or route selection is encoded in Pydantic.
- Root cause may be null. Unknown.blocking and Deviation.requires_replan must
  be present. Stable IDs and descriptive strings are stripped and nonblank.
- Historical records, structured refs, and agent outputs are frozen; Task remains
  a mutable current snapshot. Frozen models do not deeply freeze nested JSON
  dictionaries/lists, and model_copy can construct a new record. Callers must
  not mutate accepted content. Database triggers are not implemented; append-only
  repository APIs enforce the persistence boundary.
- Default timestamps are UTC; supplied datetimes are accepted as given.
  Task timestamps are data only and are not updated automatically.
- Secret handling, authorization, retry bounds, evidence-driven escalation,
  atomic transitions, and resume/idempotency remain architecture requirements
  without implementation in these contracts.

Task 1.1 intentionally rejects former string-only steps, changed files, recorded
commands, investigation actions, actor/source refs, and the removed TestRun.status.
Task 2 persists the hardened contracts; no runtime contract migration is introduced.

Persistence assumptions for Tasks 2/2.1:

- UUIDs use portable string storage, enums retain canonical strings, JSON stores
  structured payloads, and ISO datetime text preserves offsets/microseconds.
- Foreign keys are deferred until commit to support cyclic references.
- Acceptance criterion persistence_id is a UUID; logical id remains a string
  unique within its requirement. Agent-facing IDs are unchanged.
- Explicit commit is required; context exit rolls back uncommitted operations.
- Revision 0001 is unreleased and repaired in place. Existing bootstrap databases
  at that revision must be recreated; this is not a deployed-schema upgrade.

Recommended next step: BOOTSTRAP TASK 3 — State Machine + Gates.
