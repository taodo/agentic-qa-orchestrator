# QA Run snapshots and synthetic lifecycle (Tasks 3.3–3.4)

A `QARun` is a durable Project → Campaign child. Creating one freezes approved
preparation and does not start execution. It creates no legacy Task, ExecutionJob,
workflow event, ModelRequest, token-usage record, tool or executor action. It needs
no source repository, target runtime, URL, credentials or provider configuration.
Campaign preparation and existing extraction/generation usage remain unchanged.

## Status contracts

A new Run has `execution_status=CREATED`, `qa_outcome=NOT_EVALUATED`, and null
`started_at`/`completed_at`. Reserved execution values are CREATED, QUEUED, RUNNING,
COMPLETED, STOPPED, FAILED; outcomes are NOT_EVALUATED, PASS, FAIL, PARTIAL.
A new `QARunTest` has `execution_status=NOT_STARTED`, `qa_result=NOT_EVALUATED`.
Reserved test progress values are NOT_STARTED, RUNNING, COMPLETED, BLOCKED; results
are NOT_EVALUATED, PASS, FAIL, SKIP. Task 3.4 implements CREATED → RUNNING → COMPLETED / FAILED and
NOT_STARTED → RUNNING → COMPLETED. QUEUED, STOPPED and BLOCKED remain reserved,
without operations. Individual assertion FAIL is a QA outcome: record its result
and continue remaining eligible tests. It must not become execution
FAILED, which is reserved for execution-system failure. Preparation APPROVED/READY
never means PASS.

## Eligibility and immutable content

Creation uses accepted `assess_readiness` and SQL readiness counts, requiring READY.
It then loads **all** approved Requirements and Test Specifications, validates full
approval receipt hashes using the accepted review repository, revalidates typed
content, validates same-Project/Campaign links and complete coverage, and persists
one atomic snapshot. Unapproved/clarification/blocked tests are excluded. Extra
unapproved Requirements still block readiness, exactly as before.

Run metadata copies Campaign identity/name/objective/APPROVED status, full readiness
at creation, counts, note and creation timestamp. Separate Run-owned Requirement
and Test rows copy complete existing immutable domain content, original UUIDs,
logical/local keys, acceptance criteria, source citations with excerpts/hashes,
ordered test steps/expected results/evidence, provenance, review status and original
approval receipts/content hashes. Tests reference the copied Requirement snapshot
UUIDs as well as original Requirement IDs. Original preparation UUIDs are audit
identities, not foreign keys needed to reconstruct live content. Snapshot reads
never recompute current readiness or load live Requirement/Test bodies.

Contracts are frozen, and snapshot fields remain insert-only; no snapshot edit/delete
API exists. This is an application immutability contract, not a tamper-proof database.
Direct operator database edits are outside that boundary. Domain validation checks
copied content against its approval hash on reads. Migration downgrade refuses to
erase persisted Runs.

Each selected set is bounded to 1,000 Requirements and 1,000 tests; the complete
serialized prepared snapshot is bounded to 16 MiB. Exceeding either bound fails
with RUN_SNAPSHOT_SIZE_LIMIT before any insert. Nothing is silently omitted.
Snapshot bodies inherit all existing per-field bounds. Only approved metadata is
queried; no source-document reread, repository/filesystem/network/subprocess work
occurs. Source citations retain the approved audit evidence, not whole PRDs.

## Canonical identity, ordering and retries

`qa-run-snapshot-v1` SHA-256 fingerprints canonical UTF-8 JSON (sorted object keys,
compact separators, Unicode preserved, non-finite values rejected). It includes
Campaign identity/name/objective/status and ordered full Requirement/Test facts,
links and approved content-version hashes. Content versions retain the accepted
review hash, which intentionally includes the original immutable record creation
time. Run UUID, run number, caller key/note, snapshot/approval wall-clock timestamps,
live readiness counts and generated child UUIDs are excluded. Two intentional
Runs of unchanged preparation therefore share a hash while retaining distinct IDs.
Hash is audit identity, never a cache or duplicate-creation policy.

