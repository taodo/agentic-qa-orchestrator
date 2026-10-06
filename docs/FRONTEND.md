# Frontend operator dashboard (Tasks 14–24)

## Operations monitoring (Task 24)

Primary navigation now includes /operations: global text summary cards, bounded
Task/Project tables and safe recent activity with existing detail links. TaskState
and job lifecycle are separate; SUCCEEDED is never shown as Task DONE. DB-only
reconciliation attention is triage, never a full CLEAR assessment or permission
to execute. Task Detail adds only Back to Operations; lazy evidence is preserved.

Project/Task-state/attention-only/active-only filters live in URL queries; invalid
values show resettable errors. Four GETs form one serialized cycle, waiting seven
seconds after settlement while visible. Partial failures still await all requests;
no overlap, stale-filter publication, hidden scheduling or polling after navigation.
Task 23 login recovery stops expired reads without replaying writes. Manual Refresh,
discreet last-updated, text statuses, labelled filters, table captions and contained
keyboard-accessible horizontal scrolling support narrow layouts. Selected Project
runtime readiness is fetched once separately, never per-row or on every cycle.
[Full behavior and limits](OBSERVABILITY.md). No dependency or auth change.

For first-time operation, start with [Product Guide](PRODUCT_GUIDE.md) and
[Feature Reference](FEATURES.md). Earlier task-specific startup/scope statements
below describe their checkpoint; Tasks 16–17 provide local and protected demo
hosting, Task 18 adds static onboarding/copy, Task 19 adds host readiness, and
Task 21 uses Task 20 durable execution jobs for browser Run.

The Web is a local operator/control dashboard over the accepted Task 13 API.
React, TypeScript and Vite live in the separate `frontend/` workspace. Python/core
packages and backend contracts are unchanged. The browser displays backend-owned
Project/Task state; it does not simulate transitions, evaluate gates or persist
domain objects locally.

## Structure and dependencies

- `src/main.tsx`: React root and BrowserRouter.
- `src/app/`: shell, route definitions and a small latest-request-wins read hook.
- `src/api/`: manual public transport types, one request helper, Project/Task calls.
- `src/components/`: feedback, forms, state badges, dates and timeline.
- `src/pages/`: Projects, Project Detail and Task Detail.
- `src/styles/`: responsive operator dashboard styles.
- `src/test/` and adjacent test files: mocked-fetch fixtures, Vitest/RTL tests.

Runtime dependencies: React, React DOM and React Router DOM. Development dependencies:
Vite, TypeScript, the React Vite plugin, React/React DOM/Node type declarations,
Vitest, jsdom, React Testing Library and jest-dom. There are no UI/global-state/date
frameworks or OpenAPI code generators. Exact resolved dependencies are committed
in package-lock.json; node_modules/dist/Vite caches are ignored.

## Development and build

Use Node.js 22.12+ (tested with 22.17.1) and npm:

```shell
cd frontend
npm install
npm run dev
```

For reproducible installs use `npm ci`. Vite binds to localhost and proxies
`/api/v1/*` to `http://127.0.0.1:8000` by default. Task 19 also proxies the narrow
`/host/runtime-status/*` read namespace to the same host. Configure the origin
through `VITE_API_PROXY_TARGET`, for example in your shell or a local ignored
`.env.local`. The Vite configuration loads this value on the host and uses a
different browser env prefix so the proxy variable is not bundled into client
JavaScript. No secrets belong in frontend environment variables.

```shell
npm test -- --run
npm run build
```

Build runs `tsc -b` with strict checks, then Vite production compilation. The
frontend calls relative same-origin `/api/v1` paths in production too. Vite's proxy
is development-only; a future host must provide appropriate same-origin routing
and SPA route fallback. No backend production bundling/deployment is provided.

Backend startup still requires a separately and explicitly composed
`create_api_app(application)` host. Task 14 does not add uvicorn/bootstrap, fabricate
default runtime bindings, change CORS or claim a one-command full-stack launcher.
The UI shows safe API errors when no backend is listening.

## Screens and routing

`/` redirects to `/projects`; unknown paths render Not Found.

