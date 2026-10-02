# Protected public demo preview (Task 17)

Render terminates HTTPS for its generated `https://<service-name>.onrender.com`
address and forwards to one Docker Web Service: HTTP Basic preview gate →
same-origin ASGI host → accepted API/application/core and built React SPA →
deterministic synthetic calculator runtime. This path requires review and user
approval before deployment. No service or public URL was provisioned during
implementation; the repository remains private.

## Security boundary

Only explicit `--preview-demo` permits `--host 0.0.0.0`. Ordinary `--demo` and
real local JSON mode stay loopback-only, including explicit overrides. Preview
has no local project configuration and composes only `division_scenario()` fake
agents and synthetic tests for `demo-calculator`. It never constructs
RealAgentRuntime, OpenAIModelAdapter, RepositoryReadService, MutationService or
the real pytest provider. Other Projects may be created/inspected, but execution
is rejected as runtime-unconfigured. Models, source writes and subprocess test
execution are not available publicly. Existing gates, budgets, reconciliation
and process-wide Run/Resume admission remain unchanged.

Startup requires both process environment variables:

- `QA_SENTINEL_PREVIEW_USERNAME`
- `QA_SENTINEL_PREVIEW_PASSWORD`

Set them through Render's environment settings/Blueprint prompts. Do not paste
them into chat, source, shell command literals, `.env` files, logs or this manifest.
Use a strong distinct password and share access through your existing private
channel. Neither variable has a checked-in default. Missing/blank/invalid values
abort before database creation. Any presence of `OPENAI_API_KEY`, even empty,
aborts preview startup; remove it entirely from the service and shared groups.
Do not attach local runtime configuration or target workspaces.

The gate retains process-random keyed digests, compares both fields in constant
time, and returns a generic 401 plus `WWW-Authenticate: Basic` on missing/invalid
credentials. It protects UI, API, docs, OpenAPI, assets and errors. Only exact
`GET /health` is public, returning `{"status":"ok"}` without configuration or
service calls. Credentials/Authorization headers never enter SQLite or API/UI
responses. Access logging is disabled; startup emits only mode/bind or fixed
error codes. Preview responses include `nosniff`, `no-referrer`, frame `DENY`
and `Cache-Control: no-store`.

This is a shared temporary deployment gate, with no users, roles or sessions.
Browser Basic credentials may be cached for the browser session; close the
session or clear site credentials when finished. Use the generated HTTPS URL
for remote access. No product authentication, public real execution or custom
domain is supplied.

## Image and startup

`Dockerfile` builds with Node 22 and `npm ci`, sets only the public
`PUBLIC_QA_SENTINEL_MODE=preview-demo` label, then builds the SPA. A separate
Python 3.12 package stage installs existing runtime dependencies constrained by
`constraints-preview.txt`. The final Python slim image contains installed code,
unchanged packaged Alembic assets and built SPA, running as UID/GID 10001. It
contains no Node runtime, node_modules, Vite server, Git metadata or local DB.
`.dockerignore` allowlists build inputs and excludes local configuration/state
and secret files. The existing OpenAI package is installed as an accepted package
dependency but no preview provider client is constructed.

Frontend packages and preview Python runtime dependencies have exact resolutions.
Official Node/Python multi-platform base images are pinned by registry-verified
SHA-256 index digests, and the existing setuptools build dependency is pinned
in the builder only. Update these pins through a reviewed maintenance change
when upstream security fixes are needed; byte-identical build timestamps are not
promised. Never put credentials in build arguments or image layers.

The fixed command `python -m qa_sentinel.host.container` reads only provider
`PORT` (default 10000, validated 1–65535), then calls the existing host with
`--preview-demo --host 0.0.0.0`, `/tmp/qa-sentinel/state.sqlite3` and
`/app/frontend/dist`. One Uvicorn worker/process, no reload, no shell glue, no
runtime package installs/builds, no proxy-header trust or WebSockets. The host
owns migration startup exactly as in Task 16. Do not override the command,
scale instances/workers, or launch another host against this database.

