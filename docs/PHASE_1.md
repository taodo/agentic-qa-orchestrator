# Phase 1 bootstrap status and assumptions

Task 1 implements the package skeleton, enums, Pydantic domain/agent-output
contracts, validation tests, and initial documentation. Task 1.1 hardens lifecycle,
structured evidence, routing/coverage fields, and record references.

Task 2 implements SQLite persistence with SQLAlchemy ORM, explicit mappers,
repositories, Alembic revision 0001, and UnitOfWork. Task 2.1 repairs the invalid
TaskRepository list method and acceptance criterion identity, adds persistence
unit/integration tests, and verifies migrations and transactions. See DATABASE.md.

Task 3 implements the canonical state machine, seven deterministic gate evaluators,
and WorkflowEngine atomic transition persistence with decisions/events, forward
PASS-gate requirements, terminal protection, and BLOCKED resume handling. See
STATE_MACHINE.md for exact rules and contract assumptions.

Task 4 implements deterministic failure dispositions, per-domain retry budgets,
structured retry/block recommendations, normalized fingerprints and circuit
breaking, defect-cycle checks, and Investigator-only model escalation policy.
ReliabilityService atomically records decisions/events and fingerprint occurrences;
committed scheduling events track retry/escalation reservations without changing
workflow state. See RELIABILITY.md for defaults, attempt semantics, and audit behavior.

Task 5 adds a bounded single-task WorkflowRunner, typed agent contexts, deterministic
scenario-driven fake agents, and a separate fake TestRun provider. It persists
invocation lifecycles and new immutable artifacts, uses existing gates/WorkflowEngine
for progression, and integrates durable retries, circuit breaking, and defect budgets.
Happy-path and repair/retest workflows complete on migrated SQLite. See RUNTIME.md
for lifecycle, recovery boundaries, and graph-preserving safety stops.

Task 6 adds policy-controlled local Python/pytest execution, canonical cwd/target
boundaries, controlled child environment, finite timeout and process-tree cleanup,
bounded output, and built-in JUnit counts without new dependencies. TestExecutionService
persists started reservations and atomic completion evidence; WorkflowRunner accepts
real or fake providers and applies durable TEST_EXECUTION retries to eligible system
failures. Product FAIL still routes to analysis. See EXECUTION.md for exact policy and
the unchanged TESTING stop limitation.

Task 7 implements Researcher/Planner model calls; Task 8 adds real Test Analyzer,
Investigator and Reviewer. Task 9 adds real Implementer proposals and deterministic
controlled mutation. Task 10 adds read-only repository evidence for Researcher and
Planner. A general permission engine, CLI, UI and workers remain unimplemented.
Models never directly edit source.

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
  routing does not depend on interpreting the description. Task 5 routes on its enum.
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
  the contracts infer no combinations or workflow consequences. Task 3 TestGate
  uses execution_status and outcome for deterministic gate results.

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
- Secret handling, authorization, and full runtime idempotency remain architecture
  requirements beyond the contracts. Task 4 adds retry bounds and escalation policy. Task 3
  implements atomic transitions and stored BLOCKED resume targets.

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
- Revision 0001 was historically repaired during Task 2.1. Task 11 leaves the
  accepted revision unchanged and adds 0002 to upgrade existing accepted databases.

Task 3 assumptions:

- NEEDS_RESEARCH is PlanGate FAIL for readiness; structured failing analysis can
  PASS AnalysisGate for sufficiency. Insufficient investigation with explicit
  additional_evidence_needed can PASS for research routing, not root-cause proof.
- Required SKIPPED steps fail because existing data cannot associate a justification
  with a particular step without interpreting prose. General dependency cycles
  are not evaluated; direct self-dependency and missing refs are rejected.
- Only five forward edges mandate PASS gates. Other routes accept relevant optional
  evaluations; the caller requests the route. Approved plans/gate provenance are
  trusted caller inputs, not a new permission or agent-runtime API.
- Gate IDs use transition/decision links because CorrelationRef lacks a gate field.
- Task timestamps may tie; no sequence column is added.

Task 4 assumptions:

