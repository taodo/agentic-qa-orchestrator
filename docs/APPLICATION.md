# Application services (Task 12)

## Operational reads (Task 24)

OperationalSummaryView, ProjectOperationalSummaryView, TaskOperationalSummaryView
and OperationalActivityView are frozen derived visibility over existing durable
records. The explicit get_operational_summary/list_* operational methods use one
short read transaction and bounded SQL projections (default 50, maximum 100).
No runtime resolution, full reconciliation, filesystem scan, provider, test,
mutation or write occurs. TaskState remains workflow truth; operational labels
are never consulted by progression. Host readiness remains a separate host read.
[Observability](OBSERVABILITY.md) documents counts, DB-only signal limitations,
attention priority, deterministic activity ordering and snapshot consistency.
No table, migration, dependency or existing execution contract changes.

`qa_sentinel.application.QASentinelApplication` is the in-process boundary for
CLI, Backend API and Web callers. Hosts configure dependencies explicitly;
callers receive frozen, extra-forbidden DTOs. Application code depends on domain,
persistence and orchestration. Core code never depends on application contracts.

## Composition and execution

Construct the facade with an existing `create_session_factory` and a
`ProjectExecutionResolver`. The resolver receives a `ProjectRuntimeRegistry` and
explicit `ProjectExecutionBundle` instances. A bundle contains the binding,
runtime, test provider, optional repository reader and optional mutation service.
These are trusted host objects, never request/model configuration. Registry
bindings must match bundle bindings; duplicate bundles are rejected. Missing
configuration and binding drift produce stable application errors. Registry root
overlap protection and the Task 11 `ProjectWorkspaceGuard` remain authoritative.

`run_task(task_id, project_id=None)` loads the persisted Task and its Project,
resolves by **persisted Task.project_id**, closes the read transaction, constructs
the existing `WorkflowRunner`, delegates execution and returns durable TaskDetail.
There is no application transaction across model calls, filesystem work or tests.
There is no application retry, routing, gate evaluation or state assignment.
Existing runner terminal/BLOCKED semantics apply: no additional agent execution
for DONE/FAILED and no implicit resume. The core may establish its workspace
anchor on the first run, including a terminal/BLOCKED run. Subsequent runs are
idempotent when host configuration remains consistent. Runtime configuration is
required even for terminal runs, so existing guard checks are preserved.

`resume_task(task_id, project_id=None)` accepts only BLOCKED with a stored
nonterminal, non-BLOCKED resume target. It delegates to `WorkflowEngine.transition`
with `APPLICATION_RESUME`, recording transition, decision and event atomically.
It returns the resumed detail without execution. Use a separate `run_task` call
to continue. The engine validates the existing resume semantics; FAILED remains
a separate terminal transition, never an application resume target.

## Commands and queries

- `create_project(key=..., name=..., description="")` validates the existing
  Project model and commits through UnitOfWork. Keys remain unique.
- `update_project(project_id, name=..., description=...)` changes only explicitly
  supplied name/description and sets updated_at to UTC. Null values and fields
  such as key/id/created_at/workspace_root are rejected atomically.
- `create_task(project_id=..., title=..., requirement=...)` verifies Project
  existence and persists explicit ownership atomically. No default Project.
- `get_project`, `list_projects`, `get_task`, `get_task_detail`,
  `list_tasks_for_project` return detached Project/Task views.
- `get_task_timeline`, `get_task_artifacts`, `get_task_test_runs`, `get_task_errors`,
  `get_task_decisions`, `get_task_gate_evaluations`, `get_task_invocations` expose
  distinct evidence types. Every Task method optionally accepts project_id and
  verifies the scope matches the persisted owner; its owner must always exist.

The ordinary evidence/identity queries use short UnitOfWork scopes and perform SELECTs only. They do not
resolve execution dependencies, establish workspace anchors, transition workflow,
call models/tools, run subprocesses or read local source files. Inspection works
even when no execution bundle exists. UUID inputs may be UUID objects or strings.

## Read contracts and bounds

ProjectView contains Project metadata. TaskSummary contains identity, ownership,
title, state and timestamps; TaskDetail adds requirement, resume/current invocation,
counters and terminal reason. InvocationView excludes input_context_refs.
ArtifactView retains intentionally persisted metadata/content and supersession.
Content is recursively detached and frozen (mapping proxies and tuples); DTO
`model_dump()` / `model_dump_json()` returns normal serializable JSON content.
TestRunView contains structured results, never stdout/stderr. ErrorView,
DecisionView and GateEvaluationView preserve their core terminology and fields.
Nested actor/correlation/source/check contracts are already frozen core values.

CollectionPage has tuple items, total_returned and truncated. Every collection
defaults to 50, accepts positive integer limits and caps at 200, except timeline
(500). Booleans are not limits. SQL retrieves at most limit+1 rows to determine
truncation **before** materialization/projection; no full-history count or dump.
No cursor/offset is provided in this phase. These pages are bounded prefixes,
not complete histories when truncated; total_returned is the returned count.

Projects sort by key, then UUID. Tasks sort by created_at UTC instant descending,
then UUID for equal instants. Evidence collections sort by their persisted
created/evaluated/started timestamp ascending, then same-table insertion order.

## Timeline and chronology

