# Operational observability (Task 24)

Operational views summarize persisted truth and derived safety signals.
They do not control workflow progression. The dashboard has no execution,
Resume, retry, cancellation, repair or reconciliation-resolution action.
TaskState and evidence remain the only QA workflow truth; an ExecutionJob tracks
one request lifecycle. SUCCEEDED never implies Task DONE, tests PASS or review
acceptance. [Execution jobs](EXECUTION_JOBS.md), [Reconciliation](RECONCILIATION.md).

## Frozen application projections

| DTO | Selected data |
| --- | --- |
| OperationalSummaryView | Global Project/Task, RUNNING/QUEUED job, BLOCKED Task and DONE/FAILED Task counts; DB reconciliation signal count; failed/stopped jobs among the latest 50 requests; generated_at |
| ProjectOperationalSummaryView | Project UUID/key, Task/active-job/BLOCKED/signal counts, latest displayed activity or Project/Task update timestamp |
| TaskOperationalSummaryView | Task/Project UUID/key, title capped at 240 characters, TaskState, active/latest job status, fixed job/error code, DB signal, operational attention and updated_at |
| OperationalActivityView | Source record UUID, owning Task/Project UUID, fixed activity kind, timestamp and allowlisted transition TaskState |

All DTOs are frozen and reject extra fields. CollectionPage uses immutable items,
total_returned and honest truncated. No prompts, raw provider/error payloads,
stdout/stderr, ORM objects, insertion sequence, workspace paths or credentials
are returned. Unknown ErrorRecord codes map to ERROR_RECORDED; only fixed safe
codes and lifecycle enums are displayed. No new persistence table, migration,
cache, metrics store, collector or dependency is introduced.

Application methods are get_operational_summary,
list_project_operational_summaries, list_task_operational_summaries and
list_operational_activity. Each opens one short read-only UnitOfWork, performs
explicit SQL projections/aggregates and closes without committing or writing.
It never resolves a runtime, calls full reconciliation or reads a filesystem.
No operational method is consulted by execution, gates or state transitions.

## Query bounds and snapshots

All collections default to 50 and accept integer limits 1–100. SQL fetches only
limit+1 projected rows; no per-row sessions or full evidence objects are loaded.
Aggregate counts operate in SQL over durable records, including empty Projects.
Correlated EXISTS queries detect unresolved reservations; database query cost
can grow with retained evidence. This is a bounded response, not a constant-time
history scan or a replacement for future measured database tuning. No repository
scan, N filesystem verification, provider call, test process or mutation occurs.

Task lists order by updated instant descending then Task UUID descending.
Projects order by key then UUID. Latest jobs use accepted insertion order, not
client timestamps. Recent failed/stopped counts cover the latest 50 requested
jobs globally, not a time window. A newer successful request can replace a Task's
latest failed status; the activity feed still records the older terminal job.

Each response is assembled in one deliberate short read transaction. Separate
dashboard GETs can observe nearby committed states while a worker progresses;
there is no atomic distributed/global monitoring claim. generated_at timestamps
the summary snapshot. The browser publishes a cycle only after every GET settles.

## DB reconciliation signals and attention

The list flag reconciliation_attention is **DB-only triage**, not the Task 22
CLEAR/RECOVERABLE/MANUAL_ACTION_REQUIRED/INCONSISTENT assessment. It implements
the durable reservation subset of the accepted Task 22 rules:

- Any Invocation still STARTED.
- MODEL_TURN_STARTED without MODEL_TURN_COMPLETED/FAILED matching Task,
  invocation UUID and turn_index.
- MUTATION_RESERVED without MUTATION_APPLIED/FAILED matching Task/invocation.
- MUTATION_RECONCILIATION_REQUIRED, or recorded mutation result rollback FAILED.
- TEST_EXECUTION_STARTED without a TestRun matching Task, test-run UUID and
  implementation Artifact UUID.

Pending evidence can reflect work still running, not necessarily a crash.
No signal does **not** prove CLEAR or permission to continue. This subset omits
full canonical/linkage/integrity and workspace/applied-hash verification. The
existing Task Detail assessment remains the drill-down; Run/Resume/enqueue still
use accepted backend safety guards. No uncertainty is resolved, STARTED cleared,
outcome fabricated, replay attempted or source touched by operational reads.

Attention is a deterministic UI label, with this priority:

1. Task BLOCKED → BLOCKED.
2. Active QUEUED/RUNNING job → ACTIVE.
3. DB signal or latest FAILED/STOPPED job → ATTENTION.
4. Otherwise → NORMAL.

The separate reconciliation flag remains visible even for ACTIVE/BLOCKED Tasks.
Attention only includes all non-NORMAL categories; Active only requires an active
job. These filters are facts, not subjective scoring or AI prioritization.

