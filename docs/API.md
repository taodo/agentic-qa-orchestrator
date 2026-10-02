# Backend API v1 (Task 13)

The backend is a thin HTTP transport: **API → QASentinelApplication → core**.
Each domain route validates transport input, calls one application use case and
serializes its frozen DTO. Routes have no ORM, repositories, workflow engines,
model calls, tools or transaction ownership. Core and application code do not
depend on API contracts. Task 13 required no migration; Task 20 adds an operational
job table through 0003 without changing core workflow policies.

## Application factory and host composition

```python
from qa_sentinel.api import create_api_app

# application is an explicitly host-composed QASentinelApplication.
app = create_api_app(application)
```

Importing the package creates no database connection or application singleton.
Each factory result holds its own injected application. Hosts construct their
session factory and ProjectExecutionResolver/bundles as described in
[APPLICATION.md](APPLICATION.md); no workspace, fake runtime or credentials are
silently selected here. Route injection uses the per-app dependency
`get_application`, which also supports standard FastAPI test overrides.

Synchronous handlers execute in FastAPI's worker thread pool. Hosts must provide
a session factory usable there; the tests use migrated file-backed SQLite with
the existing factory. A default SQLite in-memory database is connection-local and
is not a shared multi-thread test/host database. No route holds a database session
across execution. Generic local/production bootstrap remains future host work:
there is no uvicorn dependency, executable server entrypoint or CLI in Task 13.

## Routes and response contracts

Domain routes use `/api/v1`. Process health is **GET /health**, returning
`{"status":"ok"}` without inspecting the database/workspace or invoking workflow.

| Route | Application use case / response |
| --- | --- |
| GET /api/v1/projects | list_projects → CollectionPage[ProjectView] |
| POST /api/v1/projects | create_project → ProjectView (201) |
| GET /api/v1/projects/{project_id} | get_project → ProjectView |
| PATCH /api/v1/projects/{project_id} | update_project → ProjectView |
| GET /api/v1/projects/{project_id}/tasks | list_tasks_for_project → CollectionPage[TaskSummary] |
| POST /api/v1/projects/{project_id}/tasks | create_task → TaskSummary (201) |
| GET /api/v1/tasks/{task_id} | get_task_detail → TaskDetail |
| POST /api/v1/tasks/{task_id}/run | run_task → TaskDetail |
| POST /api/v1/tasks/{task_id}/resume | resume_task → TaskDetail |
| POST /api/v1/tasks/{task_id}/executions | request_task_execution → ExecutionJobView (202) |
| GET /api/v1/tasks/{task_id}/executions | list_task_execution_jobs → CollectionPage[ExecutionJobView] |
| GET /api/v1/executions/{execution_id} | get_execution_job → ExecutionJobView |
| GET /api/v1/tasks/{task_id}/timeline | get_task_timeline → CollectionPage[TimelineEntry] |
| GET /api/v1/tasks/{task_id}/artifacts | get_task_artifacts → CollectionPage[ArtifactView] |
| GET /api/v1/tasks/{task_id}/test-runs | get_task_test_runs → CollectionPage[TestRunView] |
| GET /api/v1/tasks/{task_id}/errors | get_task_errors → CollectionPage[ErrorView] |
| GET /api/v1/tasks/{task_id}/decisions | get_task_decisions → CollectionPage[DecisionView] |
| GET /api/v1/tasks/{task_id}/gates | get_task_gate_evaluations → CollectionPage[GateEvaluationView] |
| GET /api/v1/tasks/{task_id}/invocations | get_task_invocations → CollectionPage[InvocationView] |

All collections accept `?limit=50`, capped at 200 except timeline (500).
Zero, negative, non-integer and over-maximum values produce 422; values are never
clamped. The response preserves Task 12's bounded prefix and honest truncation:

```json
{"items": [], "total_returned": 0, "truncated": false}
```

total_returned counts items in this response, not the entire database. Task 12
queries still retrieve only limit+1 rows; timeline ordering/maintenance limitations
remain documented there. UUIDs, timezone datetimes, enums and nested correlation/
actor values use Pydantic/FastAPI JSON serialization. Existing DTO field serializers
thaw nested frozen artifact content into ordinary JSON objects and arrays.

Create Project body: `{"key":"payment-api","name":"Payment API","description":"..."}`.
Description defaults to empty. Patch accepts only supplied name/description;
explicit null, immutable fields and arbitrary extras are rejected. Empty patch
retains the application's existing updated_at behavior. Create Task body:
`{"title":"...","requirement":"..."}`; ownership comes exclusively from the
Project path. Body-supplied project_id/state/workspace values are forbidden extras.
Run/resume require no body/configuration. Task routes derive Project ownership
from persisted Task identity and expose no optional Project-scope parameter.

## Run/resume and Project isolation

Run is synchronous: the request waits for the existing WorkflowRunner to finish
or safely stop. Long-running model/test/mutation work occupies that request's
worker until completion. Task 20 separately adds durable execution requests and
one host worker; /run retains its original response and synchronous semantics.
Concurrent execution for the same Task remains unsupported by the core;
hosts must serialize such execution and provide exclusive trusted workspaces.

DONE/FAILED returns current durable state under existing guard semantics; BLOCKED
does not auto-resume. Resume records only the existing engine transition and
returns resumed state. Clients explicitly POST /run to continue. Resume is not
reconciliation: failed/unfinished invocation evidence can still stop a later run
until trusted host resolution. No HTTP endpoint clears or rewrites that evidence.

