# Local full-stack host (Task 16)

The supported host is one same-origin ASGI app: host → API → application → core.
Host code lives in `qa_sentinel.host`; no core/application/API module imports it.
Imports create no app, engine, database, workspace or listening server. Explicit
startup validates built assets/config, upgrades file-backed SQLite with Alembic,
composes Project runtime bundles, then starts minimal Uvicorn in one process.
Accepted API contracts, gates, recovery budgets and workspace policies are unchanged.

## First-run offline demo

From the checkout, with Python 3.12+ and Node.js 22.12+:

```shell
python -m pip install -e ".[test]"
cd frontend
npm ci
npm run build
cd ..
qa-sentinel serve --demo
```

Open **http://127.0.0.1:8000**. Package installation/build prerequisites may require
network; **normal demo startup and workflow execution require none**. Server startup
does not install/build packages, start Vite, clone repositories or download assets.
No OPENAI_API_KEY is required. Project description explicitly identifies synthetic
demo evidence; the startup message identifies demo mode. The existing global UI
label remains a local operator workspace, without a new mode API contract.

Select **Demo Calculator**, create a Task with requirement “Add division support
and reject division by zero”, then click Run. The accepted application/runner,
state machine and gates persist the normal CREATED → RESEARCHING → PLANNING →
IMPLEMENTING → TESTING → REVIEWING → DONE path. Inspect Timeline, Artifacts,
Invocations, Test Runs, Decisions and Gates in the existing console.

The accepted `division_scenario()` provides fixed fake agent outputs and synthetic
passing test results. It is a calculator demonstration, not live AI verification
of arbitrary requirements. Fake Implementer reports synthetic changes but writes
no source. No RepositoryReadService, MutationService, subprocess test runner or
provider client is used in demo mode. Resume remains separate from Run.

The default DB is `~/.qa-sentinel/demo/state.sqlite3`. The identity-only workspace
is its sibling `demo-workspace/`, with an explicit canonical ProjectWorkspaceBinding.
It is outside QA Sentinel source and is never populated with fabricated physical
services. Exactly one Project is seeded by key `demo-calculator`; restart preserves
its UUID, operator edits, Tasks and all evidence. Operator-created Projects are
retained but receive no implicit runtime configuration. No demo Task is pre-seeded.

Explicit path/port overrides:

```shell
qa-sentinel serve --demo --database /absolute/private/state.sqlite3 --frontend-dist /absolute/frontend/dist --port 8001
```

Choose a private state directory outside the platform source and frontend dist.
Both `127.0.0.1` (default) and explicit `::1` are supported. External bind addresses
are rejected; no external-bind flag is offered in this local-only task.

## Real local mode

Create the logical Project first through the existing API (for example during a
demo session against the same DB). Stop that server, prepare a separate trusted
target workspace with tests, and provide a private JSON configuration:

```json
{
  "database": ".qa-sentinel/state.sqlite3",
  "frontend_dist": "frontend/dist",
  "projects": [
    {
      "key": "my-project",
      "workspace_root": "/absolute/path/to/prepared-project",
      "pytest_targets": ["tests"]
    }
  ]
}
```

On Windows use absolute drive paths, with JSON backslash escaping or forward
slashes. `database`/`frontend_dist` are relative to the JSON file when relative;
workspace roots must be absolute existing directories. Optional `host`/`port`
retain the same loopback defaults. Only mode `local` is allowed in a config file.

```shell
qa-sentinel serve --config qa-sentinel.local.json
```

Set OPENAI_API_KEY in the **local process environment**, never JSON/chat/source.
Startup checks only presence and gives a generic error if absent; it performs no
provider call. Existing OpenAIModelAdapter owns SDK creation, pins the official
Responses endpoint, disables SDK retries and uses schema-native output. Existing
RealAgentRuntime/RoleModelConfig defaults are reused, with accepted controlled
repository turns for Researcher/Planner and controlled Implementer proposals.
No new model tools, roles, provider memory, retry logic or prompt behavior is added.

Each config key must resolve to an existing persisted Project. Its UUID constructs
ProjectWorkspaceBinding, Registry, Bundle and Resolver; no path is persisted in
Project and request/model data cannot select runtime roots. Configuration does not
auto-create Projects or discover repositories. Restart/binding drift retains the
accepted reconciliation requirements. Only configured Projects can execute.

