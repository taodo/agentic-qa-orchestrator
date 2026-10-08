# QA Run preparation snapshots (Task 3.3)

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
are NOT_EVALUATED, PASS, FAIL, SKIP. No forward transitions or result assignment
operations exist yet. Future individual assertion FAIL is a QA outcome: record
its evidence and continue remaining eligible tests. It must not become execution
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

Contracts are frozen, and the repository is insert-only; no snapshot edit/delete
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
and packaged Alembic resources include 0008. Empty-Run downgrade to 0007 is supported;
nonempty-Run downgrade stops before erasing historical evidence. No dependency added.

Offline tests cover atomic creation/rollback, complete selection beyond default
collection size, invalid readiness/stale receipts, key replay/conflict, concurrent
same/distinct/conflicting requests, persisted historical reads after live changes
and DB reopen, bounded API errors/pagination, schema constraints, migration roundtrip,
and zero model/tool/executor/legacy-evidence effects.

Task 3.4 owns Run lifecycle UX / a synthetic execution shell. No frontend Run controls,
executor binding, result/evidence aggregation, queue, retries, stop/resume or reporting
are implemented here. Preserve the independent statuses and immutable contracts.