| Route | Screen and API reads |
| --- | --- |
| /projects | Project registry → GET /projects?limit=50 |
| /projects/:projectId | Project metadata and tasks → GET /projects/{id}, GET /projects/{id}/tasks?limit=50 |
| /tasks/:taskId?view=overview | Task operator console → GET /tasks/{id}, GET /tasks/{id}/timeline?limit=100, GET /tasks/{id}/executions?limit=10; evidence loads on section open |

All API paths above have the `/api/v1` prefix. Sidebar navigation contains only
the implemented Projects destination. Detail screens link to related persisted
Project/Task IDs; no fabricated Tasks index or settings route is added.

Projects shows name/key/update time and a labeled inline create form. Create sends
key/name/description, then explicitly refreshes the server-owned collection.
Project Detail shows description, timestamps, ID and its scoped Task list. Create
Task sends only title/requirement under the Project path; no body ownership field
exists. Forms retain values on error, give basic required-field feedback, disable
during submission and use an immediate in-flight guard. Server validation remains
authoritative. Success does not create local IDs or optimistic workflow state.

Task Detail shows requirement, canonical state, IDs/timestamps, resume target,
current invocation, implementation/defect/review counters and terminal reason. Timeline displays only
returned persisted entries, in exactly API order, with timestamps/type/summary,
actor and approved compact details. It never sorts UUIDs or invents events.
Truncated collections explicitly disclose that more records exist; there is no
unbounded download or generalized pagination in this phase.

## Run and Resume

For nonterminal Tasks, Run posts once to `/tasks/{id}/executions`, accepting a 202
job snapshot. The execution panel separates QUEUED/RUNNING/SUCCEEDED/STOPPED/FAILED
from the header's persisted Task state. SUCCEEDED means the application returned
normally; it never sets DONE or proves tests passed. When the tracked request
becomes terminal, Task, Timeline, execution history and only already-opened
evidence panels refresh. Run/Resume are disabled while checking history, submitting,
refreshing terminal evidence or while a job is active. Initial history failure
requires explicit recovery before controls become available.

BLOCKED with a persisted resume_state exposes Resume, posting only `/resume`.
Afterward reads refresh; **no automatic Run occurs**. The operator explicitly
clicks Run separately. Run on BLOCKED does not imply continuation. DONE/FAILED
Tasks retain **Run (terminal check)** through synchronous `/run`; they never enqueue.
No transition graph is reproduced here. Backend admission and ownership remain
authoritative across browsers; these controls do not provide distributed locking.

## Execution recovery and polling (Task 21)

`api/executions.ts` checks response shape, exact job statuses, timestamp/code
lifecycle, Task/job identity and bounded collections, selecting only safe fields.
It retains no queue sequence, runtime or unknown response field. GET requests use
no-store. `useTaskExecution` owns a per-Task session with serialized reads and a
single **1500 ms timeout after each settled poll**, rather than overlapping interval
ticks. It polls only QUEUED/RUNNING; terminal jobs, navigation and unmount clear
timers and abort/discard pending responses. Status text has a polite live region;
unchanged poll snapshots do not announce another tick. Native controls/disclosure
and wrapping metadata keep recent history usable on narrow screens.

Mount/reload reads the newest ten persisted execution requests, in backend order,
recovering an active request without creating one. Recent terminal history does
not poll. A duplicate POST error reads history and recovers the server's active
job. POST creation is never automatically retried, including network uncertainty;
uncertain creation performs only a recovery GET. GET polling failures retain the
active identity and show fixed guidance, with conservative active-only GET retry
and **Refresh execution history**. A missing-job 404 stops its polling, reads
history and offers safe recovery guidance; the same missing identity stays paused
until explicit refresh. All POSTs/reads are guarded against stale route sessions.
History checking cannot race creation, and manual reads cannot overlap a poll.

No browser persistence, global state, job retry/cancellation, WebSocket/SSE or
cross-Project job dashboard is added. Recoverability depends on the host/database;
preview state remains ephemeral. Standalone API factories need the documented
host worker. The frontend does not infer host liveness from TaskState or grant
execution from readiness. Preview remains Basic-protected deterministic synthetic
only; real local mode uses the same transport under existing backend safeguards.
[Execution contracts and restart limits](EXECUTION_JOBS.md).

## API and safety boundary

