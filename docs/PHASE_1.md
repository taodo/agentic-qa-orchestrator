# Task 1 and Task 1.1 scope and assumptions

Implemented: package skeleton, core enums, domain contracts, agent-output
schemas, structural validation, and unit tests. Task 1.1 hardens these contracts.
SQLAlchemy, Alembic, databases, runtime orchestration, gates, execution tools,
CLI, model calls, and prompts remain outside scope. Empty packages reserve the
specified structure only.

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
  not mutate accepted content. Database immutability remains deferred.
- Default timestamps are UTC; supplied datetimes are accepted as given.
  Task timestamps are data only and are not updated automatically.
- Secret handling, authorization, retry bounds, evidence-driven escalation,
  atomic transitions, and resume/idempotency remain architecture requirements
  without implementation in these contracts.

Task 1.1 intentionally rejects former string-only steps, changed files, recorded
commands, investigation actions, actor/source refs, and the removed TestRun.status.
No persistence or runtime migration is introduced.

Recommended next step: BOOTSTRAP TASK 2 — Persistence foundation.