The timeline projects the existing **Event ledger only**; other evidence remains
in separate typed collections and is linked by persisted correlation references.
It does not invent an Event for each Error/Artifact/Decision/TestRun. Each entry
has a prefix index, persisted SQLite insertion_order, event identity, timestamp,
timestamp_tied flag, category EVENT, type, actor, correlation, compact type summary
and an allowlist of scalar persisted details. Full event payloads are not exposed.

ISO timestamps are ordered by integer UTC microseconds through the SQLite
deterministic function installed by the existing engine factory. Historical naive
timestamps mean UTC. Equal UTC instants sort by the existing table's SQLite rowid,
which records insertion order and survives normal connection closure/reopening.
UUID order is never used as Event chronology. timestamp_tied marks equal adjacent
instants, including a lookahead row beyond the requested prefix. A tie specifies
same-table insertion order, not independently measured causal timing.

No migration is needed for the current SQLite append-only ledgers. Rowid is a
storage-local ordering key, not a portable identifier: administrative VACUUM,
table rebuilding or export/import can renumber implicit rowids. Timeline keys
must not be cached as permanent external cursors. Cross-table causal ordering,
database-maintenance-stable sequence identity and portable pagination are outside
this phase. A later such requirement would justify an explicit persisted sequence.

## Errors and data boundary

ApplicationError exposes only a stable ApplicationErrorCode as its message.
Missing resources map to PROJECT_NOT_FOUND / TASK_NOT_FOUND; scope mismatch to
PROJECT_TASK_MISMATCH. Runtime configuration maps to
PROJECT_RUNTIME_NOT_CONFIGURED / PROJECT_RUNTIME_MISMATCH. Resume preconditions
map to TASK_NOT_BLOCKED / TASK_RESUME_STATE_MISSING / TASK_RESUME_STATE_INVALID.
Bad limits/command inputs map to INVALID_LIST_LIMIT / INVALID_INPUT; duplicate
keys to PROJECT_KEY_EXISTS; database/projection failures to PERSISTENCE_ERROR.
Runner stops, reconciliation and unexpected host execution failures map to
RUNTIME_STOPPED. They never become success or force FAILED: durable core evidence
and state remain available through queries for explicit reconciliation. No retry
occurs after a stop, including mutation followed by persistence failure.

DTOs expose only approved persisted evidence, not provider responses, hidden
reasoning, credentials, environment variables, authorization headers or new
filesystem data. Existing Artifact content can include intentionally persisted
source and relative path evidence; hosts remain responsible for protecting their
database and restricting future caller access. This layer is not authentication
or a sandbox and adds no model tool capability.

## Future host mapping and non-goals

Future API handlers can validate input, call one explicit facade method, serialize
its DTO/page and map stable errors to their chosen HTTP statuses. They should not
reach into repositories or WorkflowRunner. No HTTP transport/status mapping is
implemented here. CLI/frontend/auth/users/RBAC/deletion/background execution,
schedulers/queues, event buses, generic dependency containers, Git automation,
secrets storage and Task 13 remain outside Task 12. No new dependency is added.

## Task 13 HTTP transport

`qa_sentinel.api.create_api_app(application)` now wraps this facade with typed
versioned HTTP routes and stable error envelopes. Route handlers use one explicit
application method; run/resume remain separate and queries remain bounded.
Host composition remains explicit. See [API.md](API.md) for transport contracts,
synchronous semantics and the non-public/no-auth limitation.

## Task 20 execution-request lifecycle

The facade exposes request_task_execution, get_execution_job and
list_task_execution_jobs with frozen ExecutionJobView/bounded page results.
Creation derives ownership from persisted Task, verifies the trusted resolver,
rejects DONE/FAILED async requests and allows one active job per Task. No workspace
or user payload enters job persistence. Invalid scope/unconfigured runtime retain
accepted errors. Job status never assigns Task state or alters gates.

Trusted host-only claim/finish/reconcile methods use separate short BEGIN IMMEDIATE
UnitOfWork transactions; RUNNING commits before the worker calls existing run_task.
No transaction spans workflow work. Optional host-owned admission/wakeup objects
are explicit injected dependencies, never HTTP/model inputs. Synchronous Run,
Resume and the worker share admission; active jobs block same-Task legacy commands.
Embeddings must provide equivalent single-worker coordination.

SUCCEEDED means normal return and can accompany BLOCKED. RUNTIME_STOPPED maps to
a stopped request; unexpected job failures retain only generic codes. Core
run/resume behavior, terminal checks and evidence remain authoritative. Restart
stops stale RUNNING requests without rerunning them; queued work can recover.
No retry, Task transition or source reconciliation belongs to this job surface.
[Execution jobs](EXECUTION_JOBS.md) documents the full contract.

## Task 22 derived reconciliation

`assess_task_reconciliation(task_id, project_id=None)` reads a detached durable
snapshot and then uses the trusted resolver, read-only workspace guard and
bounded recorded applied-hash verification outside the transaction. It returns
ReconciliationAssessmentView without state changes, anchor adoption, evidence
writes, provider calls, subprocesses or source mutation. Unlike ordinary evidence
queries, it requires the configured trusted bundle for workspace safety.

Run, valid Resume and async submission share the assessment guard before effects
or enqueue. MANUAL_ACTION_REQUIRED/INCONSISTENT return
TASK_RECONCILIATION_REQUIRED. Invalid Resume retains its existing validation codes
before reconciliation; no invalid command can transition. Active-job errors retain
their existing priority. No retry/routing/evidence repair moves into application.
See [Reconciliation](RECONCILIATION.md) for flags, bounds and operator playbooks.