Components use Project/Task API functions, not fetch directly. The shared request
helper prefixes `/api/v1`, serializes JSON, returns typed payloads and maps non-2xx
responses to the public error envelope. Bad/non-JSON responses and network/unknown
errors receive generic messages; raw bodies, exceptions and request values are
never displayed or logged. Public messages render as escaped React text. There
is no hidden POST retry, auth framework, tokens, localStorage/IndexedDB domain cache
or provider access. Existing Task/evidence types mirror Task 13 JSON contracts;
execution transport adds defensive runtime parsing for the Task 20 job contract.
Neither is a second workflow/business engine.

Evidence GET loading/empty/error states are explicit, with operator-triggered Retry/Refresh.
The read hook discards stale responses after navigation/re-fetch; detail components
reset by route identity. All mutation feedback stays within the current screen.
Dates use browser-local presentation, retaining the exact API timestamp in a title;
invalid dates do not crash. Canonical states always show text as well as color.

The shell uses semantic links/buttons/headings, labeled native forms, focus styles
and a skip link. Desktop lists/forms align in two columns; narrow viewports stack
navigation, forms and metadata. No modal keyboard trap or clickable div action.
No accessibility certification is claimed.

## Verification and remaining scope

Vitest/jsdom/React Testing Library tests mock every fetch and forbid unmocked fetch
and XMLHttpRequest. They cover routing, Project/Task forms and isolation, stale
navigation reads, safe errors, date/state rendering, API-order timeline, single
pending creation, active recovery, nonoverlapping/stale-safe polling, terminal job
refresh without inferred DONE and separate Resume without auto-run. No real network
or provider call is made by these tests. A supplementary headless browser check
uses intercepted in-memory API fixtures to inspect desktop screens and the
390-pixel layout; those fixtures are not part of the product or a backend bootstrap.
The full Python regression suite remains required.

## Task Detail operator console (Task 15)

Task Detail uses semantic section links, with the selected section in `?view=...`.
The choices are Overview, Timeline, Artifacts, Invocations, Test Runs, Errors,
Decisions and Gates. Links are keyboard accessible and expose `aria-current`.
Direct URLs, reload and Back/Forward retain the selection; invalid values show
Overview. Run/Resume and their feedback remain above the sections on every view.

Overview and Timeline load initially, including on a deep-linked evidence view.
Other sections mount only when first opened and retain in-memory data while the
operator switches sections within that Task. There is no eager evidence fetch,
automatic evidence retry/polling or workflow state simulation.

| Section / query value | Existing Task 13 endpoint | Presentation |
| --- | --- | --- |
| Overview / overview | GET /tasks/{id} | Requirement, state, IDs, timestamps, counters and persisted reasons |
| Timeline / timeline | GET /tasks/{id}/timeline?limit=100 | API order, actor, details, correlation IDs |
| Artifacts / artifacts | GET /tasks/{id}/artifacts?limit=100 | Metadata, producer, schema, supersession and expandable JSON |
| Invocations / invocations | GET /tasks/{id}/invocations?limit=100 | Agent, model, reasoning effort, attempt, status, times and error ID |
| Test Runs / test-runs | GET /tasks/{id}/test-runs?limit=100 | Separate outcome/execution status, counts, environment and artifact IDs |
| Errors / errors | GET /tasks/{id}/errors?limit=100 | Persisted type/severity/owner, flags, message, references and approved source fields |
| Decisions / decisions | GET /tasks/{id}/decisions?limit=100 | Persisted routing type/source/reason and evidence references |
| Gates / gates | GET /tasks/{id}/gates?limit=100 | Persisted result, individual check results/reasons and blocking reasons |

All paths have `/api/v1` prepended by the shared typed request helper. API calls
remain in `api/tasks.ts`. `EvidencePanel` reuses the latest-request-wins read hook,
with independent loading/error/empty states, explicit Refresh and an opened-panel
refresh registry. Refresh updates only the selected collection and is disabled
while pending. After an async request becomes terminal, a terminal check **or** Resume, Task/Timeline and registered panels refresh,
including after safe-stop errors. Unopened panels are never fetched merely because
an action completed. Both execution controls remain disabled through the refresh.
Task route identity remounts the console; late reads are discarded and an action
that completes after navigation does not start reads against the old Task.