## Activity and safe details

The feed derives from STATE_TRANSITIONED Events, job creation/start/terminal
timestamps, blocking ErrorRecords and TestRuns. It selects only enum/UUID/time
fields; arbitrary payloads are never returned or rendered. Task transitions
expose only a known to_state; unknown values become null. Job SUCCEEDED is named
Execution succeeded, never Task completed. PASS/FAIL/UNKNOWN refer to TestRun.

Newest UTC instant first, then fixed source rank (TestRun, blocking error, terminal
job, started job, queued job, transition), then record UUID descending provide
stable timestamp ties. Tie order is display order, not inferred causal ordering.
One job can contribute queued, started and terminal entries. No new activity
table or fabricated reconciliation-detection event is created.

## HTTP reads and access

| GET route | Filters |
| --- | --- |
| /api/v1/operations/summary | None; always global |
| /api/v1/operations/projects | limit |
| /api/v1/operations/tasks | project_id, task_state, execution_status (latest job), attention, reconciliation_attention, active_only, attention_only, limit |
| /api/v1/operations/activity | project_id, limit |

Only these new routes return safe 400 REQUEST_VALIDATION_ERROR for invalid,
duplicate or unknown query parameters. Boolean queries must be lowercase true
or false; limits must be decimal integers. Unknown filtered Project returns
404 PROJECT_NOT_FOUND. Existing API validation contracts remain unchanged.
There are no operational mutation/detail endpoints or arbitrary search/sort.
Successful responses use Cache-Control: no-store.

Preview Basic and hosted session middleware protect all operational routes and
the SPA /operations route. Hosted GETs need no CSRF proof. Login recovery, cookie
attributes, expiry and unsafe-request CSRF are unchanged; no writes are replayed
after authentication failure. Only existing public health/login entry points
retain their existing treatment. Both public runtimes remain deterministic,
synthetic fake-only; persistence never enables real models, repository access,
mutation or pytest. Local real remains trusted loopback workspace execution.

Host readiness stays outside API v1: selecting one Project reads existing
/host/runtime-status/{project_id} through RuntimeReadiness. It is a separate
manual snapshot, never persisted in Project or polled for every table row.
Configured is not execution authorization or verified provider availability.

## Browser behavior and operator drill-down

Choose Operations in primary navigation. Global cards show Projects, Tasks,
Running, Queued, Blocked and Reconciliation attention; recent failure counts are
text. Task/project tables and activity link to existing detail pages. Task Detail
adds only Back to Operations; execution/reconciliation/evidence remain intact
and evidence stays lazy. Select a Project or Inspect runtime for host readiness.

Project, Task state, Attention only and Active only filters are URL query state.
Invalid/duplicate/unknown values show a resettable error without operational
reads. The first 50 Projects supply the selector; other persisted UUIDs can be
shared in URLs, and Projects navigation remains available for the full boundary.
Tables list up to 50 rows with a truncation notice and safe empty states.

A single refresh cycle reads summary/projects/tasks/activity with GETs only.
After settlement it waits seven seconds while visible. Cycles never overlap,
including partial failure and filter changes; only the latest waiting filter
runs next. Hidden tabs cancel scheduled refresh; visibility restores a fresh
read. Unmount/navigation cancels scheduling and ignores pending results. Filter
generations prevent old snapshots from replacing newer selections. Auth expiry
uses Task 23 login recovery and stops polling. Manual Refresh is available.

Fixed text statuses, labelled filters, native links, table captions/headers and
keyboard-focusable horizontal table regions keep the page usable at narrow
widths. Summary cards wrap; tables scroll within the page at 320 px. Background
refresh keeps focus and does not repeatedly announce unchanged content. Last
updated is discreet. A fresh synthetic demo renders clean zeros; after Demo
Calculator execution, Task state and lifecycle activity reflect durable facts.

## Verification and limits

Tests cover projections/counts/bounds/filter validation, cross-Task correlation,
timestamp ties, safe enum projection, zero changes to every durable table, and
denial of runtime resolution/provider/subprocess/filesystem operations. API tests
cover inherited Basic/session and loopback modes. Mocked frontend tests cover
routing, filters, serialization, stale reads, visibility/navigation/auth expiry
and safe labels. Production browser checks exercise responsive layouts without
external requests. No live providers or Render services are used.

There are no alerts, notifications, charts, monitoring backend, operational
history store, exactly-once execution claim, multi-user access or recovery action.
Use [Product Guide](PRODUCT_GUIDE.md) and [Task recovery](RECONCILIATION.md) to
investigate evidence explicitly before continuing work.