RepositoryReadConfig/Service and MutationConfig/Service use that exact root and
accepted limits. `allow_host_workspace` remains false. A configured target that
overlaps QA Sentinel is rejected before model/write/test work. SHA preconditions,
full-set validation, rollback and write/persistence reconciliation remain intact.

ExecutionConfig → CommandRunner → PytestRunner → TestExecutionService →
PytestTestResultProvider uses the same root/binding and configured targets. The
only constructed command is `python -m pytest <targets>` using the host's Python
interpreter. Install the target's test dependencies into that interpreter before
serving. No shell/executable/argv/environment configuration field exists. Targets
must be relative existing test files/directories/node IDs; options and shell-like
syntax are rejected using the accepted CommandPolicy. Target tests remain trusted
executable code; this host is not an OS sandbox.

## Database and migration lifetime

Startup creates the configured DB parent after canonical path validation, uses
the accepted engine/session factory, and upgrades to Alembic head (`0002`) on an
explicit idle connection. It never calls metadata.create_all or edits migrations.
The helper uses checkout migrations for editable installs; wheel distributions
include the unchanged migration assets under `share/qa-sentinel/alembic`.
Repeated startup is idempotent; migration errors abort before demo seeding/runtime
initialization and return a fixed safe host code. Lifespan/CLI shutdown dispose
the engine. Start only one host against a DB/workspace; migrations need exclusive
access. Multiprocess/multiple-host coordination is not supported.

## Built assets and SPA routing

The supported serve command requires an explicit existing build with index.html;
missing assets fail before DB bootstrap. It serves existing `/api/v1`, `/health`,
`/openapi.json`, `/docs` and `/redoc`, then a contained Starlette StaticFiles mount.
Known UI paths `/`, `/projects`, `/projects/{id}` and `/tasks/{id}` return index.html
for GET/HEAD. Unknown UI paths, API misses, malformed API input and missing assets
keep their own errors. Safe build assets under `assets/` are served; dotfiles,
traversal, backslashes, source/config/DB paths and symlink escapes are denied.
Root public files other than index.html and source maps are deliberately not served.
The accepted Vite build uses assets/ and needs no frontend changes or CORS.

Development still supports `npm run dev` with the existing Vite API proxy. This
host serves production assets directly and does not launch the development server.
Accepted Swagger/ReDoc pages retain their external documentation UI assets; those
optional pages are not needed for the offline demo/frontend workflow.

## Process, logs and local security

Uvicorn 0.41 runs with one worker, no reload, asyncio/h11, no WebSocket, no proxy
header trust and no access logging. CLI settings explicitly override environment
worker/bind defaults. A host-owned nonblocking admission lock covers Run/Resume
across all Projects: an overlapping execution receives the existing safe 409
RUNTIME_STOPPED envelope without entering core. Reads remain available; there is
no queue, background job, new workflow decision, auto-retry or concurrent mutation.
CLI logs mode/bind only; no key, environment dump, request body, source or evidence.

**There is no authentication.** The API can expose bounded persisted source/evidence;
real mode can mutate configured workspaces and execute their trusted tests. Keep
DB/config private, restrict local access, and do not expose this host publicly
without a trusted access boundary. Task 16 is not an internet production service.

Task 17 can later wrap the same ASGI/config/state/assets boundaries in a protected
deployment after explicit review. No deployment, TLS, proxy, domain, auth, worker,
Docker or Task 17 implementation is included here.

## Checks and troubleshooting

Run `python -m pytest`, then frontend `npm ci`, `npm test -- --run`, `npm run build`
and `git diff --check`. Host tests use migrated temp SQLite and ASGI TestClient,
deny external sockets/provider calls/subprocesses, and cover first-run/restart,
normal API evidence, static containment, config, CLI defaults and admission.

- HOST_FRONTEND_BUILD_MISSING: build the frontend and select its dist directory.
- HOST_CONFIG_INVALID: check JSON fields, port, explicit paths and mode; unknown
  fields, duplicate keys/Projects, overlap, links and missing workspaces fail closed.
- HOST_MODEL_KEY_REQUIRED: supply the environment key for real local mode only.
- HOST_PROJECT_NOT_FOUND: create the matching persisted Project in this DB first.
- HOST_TEST_POLICY_REJECTED: prepare valid targets in the configured root; no flags.
- HOST_COMPOSITION_FAILED: check accepted workspace/mutation boundaries; do not
  bypass host-source protection or reconciliation.
- HOST_DATABASE_STARTUP_FAILED: check a private writable DB parent and migrations;
  stop other hosts before migrating. No exception details/secrets are printed.
