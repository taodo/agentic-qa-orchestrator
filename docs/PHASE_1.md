# Task 1 scope and assumptions

Implemented: package skeleton, core enums, domain contracts, agent-output
schemas, structural validation, and unit tests. SQLAlchemy, Alembic, databases,
runtime orchestration, gates, execution tools, CLI, model calls, and prompts
are outside Task 1. Empty packages reserve the specified structure only.

Small implementation assumptions where the specification leaves details open:

- Enum values use the canonical uppercase names. Additional contract enums are
  PlannerDecision, ImplementationStatus (COMPLETED/BLOCKED/FAILED),
  FailureClassification, ReviewIssueSeverity, and TestRunStatus
  (PASSED/FAILED/BLOCKED). TestAnalysisOutput uses GateResult for overall_result.
- Invocation and TestRun represent finished records; finished_at is required.
  Attempts start at one; task cycle/attempt counters start at zero.
- References to external evidence/context are nonblank strings; entity IDs and
  event correlation are UUIDs. Producer and invocation fields are optional on
  artifacts to support deterministic producers. Gate references are optional
  on transitions; a decision reference is required.
- Output collections are required tuples, allowing empty collections while
  keeping their presence explicit. Plan steps and recorded commands are text;
  commands are never executed by these contracts. Coverage items reference
  acceptance IDs and carry explanatory text and evidence references.
- Root cause may be null. Unknown.blocking and Deviation.requires_replan must
  be present. Stable IDs are nonblank, stripped strings; cross-record uniqueness,
  completeness, and coverage belong to later gates.
- Artifact content, event payload, and audit metadata accept JSON values.
  Models reject extra fields. Historical records and output models are frozen;
  tuples protect structured collections. Frozen models do not deeply freeze
  nested JSON dictionaries/lists, and model_copy can construct a new record.
  Callers must not mutate accepted content. Database immutability is deferred.
- Default timestamps are UTC; supplied datetimes are accepted as given.
  Task timestamps are data only and are not updated automatically.
- Secret handling, authorization, retry bounds, evidence-driven escalation,
  atomic transitions, and resume/idempotency are architecture requirements,
  not enforcement implemented by these contracts.

Recommended next step: BOOTSTRAP TASK 2 — Persistence foundation.