All collections are bounded prefixes. `truncated: true` displays an explicit
notice; `total_returned` does not claim the database total. No unbounded load-all
or pagination is implemented. Returned list/timeline order is preserved.

Record renderers select public DTO fields explicitly. No prompt, input context,
raw provider response, stdout/stderr or hidden reasoning fields are displayed.
Artifact `content` is the approved public JSON supplied by the API: a short
collapsed preview appears by default and Expand/Collapse reveals the complete
pretty-printed structure. Controls expose `aria-expanded`/`aria-controls`.
React escapes all JSON, reasons and messages as text; no raw HTML renderer,
JSON editor, local file read, evidence logging or mutation control exists.

Each enum domain has its own typed presentation helper; Task states, invocation
statuses, test outcomes/execution statuses, gate results and error severities are
not mapped into new workflow states. Correlation IDs use wrapping monospace text.
There is no inferred relationship lookup or optional clipboard behavior.

Compact semantic lists and definition lists wrap at narrow widths; JSON has a
bounded visual height and internal scrolling. Section links wrap, focus remains
visible, and loading/empty/error feedback uses status/alert semantics. Desktop
remains primary and no accessibility certification is claimed.

Task 15 tests additionally cover lazy/isolated evidence requests, section URL and
history, metadata/status fields, JSON expansion, literal malicious-looking text,
private-field exclusion, truncation, stale route reads and action refresh of only
opened panels. Fetch/XHR remain mocked/forbidden and tests make no real network or
provider calls. Python backend contracts and dependencies remain unchanged.

Current limits: trusted local/dev API without auth, separately composed backend,
bounded prefixes, manual evidence freshness and in-memory per-Task evidence. No source
editor/diff engine, terminal, analytics, notifications, global state framework,
settings or product auth is implemented. The current full-stack host and temporary
preview Basic gate are documented in the Task 16–17 sections below.

The required `npm ci` audit reports two moderate entries in the existing Vitest
3.2.7 development dependency chain (`vitest` and `@vitest/mocker`, advisory
GHSA-82fw-gwwq-j7x9). Task 15 does not change the accepted dependency lockfile or
add a test server/UI. A future dependency maintenance change can assess the major
version upgrade separately; the production bundle does not include Vitest.

## Task 16 same-origin local hosting

After `npm ci` and `npm run build`, `qa-sentinel serve --demo` serves this unchanged
build and the accepted `/api/v1` API through one loopback ASGI host. Relative API
requests and history refreshes work directly; Vite/proxy is not started by the host.
Missing dist/index fails startup. Demo Calculator's description identifies the
synthetic workflow; the global local-workspace label and transport contracts are
unchanged. See [HOSTING.md](HOSTING.md) for offline demo, explicit real local config,
single-process admission, private SQLite state and security limitations. The older
Task 14 startup limitation above describes that task's scope; Task 16 supplies the
supported local host without production/public deployment.

## Task 17 preview indicator

The Docker frontend build sets `PUBLIC_QA_SENTINEL_MODE=preview-demo`. The shell
then displays **DEMO PREVIEW · Synthetic**, with a title explaining that no live
AI, source mutation or real test execution occurs. Other values retain the local
operator label; environment values are never displayed. This is public build-time
information only, not a mode-selection or authorization mechanism. No credentials,
new API endpoint, browser storage or authentication code enters the bundle.
The host enforces preview isolation independently of this label. Same-origin API
requests use the browser's HTTP Basic authentication after the initial challenge.
See [DEPLOYMENT.md](DEPLOYMENT.md) for the protected preview deployment path.

## Task 18 lightweight product onboarding

Projects now introduces QA Sentinel and explains how to open a Project, create
a Task, Run its configured workflow and inspect evidence. A native button opens
an inline **How QA Sentinel works** panel with Project/Task/Run/Resume distinctions,
the canonical Division support input and a clear synthetic-demo limitation.
Project creation helper text states that identity creation does not configure
execution. Task Execution copy describes completion/safe stops and separate Resume.