- Retry budgets count scheduled retries, excluding the initial execution.
- Committed events track reservations independently per task/domain; runtime
  implementation_attempt/review_cycle counters are not changed by scheduling.
- Defect-cycle checks are pure; Task 4 itself adds no runtime counter increment.
- Reliability events record recommendations/reservations, marked explicitly in
  payloads. Actual blocking/resume uses WorkflowEngine.
- Execution idempotency and concurrent worker scheduling remain future runtime work.

Task 5 assumptions:

- Fake scenario sequences use persisted per-role attempts; contexts contain bounded
  accepted evidence, never mutable Task or persistence handles.
- Actual fake Implementer/Reviewer calls increment implementation_attempt/review_cycle;
  starting a defect repair increments defect_cycle atomically with its transition.
- Schema retries require explicit changed-input/evidence scenario metadata.
- Unsupported BLOCKED edges record errors/recommendations and raise RunnerStoppedError;
  no graph edges are invented. Full crash reconciliation/concurrent runtime is deferred.
- All implementation reports and test results are synthetic; no source/tool execution.

Task 6 assumptions:

- Prepared workspace tests/conftest are trusted Python code; command policy is not
  an OS sandbox. Interpreter/dependency paths are trusted configuration.
- Built-in pytest JUnit reporting supplies counts; invalid/missing/oversized reports
  produce conservative zero counts with explicit reliability metadata.
- Raw output/environment values are not persisted; no new dependency or schema is added.
- Started execution without a completed TestRun requires explicit reconciliation.
- TESTING cannot enter BLOCKED; denied/exhausted recovery records evidence and raises
  RunnerStoppedError without routing infrastructure failures to product analysis.

Task 7 provides a provider-neutral model boundary, the official OpenAI Responses
API adapter, native structured-output parsing with repeated contract validation,
bounded deterministic prompts, and real Researcher/Planner. Explicit composite
routing keeps all other roles fake. Calls have no tools or provider conversation
state. SDK retries are disabled; existing reliability owns application retries.
One explicit schema correction adds instructions to the next reserved invocation;
repeat malformed output without further changed input stops safely.
Configured model/reasoning/attempt/timestamps remain on AgentInvocation; safe usage,
response ID, and latency metadata use existing correlated events, without migration.
The only new direct dependency is the official OpenAI SDK. Offline tests require no
key and use actual SDK mock transport. The real API smoke is developer-only and
was not run. See MODELS.md for boundaries, configuration, and limitations.

Task 8 extends reasoning-only role configuration/prompts/context serialization for
classification, RCA, and independent review using existing typed outputs. It connects
Task 4 Investigator escalation to explicit separate persisted invocations and immutable
artifacts without changing thresholds, budgets, state-machine edges, or gates.
Durable MODEL_ESCALATED evidence selects the configured model and survives restart;
successful escalated output is the selected routing candidate. No hidden fallback
or provider retry is added. All-fake workflows remain compatible.
Prepared fixture code switches independently of fake Implementer to prove real
pytest failure/fix/retest with mocked real reasoning. ReviewGate rejects insufficient
APPROVE coverage; HUMAN_ACTION blocks through WorkflowEngine. No dependency or
migration is added, no real API smoke is run, and no model receives tools.

Task 9 adds frozen source/proposal contracts, configurable real Implementer, bounded
plan-authorized UTF-8 snapshots, complete-set mutation policy, CREATE/MODIFY apply,
SHA-256 stale protection, rollback and explicit persistence reconciliation stops.
The minimal IMPLEMENTATION_PROPOSAL artifact is separate from canonical actual-file
evidence; existing database string storage needs no migration. No model tools,
new dependency, Git rollback, shell mutation or state-machine/gate/reliability change
is added. Fake Implementer stays compatible. Temporary-workspace integration applies
the actual first implementation and repair, running real pytest FAIL then PASS and
real mocked review through ReviewGate. No fixture switches source for repair.