Requirements and tests sort by `(logical_key, original UUID)` with contiguous
one-based positions. Child UUIDs are derived from `(run UUID, kind, original UUID)`.
The Run exposes a positive Campaign-scoped `run_number`, usable as RUN-001 etc.
The application reserves SQLite's writer with the accepted `qa_job_write` /
`BEGIN IMMEDIATE` transaction before reading ownership, idempotency or readiness.
Within that transaction MAX(run_number)+1 is protected; DB uniqueness constraints
also guard Campaign/run-number and Campaign/idempotency-key identities. Run + all
children commit together or roll back together. SQLite is the supported database;
contention/timeouts retain the existing safe PERSISTENCE_ERROR, with no hidden retry
or exactly-once/distributed-lock claim. There is no deletion operation or number reuse.

Every create requires a caller key: 1–128 ASCII letters/digits/`_.:-`, beginning with
a letter/digit. Same Campaign + same key + same note (including null) returns the
original durable Run, even if live preparation later becomes NOT_READY. Same key
with a different note returns RUN_IDEMPOTENCY_CONFLICT. A different key intentionally
creates a new Run, including when the snapshot hash matches. Keys are retained for
the Run lifetime; no expiry/cache or inferred retry is added.

## Application / API

All routes share `/api/v1/projects/{project_id}/campaigns/{campaign_id}/runs`:

| Method / suffix | Application operation / response |
| --- | --- |
| POST empty suffix | `create_qa_run` → QARun (201, including replay) |
| GET empty suffix | `list_qa_runs` → CollectionPage[QARun] |
| GET /{run_id} | `get_qa_run` → QARun |
| POST /{run_id}/start | `start_qa_run` → final QARun (200) |
| GET /{run_id}/tests | `list_qa_run_tests` → CollectionPage[QARunTest] |
| GET /{run_id}/requirements | `list_qa_run_requirements` → CollectionPage[QARunRequirement] |

Create body: `{"idempotency_key":"operator-request-001","note":"RC validation"}`.
Note is optional inert text (1–1,000 characters when supplied); extra fields are
rejected. JSON body, including streamed bytes, is capped at 8 KiB before parsing.
All collections default to 50, maximum 200, with total_returned/truncated. Runs
sort by descending run_number. Snapshot lists sort by position and accept
`after_position` (0–1,000, exclusive), allowing complete bounded reconstruction.
Run detail contains metadata and summary counts, not unbounded children.

Project/Campaign ownership uses accepted scoped-child checks. All Run queries also
filter Project/Campaign/Run together. An unknown or foreign-Project Run returns the
same RUN_NOT_FOUND (404), concealing foreign Project existence. A metadata-only
check inside the validated Project scope distinguishes RUN_CAMPAIGN_MISMATCH (409)
when that Project owns the Run under a different Campaign. Existing PROJECT_NOT_FOUND,
CAMPAIGN_NOT_FOUND and PROJECT_CAMPAIGN_MISMATCH mappings remain compatible.
CAMPAIGN_NOT_READY_FOR_RUN and RUN_IDEMPOTENCY_CONFLICT are 409;
INVALID_IDEMPOTENCY_KEY is 422; request/snapshot size limits are 413;
stale approval evidence retains REVIEW_EVIDENCE_INVALID (409). Persistence errors
use the existing safe envelope without raw input/exception logging or disclosure.
Hosted auth/CSRF composition protects these routes unchanged.

## Migration, validation and handoff

0008 adds only qa_runs, qa_run_requirements and qa_run_tests, with composite owner
FKs, unique Run numbers/keys, unique child originals/positions and separate constrained
progress/outcome columns. 0004–0007 data and legacy schema are unchanged. Host startup
and packaged Alembic resources include head 0009. Empty-Run downgrade to 0007 is supported;
nonempty-Run downgrade stops before erasing historical evidence. No dependency added.

Offline tests cover atomic creation/rollback, complete selection beyond default
collection size, invalid readiness/stale receipts, key replay/conflict, concurrent
same/distinct/conflicting requests, persisted historical reads after live changes
and DB reopen, bounded API errors/pagination, schema constraints, migration roundtrip,
and zero model/tool/executor/legacy-evidence effects.

## Task 3.4 synchronous synthetic execution

Start accepts an absent body or `{}`, never target settings, credentials or an
outcome override; its body has the same 8 KiB bound. Only CREATED can start.
RUN_INVALID_STATE (409) rejects a double/concurrent Start and terminal restart.
The existing SQLite writer reservation protects the state check plus RUNNING claim.
That claim commits before any evaluation. Each test separately commits RUNNING,
evaluates outside a database transaction, then commits COMPLETED and its QA result
before the next test. A rejected concurrent Start never evaluates tests. There is
no job/queue, distributed lock, hidden retry, resume or exactly-once claim.

