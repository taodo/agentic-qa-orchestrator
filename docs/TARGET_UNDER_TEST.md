# Target Under Test

**Target != Workspace != Executor.**

A Target Under Test is the external system QA Sentinel evaluates. Source-code
repository access is optional and is not required for black-box Target execution.
Repository/workspace configuration must never be used as an implicit substitute
for Target configuration. Actual black-box execution is future work: the current
Campaign executor is **SYNTHETIC**, and never visits or verifies the configured URL.

## Domain and selection

A Project owns multiple Targets. WEB is the only implemented type. Each has a UUID,
Project UUID, bounded name, environment (LOCAL/DEVELOPMENT/STAGING/PRODUCTION/OTHER),
closed configuration with `base_url`, and creation/update timestamps. No arbitrary
plugin/environment/credential fields exist. There is no delete operation.

Each Campaign explicitly selects zero or one same-Project Target. No default is
inferred. Selection is persisted separately from metadata/status; changing it does
not change preparation lifecycle, approval, readiness or eligibility. Project
Settings configures Targets; workspace creation and Overview offer explicit
selection. No source repository/runtime binding is required for these operations.

## URL policy

Validation is structural and offline. Accept ASCII HTTP/HTTPS DNS names (including
localhost/punycode) or IP literals, valid optional ports 1–65535 and paths, up to
2048 characters. Scheme/hostname are lowercased. Explicit ports, trailing dots,
path case and percent escapes are preserved; no slash is inserted. Reject embedded
credentials, whitespace/control characters, backslashes, malformed escapes/ports,
unsupported schemes and **all query/fragment delimiters**, even empty ones. These
are base URLs, not credential-bearing request URLs. Meaningful query URLs are
rejected rather than silently rewritten. Invalid input is not echoed by the API.

No DNS, HTTP fetch, connection probe or browser navigation occurs. Reachability,
future SSRF/network policy and credential handling belong to deliberate executor
work, not configuration validation. URLs are displayed as inert text.

## API

All routes below start at `/api/v1/projects/{project_id}` and preserve host auth,
CSRF, safe errors and Project scoping:

- POST/GET `/targets`: create/list, default 50 and maximum 200, deterministic UUID order.
- GET/PATCH `/targets/{target_id}`: scoped read/update typed fields only.
- GET/PUT `/campaigns/{campaign_id}/target`: read selected Target or null; explicit
  `{"target_id":"UUID"}` or `{"target_id":null}` selection/removal.
- POST `/campaigns` also accepts optional `target_id`; legacy bodies remain valid.

New Target write bodies are bounded to 8 KiB; Campaign creation allows 32 KiB
to preserve the existing Unicode metadata bounds. Collections use limit+1 truncation,
without per-row fan-out. Target access outside its owning Project returns a safe 404.

## Run evidence and migration

Run creation, inside the existing reserved writer transaction, freezes the selected
Target as `web-target-snapshot-v1`: target/project IDs, name, type, environment and
base URL. This optional sub-contract is included in the existing snapshot fingerprint
only when present. The existing Run snapshot version remains compatible. Persisted
Target snapshots are immutable; SQLite rejects updates. Idempotent creation replay
returns the original Run and snapshot. Results uses stored context, never a live
Target join. Target edits and Campaign reassociation cannot rewrite old Runs.

Migration **0013**, parent **0012**, adds `targets_under_test`, `campaign_targets`
with composite ownership foreign keys, and nullable `qa_runs.target_snapshot`.
Upgrade does not recreate Campaign/Run tables, invent Targets or rewrite legacy
hashes. Historical Campaigns show "Target not configured"; historical Runs disclose
that Target information was not captured. Used Target/association/snapshot data
blocks downgrade; empty downgrade/re-upgrade is supported. Runtime admission requires
0013. Stop the host, back up the configured database and migrate explicitly using
[Hosting](HOSTING.md#database-and-migration-lifetime); startup never auto-migrates.

## Future boundary and manual review

Future executors should consume **Approved Test Snapshot + Target Snapshot**, without
requiring application source. Planned API/ANDROID/IOS Target variants and browser
(Playwright)/API/mobile executors are not implemented. SYNTHETIC PASS/FAIL reflects
demonstration outcomes; individual FAIL continues eligible tests, while system
failure is execution FAILED. No executor semantics change in this increment.

Manual review after explicit migration: create a WEB Target without a workspace;
choose it in a Campaign; prepare/approve eligible tests; create a Run with a staging
URL; change the Target to production; confirm old Run/Results still shows staging
and a new Run captures production. Check legacy absent states, cross-Project safe
errors, hosted login/CSRF and unchanged synthetic warnings. This checklist does not
prove target reachability or real web execution.
