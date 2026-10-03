# Hosted synthetic demo access — Task 23

This is a single-operator portfolio access boundary, not production multi-user
identity/RBAC. There are no accounts, roles, registration, reset, invitations,
OAuth or auth/session database tables. Persistence does not enable real execution.
Only Demo Calculator has FakeAgentRuntime and FakeTestResultProvider. Other
Projects can be inspected but remain runtime-unconfigured. No OpenAI adapter,
real agent, repository reader, mutation service or real pytest service is composed.
Any presence of OPENAI_API_KEY aborts startup, even an empty value.

## Provider secrets

Supply QA_SENTINEL_OPERATOR_USERNAME, QA_SENTINEL_OPERATOR_PASSWORD and
QA_SENTINEL_SESSION_SECRET through the provider's runtime environment secrets.
Never put them in chat, source, build arguments, files, browser storage or logs.
Username/password must be nonblank, controls-free and at most 1024 UTF-8 bytes
each; Unicode control/format/surrogate characters are rejected. Username rejects
colon, semicolon, equals, comma, backslash and quotes.
Signing secret must be independently generated, controls-free, 32–1024 UTF-8
bytes and different from credentials. Use a cryptographically random value,
not a repeated character or memorable password. Only process-random keyed
credential verifiers and signing material survive preflight in host objects.
The environment remains provider-owned; no credential enters SQLite or responses.

## Login and session

Exact GET /health, GET /login and POST /auth/login are the only public routes.
The minimal server-rendered login form loads no SPA or external assets. It carries
an independent random form proof paired with a signed ten-minute HttpOnly cookie;
login requires the pair. Cross-site Fetch Metadata and mismatched/non-HTTPS Origin
are rejected. Proxy headers are never trusted. The login body is limited to
8192 bytes with exactly three unique fields. Credential comparisons use keyed
SHA-256 digests and constant-time comparison of both username and password.
All failures return the same generic message without reflection.

Successful login sets a versioned HMAC-SHA256 stateless session cookie and redirects
to /. The bounded encoded payload contains only purpose/version, issued/expiry
times and independent random session/CSRF nonces. No credential/config/path is
encoded. Constant-time MAC verification and strict field/lifetime validation
protect it. The __Host-qa-sentinel-session cookie has Secure, HttpOnly,
SameSite=Strict, Path=/ and no Domain. Always use HTTPS, including when testing
browser login locally; HTTP cannot send this Secure cookie. Session expiry is
fixed at eight hours, with no sliding renewal. Same-secret restart preserves
valid sessions; rotate the signing secret to invalidate every issued session.

All app/API/assets/docs/host readiness/reconciliation routes require the cookie.
Invalid/expired API access gives fixed HOST_AUTH_REQUIRED (401); HTML navigation
redirects to /login. No request or workflow is replayed after authentication.
POST /auth/logout requires CSRF, clears cookies and redirects to /login.
Stateless logout clears this browser's cookie; a copied cookie remains valid
until expiry or signing-secret rotation. Logout/expiry never cancel jobs, change
Task state or clear uncertainty. Background fake-only queued work keeps its
accepted Task 20 lifecycle independent of browser sessions.

## CSRF and browser transport

Authenticated GET /auth/session returns only mode=hosted-demo and the independent
session-bound CSRF proof. This proof cannot authenticate by itself. The SPA reads
it before mounting, retains it only in memory and supplies X-QA-Sentinel-CSRF for
POST/PATCH/PUT/DELETE, including logout. Missing, duplicate, wrong-session and
cross-site proofs fail with HOST_CSRF_REQUIRED (403) before application work.
Reads need no proof. CORS stays disabled. Origin/Fetch Metadata checks supplement
the proof; absent Origin alone does not authorize an unsafe request.

On HOST_AUTH_REQUIRED the client navigates to login once and blocks further
transport in that page. No state-changing action is retried. After sign-in,
inspect refreshed Task state, execution history and reconciliation before any
new explicit action. SUCCEEDED still does not mean Task DONE; Resume stays
separate and synchronous; evidence remains lazy. The header is added only for
hosted sessions; Basic preview and local/demo requests are unchanged.

Hosted responses use nosniff, no-referrer, frame DENY and no-store. CSP permits
same-origin scripts/connections, no objects or embedding, and same-origin form
actions. Inline styles support accepted React styling; inline scripts are blocked.
Optional Swagger/ReDoc external assets are blocked by this hosted CSP; use the
authenticated OpenAPI JSON or accepted SPA. Access logs remain disabled.

## Operational limits

One bounded process-wide rolling window admits ten login attempts per minute,
including successful attempts, and stores only at most ten monotonic timestamps.
It is not IP-aware and resets on process restart; an attacker can exhaust it and
temporarily deny login. Provider/WAF rate limiting and private credential sharing
remain the owner's operational responsibility. No distributed throttle, CAPTCHA
or external service is added.

SQLite and evidence are durable only on the selected persistent disk. Host startup
owns the accepted Alembic upgrade. Use exactly one service instance/process,
Uvicorn worker and execution worker. There is no distributed coordination,
horizontal scaling, exactly-once execution or zero-downtime guarantee. Preserve
uncertain STARTED evidence and follow [reconciliation](RECONCILIATION.md).
[Deployment profiles](DEPLOYMENT.md#optional-persistent-hosted-demo-task-23).
