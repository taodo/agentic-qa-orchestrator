# Frontend operator dashboard (Tasks 14–15)

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
`/api/v1/*` to `http://127.0.0.1:8000` by default. Configure only the proxy origin
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
| /tasks/:taskId?view=overview | Task operator console → GET /tasks/{id}, GET /tasks/{id}/timeline?limit=100; evidence loads on section open |

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

Run posts once to `/tasks/{id}/run` and waits for synchronous completion. Both
execution controls are disabled while it is pending, with a clear waiting status.
An immediate ref guard prevents repeated same-action requests before React renders.
After either success or a safe stop, Task, timeline and already-opened evidence
panels are re-fetched so committed state/evidence is visible. Backend responses remain the authority; returned state
is never optimistically assigned in the browser.

BLOCKED with a persisted resume_state exposes Resume, posting only `/resume`.
Afterward reads refresh; **no automatic Run occurs**. The operator explicitly
clicks Run separately. Run on BLOCKED does not imply continuation, and terminal
Tasks retain an explicitly labeled idempotent backend check. No transition graph
is reproduced here. No polling, time-based retry, background job, WebSocket or SSE.
These local controls do not serialize separate browser tabs or other clients;
existing backend/host concurrency and reconciliation limits remain unchanged.

## API and safety boundary

Components use Project/Task API functions, not fetch directly. The shared request
helper prefixes `/api/v1`, serializes JSON, returns typed payloads and maps non-2xx
responses to the public error envelope. Bad/non-JSON responses and network/unknown
errors receive generic messages; raw bodies, exceptions and request values are
never displayed or logged. Public messages render as escaped React text. There
is no hidden retry, auth framework, tokens, localStorage/IndexedDB domain cache
or provider access. Transport types are manual mirrors of Task 13 JSON contracts;
they are compile-time types, not a second backend validation/business engine.

GET loading/empty/error states are explicit, with operator-triggered Retry/Refresh.
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
pending Run, durable refresh and separate Resume without auto-run. No real network
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
automatic retry, polling or workflow state simulation.

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
while pending. After Run **or** Resume, Task/Timeline and registered panels refresh,
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
bounded prefixes, manual freshness and in-memory per-Task evidence. No source
editor/diff engine, terminal, analytics, notifications, global state framework,
settings, deployment or auth is implemented.

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
