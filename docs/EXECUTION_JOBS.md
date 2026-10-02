# Durable execution requests (Task 20)

**TaskState = QA workflow truth. ExecutionJobStatus = one host execution request
lifecycle.** Inspect persisted Task state, Artifacts, Invocations, Test Runs,
Errors, Decisions, Gates and Events to understand QA work. A job neither changes
workflow state nor replaces that evidence. SUCCEEDED does **not** mean DONE.

## Request lifecycle

| Status | Meaning |
| --- | --- |
| QUEUED | Accepted and durably waiting for the one local worker |
| RUNNING | Worker durably claimed the request before entering workflow |
| SUCCEEDED | Existing application Run returned normally; inspect Task separately |
| STOPPED | Accepted RUNTIME_STOPPED, or interrupted RUNNING work on restart |
| FAILED | Unexpected job/host infrastructure failure with a fixed generic code |

Allowed edges are QUEUED → RUNNING → SUCCEEDED/STOPPED/FAILED. Normal return for
BLOCKED can produce SUCCEEDED without resuming or executing agents. Job status
never sets TaskState or evaluates a gate. There are no job retries, cancellation,
priorities, schedules, pause/resume or distributed leases.

The frozen domain record and detached ExecutionJobView contain only id, task_id,
project_id, status, created_at, nullable started_at/finished_at and nullable
safe_error_code. Timestamps are UTC and validated against the lifecycle. Fixed
codes are RUNTIME_STOPPED, EXECUTION_INTERRUPTED and EXECUTION_FAILED. No workspace,
runtime object, request/header, environment, credential, prompt, provider response,
raw exception or command output is stored.

## Persistence and ordering

Alembic **0003_execution_jobs.py** follows unchanged 0002. It adds a small table,
Task/Project foreign keys, lifecycle checks and indexes. Application creation
derives Project ownership from the persisted Task and validates any trusted
Project scope; independent foreign keys alone cannot prove matching ownership.
Reads/claims also reject mismatched persisted ownership. HTTP bodies cannot set
owner, workspace or lifecycle fields.

A SQLite partial unique index allows one active (QUEUED/RUNNING) job per Task.
Another permits only one RUNNING job globally. An internal integer AUTOINCREMENT
sequence, omitted from the DTO, orders queue claims by **ascending durable
insertion**, independent of wall-clock ties/drift or random UUIDs. Task job lists
show descending insertion sequence, bounded to limit+1 with honest truncation.
The sequence is operational queue ordering, not QA chronology.

Short lifecycle writes use SQLite BEGIN IMMEDIATE before reading, serializing
duplicate submissions and claims without read-to-write upgrade races. Other core
transactions retain their accepted behavior. QUEUED, RUNNING and terminal commits
are separate UnitOfWork lifetimes; no DB session/transaction wraps workflow,
models, tools, mutation or tests. Downgrade drops only job records/indexes, retaining
Tasks and QA evidence. Back up operational history before downgrading. Package
distributions include the new migration asset.

## Application and HTTP

Application commands/queries are request_task_execution(task_id, project_id=None),
get_execution_job(job_id, project_id=None) and list_task_execution_jobs(task_id,
project_id=None, limit=50). Results are frozen views or bounded pages. Trusted
worker-only methods claim, finish and reconcile requests; they have no public
lifecycle-write endpoint. The existing resolver resolves persisted Task ownership;
unconfigured Projects fail before enqueue. No request/model data selects a runtime.

| Endpoint | Response |
| --- | --- |
| POST /api/v1/tasks/{task_id}/executions | 202, newly committed QUEUED snapshot |
| GET /api/v1/tasks/{task_id}/executions?limit=50 | CollectionPage[ExecutionJobView], cap 200 |
| GET /api/v1/executions/{execution_id} | Persisted ExecutionJobView |

POST accepts no body or `{}`; extra fields are rejected. The worker can advance
before the POST response reaches the client. GET reflects persisted status.
Active same-Task requests yield TASK_EXECUTION_ALREADY_ACTIVE (409), unknown jobs
EXECUTION_JOB_NOT_FOUND (404), invalid trusted lifecycle writes
EXECUTION_JOB_INVALID_STATE (409). DONE/FAILED Tasks reject async requests with
TASK_EXECUTION_TERMINAL (409); legacy synchronous /run retains the existing
terminal check without rerunning agents.