The button is keyboard-focusable with native Enter/Space activation,
aria-expanded/aria-controls and the existing focus styling. Hidden content is
inline, not a modal; there is no focus trap or new route. The panel uses fluid
width, wrapping text/control and the existing narrow-screen layout. Local component
state is discarded on navigation; there is no analytics, browser storage, tutorial
framework, API call or added dependency. The Task 17 preview label is unchanged.
Tests cover visibility, expansion/collapse, focus/semantics, exact demo wording,
no extra requests, preview indicator and unchanged Project navigation. See
[Product Guide](PRODUCT_GUIDE.md#demo-mode) and [PRD](PRD.md).

Supplementary checks against the production SPA use mocked API fixtures at
1280px and 390px widths, verifying native Enter/Space activation, no horizontal
overflow, unchanged routing and no help-triggered request. No screenshot assets
or screenshot-automation tooling are added.

## Real Project onboarding

Project Detail reads `GET /host/runtime-status/{project_id}` once after Project
identity loads, then offers native **Refresh runtime**. A typed allowlist retains
only mode, Project UUID and readiness flags, checks response ownership and discards
unknown fields. The host also returns the immutable key, which readiness does not
display. No workspace, database path, test target text, environment value or key
value is displayed. API v1 contracts and Task Run/Resume controls are unchanged.

Configured local status shows key **Present (not verified with provider)** or
**Missing**, Tests Configured and trusted workspace ownership guidance. Missing
configuration explains persisted identity vs host runtime and init/validate/restart.
Configured demo/preview is explicitly deterministic synthetic only; arbitrary
Projects remain unconfigured based on the host's resolution, never frontend key
matching. The preview shell notice and Basic gate are unchanged.

Status is nonblocking and manually refreshed, without polling or auto-retry.
Backend Run remains authoritative. An unavailable standalone host endpoint shows
fixed safe guidance without hiding Task controls or rendering server failure
bodies. Route identity resets readiness; late responses after navigation are
discarded by the existing read hook. No new storage, dependency or provisioning
UI is added. Tests cover safe fields, modes, unavailable status, explicit refresh
and stale navigation. [Setup](HOSTING.md#real-project-onboarding).

## Recovery / Reconciliation (Task 22)

Task Detail adds one no-store assessment read and a compact panel with Clear,
Recoverable, Manual action required or Inconsistent. Fixed kind-based guidance
and UUID references are allowlisted; arbitrary server summaries, paths, exceptions
or provider fields never enter this panel. Native Refresh reconciliation rereads
only the assessment, with no POST, auto-fix, wizard, polling or storage.

Run/Resume wait for a valid assessment and respect its separate advisory safety
flags. Unavailable/unknown assessment keeps controls disabled until explicit
refresh; backend entry-point checks remain authoritative. Existing latest-read
and keyed Task routing discard late responses on navigation/unmount. Job terminal
and synchronous-action evidence refresh also reread reconciliation without opening
lazy evidence sections. Job status never changes TaskState. Preview remains
synthetic fake-only and Basic-protected. [Meaning and limits](RECONCILIATION.md).

## Hosted session transport (Task 23)

Production bootstrap reads the host-owned GET /auth/session before mounting the
existing app. Only hosted-demo's validated independent CSRF proof is held in
module memory; no credential, cookie or unknown projection field is retained or
rendered. Local/demo/Basic host mode projections, standalone 404 and Vite's HTML
fallback retain the existing non-session behavior. The optional runtime status
allowlist also accepts hosted-demo without exposing configuration.

The shell shows HOSTED DEMO · Synthetic and Sign out only after hosted bootstrap.
Unsafe POST/PATCH/PUT/DELETE calls carry X-QA-Sentinel-CSRF in that mode, including
one explicit logout POST. The HttpOnly cookie is managed by the browser; no
localStorage/sessionStorage is used. HOST_AUTH_REQUIRED (401) navigates to /login
once and stops further transport from that page. No action is replayed. Logout
errors keep explicit retry; a session-bound CSRF failure never triggers a retry.
The minimal login form belongs to the server; no SPA/assets load before auth.

TaskState/job/reconciliation/polling ownership and lazy evidence behavior stay
unchanged. Sign-in recovery requires fresh history/state inspection, and sign-out
does not cancel backend work. Narrow topbars wrap, keeping logout accessible.
Production CSP allows existing same-origin bundles/styles and blocks external
script assets. [Hosted access](HOSTED_ACCESS.md) documents expiry and trust limits.
