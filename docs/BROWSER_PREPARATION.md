# Browser Execution Preparation — Task 5.8A

Preparation records what the operator selected before a QA Run. It is not a QA Run,
not browser execution evidence, and not a PASS/FAIL/SKIP result.

## Human approval and absent traceability

The internal application command `review_source_free_campaign_test` uses the explicit
`source-free-browser-test-v1` policy through the existing scoped review transaction
and immutable human approval receipt. A complete imported/human-edited Test with no
Requirement references can be approved by a named human reviewer. Its
`MISSING_TRACEABILITY` marker is retained as informational provenance. Explicit
unresolved references, other information markers, missing expectations/evidence,
unapproved or superseded identities still reject. AI-generated Tests retain their
existing required links. The generic approval action and specification-driven
Campaign readiness remain unchanged; no Requirement or READY status is invented.

## Snapshot compatibility

`qa-run-browser-v3` is explicitly WEB_BROWSER-only. It permits zero immutable
Requirement snapshots and empty Test snapshot links only when approved Test content
has no Requirement IDs. Existing links must resolve exactly to Run-owned approved
Requirement snapshots. Every browser Test still requires an exact sealed plan, Target
hash, Test hash, runtime identity and ownership validation. Actual Runs contain at
least one Test. Historical v1/v2 rules and fingerprint bytes remain unchanged.

Run Test version context comes from the owning Run and is excluded from serialized
Test content and persistence; it is reapplied on detached reads/revalidation. The
fingerprint includes snapshot version and, when present, the preparation ID. Historical
null preparation links do not contribute any new fingerprint bytes.

There is no new public Run creation path or preparation-to-Run materializer in 5.8A.

## Durable intent and bounds

`create_browser_preparation` and `get_browser_preparation` are internal application
methods. They persist/read `browser-preparation-v1` with immutable Project/Campaign
ownership, captured WEB Target, requested HEADLESS/HEADED mode, idempotency key and
all 1–500 selected approved Test versions in caller selection order. Duplicate IDs
reject. Selection fingerprints bind full approved content, receipt, position, Target
and mode. The serialized aggregate is limited to 16 MiB; oversized complete selections
fail instead of truncating. No source workspace or repository configuration is needed.

Creation revalidates current Test versions/receipts under the accepted SQLite writer
reservation. Same key and unchanged sealed inputs return the existing record; different
selection/order/Target/mode rejects. Superseded/invalid current input rejects rather
than silently repinning it. A successful read always uses the persisted Target and
Test snapshots, independently of subsequent live changes.

## Explicit lifecycle and interruption

Aggregate: CREATED → PREPARING → COMPLETED or FAILED.
Items: PENDING → PREPARING → RUNNABLE, NEEDS_ATTENTION or SYSTEM_ERROR.

The repository exposes only whitelisted lifecycle commands. Starting an item creates
a durable attempt UUID and timestamp. A terminal write must present that exact attempt
UUID. RUNNABLE requires only typed future grounding/observation/plan identity hooks;
5.8A stores no grounding payload and performs no grounding itself. NEEDS_ATTENTION
has fixed information/ambiguity/unsupported/policy reason codes. SYSTEM_ERROR and
aggregate failure have fixed system/interruption codes, never raw exceptions.
COMPLETED means every selected item has a preparation outcome, including mixed ones;
it does not mean every item is runnable. Failure preserves pending/started/terminal
items as recorded. Restart and idempotent creation never restart PREPARING work.
There is no retry/resume worker; future reconciliation must assess uncertain attempts
explicitly. Terminal rows and terminal item outcomes cannot be rewritten or deleted.

## Future Run relationship

Nullable `QARun.preparation_id` is an immutable composite ownership FK and a unique
link: zero or one resulting Run per preparation. The read view derives
`resulting_run_id` from that stored relationship; no Run is claimed when absent.
The contract admits links only for browser-v3 Runs backed by a completed preparation
with runnable items. Repository admission checks the exact runnable Test subset,
approvals, Target and plan hashes. This is a validation hook, not orchestration;
5.8C will own materialization and combined Results. Historical Runs keep null links.

## Migration and safety

Migration 0016 preserves existing rows and Run triggers while conditionally evolving
snapshot counts/version constraints. Runtime preflight now requires 0017. Stop the
host and explicitly migrate the configured operator DB with the existing documented
Alembic procedure. Normal startup never migrates automatically. Downgrade to 0015
refuses source-free approval, preparation or browser-v3 history rather than erasing
or making it unreadable; empty compatible schemas can downgrade/re-upgrade.

No new dependency, HTTP route, frontend workflow, provider call, Target visit,
Chromium launch, source mutation, automatic Browser Facts injection, or change to
BrowserExecutionPolicy/0015 planning receipts is introduced. Browser mode is recorded
intent only; actual headed runtime wiring belongs to 5.8D. Machine observations and
safe structured grounding belong to 5.8B. Phase 5 remains product-incomplete pending
those child tasks and the parent epic's manual acceptance smoke.

Task 5.8B now backs future grounding hooks with explicit immutable observation and
grounding receipts; see [grounding](BROWSER_GROUNDING.md). It does not itself finish
items as RUNNABLE or create/seal a QA Run. The no-side-effect statements above describe
the 5.8A create/read foundation; explicit B grounding is a separate trusted internal call.