**POST /run remains synchronous** and returns durable TaskDetail after execution
or the existing safe stop. It does not enqueue. Resume remains synchronous,
restores BLOCKED → resume_state and requires separate execution. Active jobs block
same-Task synchronous Run/Resume; global overlap remains fail-fast RUNTIME_STOPPED.
The existing frontend still uses synchronous Run and separate Resume. Task 20
adds no frontend polling/job UX.

## One host worker and shared admission

Only the explicitly composed full-stack ASGI host starts a worker, in lifespan.
Standalone API/application factories never start one implicitly; embeddings must
provide equivalent trusted single-host coordination. Production remains one host,
one process, one Uvicorn worker and one execution thread. Use only one host against
a database/workspace; this is not multiprocess/multi-host coordination.

Startup migrates and composes runtimes, stops submissions, reconciles old RUNNING
records, then starts the daemon worker before accepting HTTP requests. It reads
persisted QUEUED work from SQLite. An Event wakes it after commits; a bounded idle
recheck recovers a lost notification without retrying claimed work. No in-memory
queue is authoritative.

One host-owned reentrant workflow mutex covers claim, Run and completion. The
worker's own application call reenters on its thread with a trusted job context;
the application verifies the matching job is RUNNING. Synchronous Run/Resume
share that coordinator on their request threads. Short submission/lifecycle gates
protect admission state and stop/claim races, without executing workflows.
Different Tasks can enqueue while the worker is busy but cannot execute together.
The current Task cannot enqueue while its legacy synchronous command is active.

Normal return maps to SUCCEEDED. Accepted application RUNTIME_STOPPED maps to
STOPPED/RUNTIME_STOPPED. Other application/infrastructure failures map to
FAILED/EXECUTION_FAILED, without exception text or Task changes. Existing core
exception mapping is retained: failures already wrapped as RUNTIME_STOPPED remain
STOPPED. If claim/completion persistence is uncertain, the worker and new execution
admission stop with a fixed host code; there is no blind retry.

## Shutdown, restart and uncertainty

Shutdown stops submissions/new claims and waits a bounded grace period. In-flight
work is not cancelled and its RUNNING record is not falsely completed. It may
finish and persist a terminal result while the same process remains alive. Engine
disposal is deferred until that worker exits if the bounded join expires. Queued
records remain recoverable; there is no forceful source/test/model cancellation.

On a new process startup, stale RUNNING reservations are committed as
STOPPED/EXECUTION_INTERRUPTED **before new work is accepted**, never automatically
rerun. Persisted QUEUED requests may execute in durable FIFO order, including real
local jobs using the currently configured resolver. Inspect Task evidence and
reconcile unresolved Invocations, Test Runs, mutation/persistence or workspace
drift before explicitly requesting execution. Resume is not reconciliation or a
reliability-budget reset.

There is **no exactly-once guarantee** across filesystem, provider, subprocess,
workflow persistence and job completion. A crash after RUNNING but before work,
or after Task completion but before job completion, is conservatively uncertain.
A terminal job cannot prove every external side effect occurred. The job system
adds no hidden provider/workflow retries or recovery shortcuts.

## Runtime boundaries and verification

Demo/preview jobs use Demo Calculator's existing FakeAgentRuntime and fake test
provider. Preview still rejects OPENAI_API_KEY, protects all job endpoints with
Basic authentication and leaves only exact GET /health public. No physical
repository/mutation service or real pytest/provider access is introduced there.
Real local jobs use accepted ProjectExecutionResolver/bundles, workspace guards,
read/mutation/test policies, gates and reliability. Workspace paths remain
host-owned, absent from Projects and jobs. Local bind stays loopback-only.

Tests use temporary databases/workspaces and fake or mocked models, with live
network/provider calls denied. They cover migration preservation/downgrade,
duplicate writers, FIFO ties, lifecycle constraints, detached DTOs, commit-before-work
and closed transactions, shared admission, bounded shutdown, stale RUNNING/queued
recovery, API compatibility and preview isolation.