Project task lists are scoped by explicit path UUID. Task execution resolves
only persisted Task.project_id, never body/path metadata beyond task identity.
Task 11 workspace guards independently reject cross-Project service composition
before model/read/write/process calls; Task 9/10 policies and reliability budgets
are unchanged. All GET operations inherit side-effect-free application queries.

## Stable errors

Every public error uses `{"error":{"code":"TASK_NOT_FOUND","message":"Task not found"}}`.
Messages are fixed and generic, selected by code rather than exception text.

| Status | ApplicationErrorCode |
| --- | --- |
| 404 | PROJECT_NOT_FOUND, TASK_NOT_FOUND |
| 409 | PROJECT_KEY_EXISTS, PROJECT_TASK_MISMATCH, PROJECT_RUNTIME_NOT_CONFIGURED, PROJECT_RUNTIME_MISMATCH, TASK_NOT_BLOCKED, TASK_RESUME_STATE_MISSING, TASK_RESUME_STATE_INVALID, RUNTIME_STOPPED |
| 422 | INVALID_INPUT, INVALID_LIST_LIMIT |
| 500 | PERSISTENCE_ERROR |

Request validation (including invalid UUID/limit/body/extra fields) returns 422
with REQUEST_VALIDATION_ERROR and "Request validation failed". It does not echo
body, field values, exception details or internal validation structures. Framework
HTTP failures use HTTP_ERROR and generic messages; unexpected transport/response
failures use INTERNAL_ERROR / "Internal server error" (500). Debug mode is off.
No stack traces, provider details, paths or sensitive headers are returned.
RUNTIME_STOPPED never becomes 2xx or forces FAILED; durable evidence remains
available for inspection. Error models appear in OpenAPI responses.

## Dependencies, development schema and tests

The only new direct runtime dependency is `fastapi>=0.135.2,<0.136`. This bounded
release avoids the newer telemetry dependency. Its minimal newly installed
transitive packages are Starlette and annotated-doc; Pydantic, typing utilities
and AnyIO were already present. HTTPX (`>=0.28,<1`) is explicitly declared in test
extras; it was already available through the existing SDK test environment.
No FastAPI standard/all extras, uvicorn, telemetry, httpx2 or other frameworks.

Generated `/openapi.json`, `/docs` and `/redoc` are available in development/test
with title "QA Sentinel API" and version "1.0.0". No custom schema infrastructure.
The documentation pages may load their usual external UI assets in a browser;
automated tests only retrieve the HTML/schema through in-process ASGI transport.

Tests use FastAPI/Starlette TestClient directly, never start uvicorn/listen on an
HTTP port, and forbid external socket connections and live provider transport.
Windows asyncio's private stdlib wakeup socketpair uses loopback internally; the
socket guard allows only that exact stdlib call site, not application/provider
network traffic. SDK responses use the existing MockTransport with no real key
or API cost. Starlette 1.7's TestClient emits a deprecation warning for HTTPX;
the supported HTTPX transport remains functional without adding httpx2.
HTTP tests prove serialization, all bounds/error codes, explicit resume/run,
two-Project real read/mutation/pytest isolation and unchanged GET evidence/files.

## Security and non-goals

This API has **no authentication** and is not intended for untrusted public
internet exposure. Hosts must restrict access. It may return intentionally
persisted bounded source/artifact evidence approved by Task 12; it reads no new
filesystem content and exposes no API keys, environment, authorization headers,
hidden reasoning or raw provider responses. No request/body/content logging is
added. There is no CORS middleware or wildcard origin policy.

Frontend, auth/users/RBAC, queues/workers, WebSocket/SSE, schedulers, deployment,
Docker/HTTPS, uploads, Git/GitHub automation, CLI and Task 14 remain out of scope.

## Task 14 frontend consumer

The dedicated React/Vite workspace consumes these unchanged API contracts via
same-origin `/api/v1` requests and a configurable development proxy. Backend
startup remains explicit; no wildcard CORS or unsafe runtime defaults were added.
See [FRONTEND.md](FRONTEND.md) for operator screens and development commands.

## Task 16 local host

`qa-sentinel serve --demo` now explicitly composes the existing factory/application
with migrated file-backed SQLite and offline fake runtime, then serves the built
frontend on the same loopback origin. Real local composition uses persisted Project
keys and accepted workspace services. Host code does not change this API contract,
CORS or runtime semantics; it admits only one Run/Resume request at a time and
returns the existing RUNTIME_STOPPED conflict for overlap. See [HOSTING.md](HOSTING.md).

## Task 20 durable execution requests

POST `/tasks/{task_id}/executions` accepts no body or `{}` and returns 202 with the
committed QUEUED snapshot. Extra owner/workspace/status fields are rejected. GET
`/executions/{execution_id}` returns persisted operational status; GET
`/tasks/{task_id}/executions` returns newest insertion first with existing bounded
limit/truncation rules. All paths use `/api/v1`. ExecutionJobView contains only id,
task_id, project_id, status, created_at, started_at, finished_at, safe_error_code.

TaskState remains QA truth. SUCCEEDED means normal application return, not DONE.
Unknown jobs return EXECUTION_JOB_NOT_FOUND (404); duplicate active requests
TASK_EXECUTION_ALREADY_ACTIVE (409); terminal async requests TASK_EXECUTION_TERMINAL
(409); invalid trusted lifecycle transitions EXECUTION_JOB_INVALID_STATE (409).
Global execution overlap retains safe RUNTIME_STOPPED. /run never enqueues; Resume
remains synchronous and separate. Host lifespan owns the worker; a standalone API
only persists requests unless its embedding explicitly supplies a worker. Preview
job routes stay Basic-protected. [Ordering/restart limits](EXECUTION_JOBS.md).
