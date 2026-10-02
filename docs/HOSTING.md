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
are rejected in ordinary demo and real local modes. Task 17 adds a separate explicit
`--preview-demo` mode; it does not relax these local restrictions.

## Real local mode

For repeatable setup, use [Real Project onboarding](#real-project-onboarding).
The explicit JSON format below remains supported for multiple Project bindings.

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

**Local modes have no authentication.** The API can expose bounded persisted source/evidence;
real mode can mutate configured workspaces and execute their trusted tests. Keep
DB/config private, restrict local access, and do not expose this host publicly
without a trusted access boundary. Task 16 is not an internet production service.

Task 17 wraps the same ASGI/config/state/assets boundaries with a temporary HTTP
Basic gate in explicit `--preview-demo` mode. Only this mode permits `0.0.0.0`;
it rejects OPENAI_API_KEY and uses only the fake runtime. Credentials are required
from the environment before filesystem/database startup. It never reads local
JSON runtime configuration. The local defaults above remain unchanged. See
[DEPLOYMENT.md](DEPLOYMENT.md) for Docker/Render setup and preview limitations.

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

## Real Project onboarding

**Project identity is persisted. Workspace/runtime configuration is host-owned.**
The CLI connects an existing immutable Project key to its persisted UUID in the
selected database. It never creates a missing Project or stores workspace paths
in Project rows. API/UI/model inputs cannot choose workspaces.

Canonical flow (replace each absolute path with an explicitly selected path):

1. Install/build the prerequisites above. Start a loopback demo host using the
   database you will reuse, for example:
   `qa-sentinel serve --demo --database /absolute/private/state.sqlite3 --frontend-dist /absolute/qa-sentinel/frontend/dist`.
2. Open http://127.0.0.1:8000. Create/select your logical Project in the UI, for
   example key `my-project`. Demo mode configures only Demo Calculator.
3. Stop the host. Prepare a separate **trusted local workspace** and explicit
   pytest targets. Prepared tests/conftest are executable trusted Python code;
   these policies are not an OS sandbox.
4. Generate a config with all trust-bearing paths explicit and absolute:

   ```shell
   qa-sentinel local init --database /absolute/private/state.sqlite3 --frontend-dist /absolute/qa-sentinel/frontend/dist --project-key my-project --workspace /absolute/prepared-project --pytest-target tests --config /absolute/private/qa-sentinel.local.json
   ```

   On Windows use absolute drive paths such as `C:/private/state.sqlite3`,
   `C:/qa-sentinel/frontend/dist` and `C:/work/my-project`. Repeat
   `--pytest-target` to select more prepared targets. No targets are discovered.
5. Run `qa-sentinel local validate --config /absolute/private/qa-sentinel.local.json`.
   Without a local key, the policy/identity checks can pass while the report says
   `OPENAI_API_KEY: MISSING`, `Overall: NOT READY`, exit code 1. This is expected.
6. Supply OPENAI_API_KEY securely through the local process environment, never
   chat, JSON, frontend variables, source or command flags. Validate again:
   a nonblank key yields PRESENT/READY if other checks pass, exit code 0. This
   checks presence only, not validity, model availability, billing or connectivity.
7. Start `qa-sentinel serve --config /absolute/private/qa-sentinel.local.json`.
   Default bind is **127.0.0.1:8000**; optional `::1` stays loopback-only.
8. Open Project Detail and inspect **Runtime readiness**. Configured means the
   host composed the accepted binding; key presence is not provider verification.
9. Create a Project-owned Task, open it and explicitly Run. Execution can call
   models, read bounded repository evidence, apply authorized CREATE/MODIFY and
   run configured pytest. The backend remains authoritative.

### Generation and validation semantics

`local init --help` and `local validate --help` list the narrow argparse flags.
Init writes one Project binding, with deterministic UTF-8 JSON and only database,
frontend_dist, projects (key/workspace_root/pytest_targets), loopback host and port.
It can succeed without a model key; it performs the same inert prerequisites as
validate before publishing configuration. No arbitrary command, executable,
environment, provider object, credential or secret field is supported.

Existing output fails with HOST_CONFIG_EXISTS. `--overwrite` explicitly replaces
the **entire existing valid local host config** with this one binding; it does
not merge multiple bindings. Unrelated/invalid JSON is rejected even with that
flag. Maintain multi-Project configuration manually using the accepted JSON format
and validate the complete file. Missing output parents are created only with
`--create-parent`. Output must be .json, outside target workspaces, frontend assets,
platform source/tests/migrations and protected credential/Git/environment paths.
Links/junctions and hardlinked existing destinations fail closed. Publication uses
a same-directory temporary file, exclusive hardlink for new files and atomic
replace for explicit overwrite; failure leaves the original intact and cleans
the temporary file. Filesystem support for these operations and trusted exclusive
access are required; portable path checks do not provide hostile-race isolation.

Validation reuses HostConfig, frontend checks, RepositoryReadConfig/Service,
MutationConfig/Service and CommandPolicy from real startup. It performs bounded
metadata inspection of **explicitly selected** targets, not test discovery or
source-content reading. It opens existing SQLite with `mode=ro`, requires accepted
schema 0002, and resolves all configured keys through existing persistence reads.
No migration, database creation, Project/Task creation, server start, model adapter
construction, provider call, pytest/subprocess execution or source write occurs.
Missing/old databases must first be initialized/upgraded through normal host
startup. Startup still fails closed for unknown Project keys.

Success reports Project identity FOUND, Workspace/Repository read boundary/Mutation
boundary/Pytest targets VALID, Frontend build FOUND, Database READY, key presence
and Overall READY/NOT READY. Failed checks print only a fixed safe code and
NOT READY, exit 1; argparse usage errors exit 2. Reports contain no source contents,
paths, environment dump or key values. A readiness check is a snapshot, not an
execution guarantee: missing packages, pytest collection behavior, filesystem
permissions/drift and provider failures can still stop Run.

### Host status and UI

`GET /host/runtime-status/{project_id}` is a typed host-only projection **outside
/api/v1**, for one persisted Project UUID. Fields are mode, project_id,
project_key, runtime_configured, model_ready (presence boolean, or null when
unconfigured/synthetic), test_targets_configured. It resolves the composed host
binding without executing it. No workspace, DB/frontend path, target text,
environment value, credential or runtime object is returned. Unknown Projects
keep the existing safe error envelope; the standalone API has no host endpoint.

Project Detail loads this snapshot once and offers **Refresh runtime**. No polling,
automatic retry, provisioning or frontend-owned Run gate is added. Unconfigured
Projects show guidance to init/validate/restart; unavailable status on a standalone
API leaves normal Task controls and safe backend checks unchanged. Local key
presence can be refreshed; targets/configured binding reflect startup composition.

Demo/preview status is synthetic-only: only the seeded Demo Calculator UUID is
configured; model_ready is null and real test targets are false. Arbitrary Projects
remain unconfigured. Preview never inspects real key readiness; the endpoint is
behind the unchanged Basic gate, with only exact GET /health public. No preview
workspace/mutation/test/provider capability is introduced.

Additional safe codes:

- HOST_LOCAL_PATHS_MUST_BE_ABSOLUTE: supply explicit absolute DB/frontend paths.
- HOST_LOCAL_DATABASE_NOT_READY: select the existing initialized 0002 database.
- HOST_RUNTIME_POLICY_REJECTED: workspace violates accepted service boundaries.
- HOST_CONFIG_PARENT_MISSING: select an existing parent or explicitly use --create-parent.
- HOST_CONFIG_OUTPUT_UNSAFE: select a separate ordinary .json output outside protected paths.
- HOST_LOCAL_INIT_FAILED / HOST_LOCAL_VALIDATION_FAILED: check explicit inputs,
  filesystem support/access and the accepted config; no raw failure details are printed.