Task 9 assumptions: trusted exclusive target access; existing parent directories;
UTF-8 exact-byte newline preservation; same-directory hardlink support for exclusive
CREATE; practical mode preservation for MODIFY; caller-selected source excludes
secrets; model character/token limits apply in addition to filesystem byte limits.
Filesystem/DB completion is not distributed atomic: unresolved STARTED requires
manual reconciliation and process death may lose original in-memory backups.
Portable filesystem checks have TOCTOU limits, not hostile-code sandbox guarantees.
See MUTATION.md for full policy, error mapping and recovery boundaries.

Task 10 adds optional Researcher/Planner repository evidence through typed structured
turns, independent read authorization and bounded local LIST_FILES/READ_FILE/
SEARCH_TEXT. The Responses adapter has no native tools. Intermediate evidence and
per-turn metadata are persisted separately from final Research/Plan artifacts, with
safe result reuse and explicit unresolved-provider reconciliation on restart.
Investigator tooling is deferred; Implementer snapshots/mutation and Reviewer
supplied-evidence boundaries remain unchanged. No dependencies, gates, state edges,
reliability thresholds or budgets change. Temporary-workspace tests cover discovery,
citations, Planner reads/NEEDS_RESEARCH, read limits, denied paths, drift, restart,
zero read-service mutation and existing Task 9 real mutation/pytest/review.

Task 10 assumes a trusted caller-selected repository, no concurrent runners or
hostile filesystem mutation, and portable path-check TOCTOU limitations. Obvious
secret paths are protected but arbitrary source may contain secrets. There is no
snapshot isolation, native provider tooling or silent context/file truncation.
See REPOSITORY_TOOLS.md for configuration, limits and recovery semantics.

Task 11 adds logical Project identity, mandatory immutable Task ownership, explicit
Project persistence and Alembic 0002. Existing 0001 rows are backfilled into a fixed
migration-only Project; new domain Tasks require an explicit owner. Runtime-only
canonical bindings and a small registry compose one workspace per Project, verifying
reader/mutation/real-test roots before side effects. Durable task-scoped binding
digests detect drift; evidence derives ownership through Task rather than duplication.
Fake workflows retain compatibility through explicit Project fixtures. Models/prompts,
gates, state edges, path policies, reliability and dependencies remain unchanged.
Tests cover migration/history preservation, two independent temporary calculator
Projects, rejected compositions, DB reopen and safe resume. See PROJECTS.md.

Recommended next step: wait for ChatGPT review and user approval before Task 12.
At the Task 11 checkpoint, Task 12 was not implemented.

## Task 12 application surface

An in-process `QASentinelApplication` now provides Project/Task commands,
Project-scoped execution/resume and bounded detached evidence views above the
existing core. No transport, CLI, frontend or dependency was introduced. See
[APPLICATION.md](APPLICATION.md); Task 13 remains pending review and approval.

## Task 13 backend API v1

An explicitly composed FastAPI factory now exposes `/api/v1` Project/Task commands
and bounded inspection routes over QASentinelApplication, plus process health and
generated OpenAPI. Controlled error envelopes omit internal details. Run is
synchronous and resume remains separate. No auth/frontend/background worker or
migration is introduced. ASGI HTTP tests use no real API/provider connections.
See [API.md](API.md). Wait for ChatGPT review and user approval before Task 14.

## Task 14 frontend foundation

A separate React/TypeScript/Vite workspace now consumes API v1 through a shared
typed client. The operator shell includes Projects and creation, Project Detail
with owned Tasks and creation, and Task Detail with basic persisted timeline and
explicit synchronous Run/separate Resume. API error/truncation feedback and
responsive accessible controls are included. No backend contract/CORS/persistence
changes, fake runtime bootstrap, polling, auth or Task 15 tabs were added.
See [FRONTEND.md](FRONTEND.md). Wait for review and approval before Task 15.

## Task 16 — Local full-stack host

The explicit host package composes the accepted API/application/core with Alembic
file-backed SQLite and built frontend assets. `qa-sentinel serve --demo` uses the
offline synthetic calculator runtime; real local JSON configuration resolves
persisted Project keys into explicit guarded workspace/service bundles. Loopback
only, one worker, no concurrent Run/Resume, no auth/public deployment. No accepted
contracts, migrations, model defaults or Task 9–15 policies change. See HOSTING.md.