`SyntheticRunExecutor` accepts only persisted `QARunTest` snapshots. The explicit
**synthetic-position-v1** fixture revalidates frozen content and approval, then
returns PASS for odd one-based snapshot positions and FAIL for even positions.
Position is immutable and part of snapshot identity. Titles/priorities have no
semantic effect; identical snapshots reproduce the same result. This is a
lifecycle demonstration, not an evaluation of test assertions against a target.
No model, external network, browser, subprocess, repository/target filesystem,
URL, credentials, source mutation or legacy workflow service is used. No legacy
Task/job/invocation/artifact/TestRun/token evidence is created. Campaign readiness
and live Requirement/Test Specifications are not reread during execution.

Every normal FAIL is saved as COMPLETED + FAIL, and later tests continue. Final
aggregation reads persisted bounded Run tests: any FAIL → FAIL; otherwise at least
one PASS with remaining PASS/SKIP → PASS; all SKIP → NOT_EVALUATED. In every normal
case the Run is COMPLETED. System exceptions stop later processing, preserve all
committed earlier results and mark Run FAILED with only RUN_EXECUTION_FAILED.
Outcome is PARTIAL if a test completed, otherwise NOT_EVALUATED. A test interrupted
in RUNNING remains RUNNING / NOT_EVALUATED: no completion is fabricated. Internal
trusted/test-only adapter injection exercises failure and SKIP cases; HTTP exposes
no injection or outcome controls. A FAILED Run is returned as durable state (200),
not a raw exception.

Migration 0009 adds only nullable `qa_runs.execution_error_code`, constrained to
RUN_EXECUTION_FAILED or null. Existing CREATED snapshots backfill null and remain
unchanged. It adds no table or redundant result counters. Only status/outcome,
Run timestamps and safe code update; content, receipts, original IDs, links and
positions never update. Downgrade to 0008 is permitted for CREATED-only data but
refuses any execution history before losing lifecycle evidence.

Stop is deferred for the bounded synchronous shell. No automatic crash recovery
or replay is implemented: process termination or an unrecoverable persistence
failure may leave RUNNING evidence. Refresh inspects saved progress; never infer
completion or restart it. If recording FAILED also fails, the API returns safe
PERSISTENCE_ERROR; it does not pretend the failure record was saved.

## Campaign Runs UX

Campaign navigation includes Runs. The bounded list shows Run number/UUID, created
time, short hash, separate execution/outcome, counts and note. READY enables explicit
Create; NOT_READY displays accepted blocker guidance and a Readiness link. Each
intentional new create gets a fresh UUID key; explicit retry retains the same key
and note. No mutation auto-retries, including after auth failure. Successful Create
opens immutable Run detail without starting it.

Detail reads only stored Run metadata, Requirement snapshots and Test snapshots.
It shows full hash, readiness-at-creation, captured Campaign, approval/source
provenance, expected behavior and required evidence descriptions. Snapshot lists
fetch 50 at a time with explicit next-page cursors and truncation notices, never
automatic detail fan-out. Later Campaign changes cannot alter these views.

Both views state **Synthetic execution** and **No external target is tested in this
mode.** Results carry a Synthetic label, never fake screenshots/network traces or
editable PASS/FAIL fields. CREATED exposes Start Synthetic Run. Pending Start is
disabled with “Running synthetic execution…”; no fake incremental animation or
polling is shown. Completion refreshes Run and tests. Safe conflicts refresh saved
state without retrying Start. Terminal Runs have no Start/retry/resume controls.
Shared same-origin CSRF/auth transport and latest-request/unmount guards remain.

The offline showcase freezes three approved tests, changes live Campaign content,
then proves PASS → FAIL → PASS, all COMPLETED, final Run COMPLETED + FAIL, immutable
snapshots, DB reopen durability and no legacy evidence. Additional tests cover
concurrent Start, terminal rejection, partial system failure, all-SKIP honesty,
bounded requests/pagination, migration roundtrip and browser action intent.

Phase 4 can build read-only evidence/analysis/reporting over these durable facts.
Real API execution (Phase 5), browser/Playwright execution (Phase 6), target settings,
analyzer, defects, reporting,
retry/resume and source repair remain outside Task 3.4.