## Render setup from the private repository

After review, obtain user approval and integrate the reviewed change into the
accepted `feature/develop` branch through the usual separate review process.
Task 17 itself does not merge branches. The Blueprint deliberately deploys
`feature/develop`, so it must contain these files before initial deployment.

1. Connect Render's GitHub integration and grant access to the private
   `taodo/qa-sentinel-repo` repository. Keep GitHub visibility private; provider
   repository authorization is separate from preview access credentials.
2. Create a Blueprint from that repository, selecting `feature/develop` and
   `render.yaml`. It defines one Docker Web Service, free plan, one instance,
   `/health` health check and no disk, database, worker or other service.
3. Supply both preview variables at the supported `sync: false` prompts. For an
   existing Blueprint service, set missing secrets manually in its Environment
   dashboard; the initial-creation prompt is not an update mechanism. Confirm
   no OPENAI_API_KEY or local-runtime configuration is inherited.
4. Leave Dockerfile/context and Docker CMD unchanged. Render supplies PORT.
   `autoDeployTrigger: off` requires an explicit deploy after reviewed changes;
   no GitHub Actions automation is added.
5. Deploy, wait for a successful health check, and record the assigned
   `onrender.com` HTTPS URL. Open it, authenticate, verify the synthetic notice,
   and follow the workflow smoke below. Do not publish credentials with the URL.

