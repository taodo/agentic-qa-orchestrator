# Frontend foundation (Task 14)

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
| /tasks/:taskId | Task metadata and persisted timeline → GET /tasks/{id}, GET /tasks/{id}/timeline?limit=100 |

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
implementation/defect/review counters and terminal reason. Timeline displays only
returned persisted entries, in exactly API order, with timestamps/type/summary,
actor and approved compact details. It never sorts UUIDs or invents events.
Truncated collections explicitly disclose that more records exist; there is no
unbounded download or generalized pagination in this phase.

## Run and Resume

Run posts once to `/tasks/{id}/run` and waits for synchronous completion. Both
execution controls are disabled while it is pending, with a clear waiting status.
An immediate ref guard prevents repeated same-action requests before React renders.
After either success or a safe stop, Task and timeline are re-fetched so committed
state/evidence is visible. Backend responses remain the authority; returned state
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

Current limits: trusted local/dev API without auth, separately composed backend,
bounded collection prefixes and basic Task timeline only. Task 15 can add richer
artifact/invocation/test/error/decision/gate inspection after review and approval.
No Task 15 observability tabs, source editor/diff viewer, terminal, analytics,
notifications, global state framework, settings, deployment or auth is implemented.