Provider behavior and manifest fields are documented in the official
[Render Blueprint specification](https://render.com/docs/blueprint-spec) and
[Render Docker deployment guide](https://render.com/docs/docker). The build follows
[Docker multi-stage builds](https://docs.docker.com/build/building/multi-stage/).

## Ephemeral state and operator workflow

The preview stores SQLite and the identity-only demo binding under
`/tmp/qa-sentinel/`. State may reset on restart/redeploy or provider recycling.
This includes Projects, Tasks and evidence; do not treat preview records as
durable or enter secrets/production information. A restart that retains the
filesystem reuses the existing seed without duplication; a clean filesystem
starts a new demo database. No paid disk is required. Task 16's default
`~/.qa-sentinel/demo/` local persistence is unchanged. No new migration is added.

After authentication: open Demo Calculator, create a Task such as “Add division
support and reject division by zero”, click Run, then inspect Overview, Timeline,
Artifacts, Invocations, Test Runs, Decisions and Gates. Evidence is synthetic.
New arbitrary requirements still execute the same fixed demonstration scenario.
Run is synchronous; Resume remains a separate explicit action. A second Project
can be created but must receive a safe execution rejection, never a runtime.

## Local Docker verification

Docker was unavailable on the implementation machine (CLI absent from PATH and
standard installation paths). No image build/container pass is claimed. On a
Docker-capable machine, from the repository root:

```shell
docker build -t qa-sentinel-preview .
docker run --rm -p 127.0.0.1:8000:10000 -e QA_SENTINEL_PREVIEW_USERNAME -e QA_SENTINEL_PREVIEW_PASSWORD -e PORT=10000 qa-sentinel-preview
```

Supply the two variables in that shell through your local secret mechanism,
without literal secrets in command history. `-e NAME` forwards their values
without embedding them in arguments. Do not forward OPENAI_API_KEY. Docker must
hold runtime environment values; do not export/share container inspection
output. The published local port is loopback-only. Keep the container running
while executing the following standard-library smoke in a second shell with
the same environment variables (`python -` accepts this block on stdin; on
PowerShell pipe a here-string containing the block to `python -`). It makes
loopback-only HTTP requests, never follows redirects and prints only PASS:

```python
import base64, http.client, json, os

user = os.environ["QA_SENTINEL_PREVIEW_USERNAME"]
password = os.environ["QA_SENTINEL_PREVIEW_PASSWORD"]
token = base64.b64encode((user + ":" + password).encode()).decode()

def request(method, path, *, auth=True, payload=None):
    headers = {"Authorization": "Basic " + token} if auth else {}
    body = None if payload is None else json.dumps(payload)
    if body is not None:
        headers["Content-Type"] = "application/json"
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=30)
    try:
        connection.request(method, path, body, headers)
        response = connection.getresponse()
        data = response.read()
        assert user.encode() not in data and password.encode() not in data
        assert response.getheader("X-Content-Type-Options") == "nosniff"
        assert response.getheader("X-Frame-Options") == "DENY"
        return response.status, data
    finally:
        connection.close()

assert request("GET", "/health", auth=False) == (200, b'{"status":"ok"}')
assert request("GET", "/", auth=False)[0] == 401
assert request("GET", "/api/v1/projects", auth=False)[0] == 401
assert request("GET", "/")[0] == 200
status, data = request("GET", "/api/v1/projects")
assert status == 200
projects = json.loads(data)["items"]
demo = next(project for project in projects if project["key"] == "demo-calculator")
status, data = request("POST", "/api/v1/projects/" + demo["id"] + "/tasks",
    payload={"title": "Division demo", "requirement": "Add division support and reject division by zero"})
assert status == 201
task = json.loads(data)
assert request("POST", "/api/v1/tasks/" + task["id"] + "/run")[0] == 200
status, data = request("GET", "/api/v1/tasks/" + task["id"])
assert status == 200 and json.loads(data)["state"] == "DONE"
for collection in ("timeline", "artifacts", "invocations", "test-runs", "decisions", "gates"):
    assert request("GET", "/api/v1/tasks/" + task["id"] + "/" + collection)[0] == 200
assert request("GET", "/projects/" + demo["id"])[0] == 200
for path in ("/.env", "/.git/config", "/render.yaml", "/Dockerfile", "/state.sqlite3"):
    assert request("GET", path)[0] == 404
print("PASS: protected deterministic container preview")
```

Also inspect the browser at http://127.0.0.1:8000 for **DEMO PREVIEW · Synthetic**
and evidence tabs. Stop/recreate the container and verify that ephemeral records
reset. Confirm unauthenticated health still succeeds and no credential/header
values appear in application logs. Do not dump the container environment.

## Regression checks and troubleshooting

Run the full Python suite, frontend `npm ci`, `npm test -- --run`, `npm run build`
and `git diff --check`. Preview integration tests use temporary migrated SQLite,
ASGI TestClient, synthetic credentials and denied external sockets/provider
calls/subprocesses. They verify bind separation, fake-only composition, safe
authentication, credential exclusion from responses/logs/SQLite, static
containment, startup/PORT behavior and existing local hosting. Normal tests do
not require Docker or an API key. Package/image build downloads are prerequisites,
not demo workflow network calls; execution requires no external network.

- `HOST_PREVIEW_CREDENTIALS_REQUIRED`: configure both nonblank environment values;
  username cannot contain a colon; control characters/oversized values are rejected.
- `HOST_PREVIEW_MODEL_KEY_FORBIDDEN`: remove OPENAI_API_KEY entirely.
- `HOST_PREVIEW_PORT_INVALID`: retain Render's numeric PORT; do not override bind.
- 401 at UI/API: check credentials in the provider dashboard and browser prompt;
  never debug by printing Authorization headers or environment values.
- Build failure: verify private GitHub authorization, accepted branch contents,
  lockfiles and Docker support; do not enable real runtime or weaken access gates.
- Failed health/startup: check fixed error codes and writable ephemeral directory;
  host startup owns migrations. See HOSTING.md for safe host readiness errors.
- Runtime-unconfigured Project: use Demo Calculator; arbitrary Projects are
  intentionally not executable in preview.
- Missing records: ephemeral state was recycled; create a new synthetic demo Task.
- Basic access to Swagger/ReDoc remains gated, but those optional accepted pages
  use external UI assets. They are not needed for the offline SPA/workflow.
