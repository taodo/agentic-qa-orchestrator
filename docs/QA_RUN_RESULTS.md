# QA Run Results and evidence (Task 4.1)

Results come from immutable QARunTest snapshots and their persisted QA result,
never live Campaign preparation or evidence-text interpretation. No real Campaign
executor is added. Existing Create/Start concurrency, readiness, approval, token,
provider and synthetic lifecycle policies are unchanged.

## Result / evidence write boundary

The pure synthetic evaluation seam is wrapped into a frozen `TestExecutionResult`
containing one completed QA result and 1–20 validated `EvidenceDraft` records.
`QARunRepository.complete_test` revalidates the complete typed result and dispatches
snapshot validation through each draft's registered policy, then writes COMPLETED,
QA result and all evidence in one short reserved transaction. A failed insert or
commit rolls back that test's result/evidence together. Earlier committed tests
survive. No transaction spans executor evaluation.

Ordinary FAIL is COMPLETED + FAIL + evidence, followed by the next test. Mixed
PASS/FAIL finishes Run COMPLETED + FAIL. Execution exceptions stop subsequent
work and keep the accepted FAILED/PARTIAL or FAILED/NOT_EVALUATED semantics.
Interrupted RUNNING tests remain NOT_EVALUATED with no fabricated completion or
evidence; unstarted tests remain NOT_STARTED. Failure to persist the FAILED record
returns the accepted safe PERSISTENCE_ERROR. There is no retry, resume or crash replay.

## Evidence envelope, ownership and safety

`QARunEvidence` is executor-neutral in ownership and lifecycle: UUID, Project,
Campaign, Run, RunTest, sequence, host recorded_at, schema_version, kind, source,
summary and typed payload. It is separate from legacy Task/TestRun/artifact evidence.

- Envelope version: `qa-run-evidence-v1`; kind: `EXECUTION_OBSERVATION`.
- Current admitted source/payload: synthetic only. Payload contains exactly
  discriminator `variant=synthetic-observation-v1`, `strategy=synthetic-position-v1`,
  immutable `position` (1–1000) and observed
  synthetic `outcome` (PASS/FAIL/SKIP). Default fixture returns odd PASS/even FAIL;
  existing trusted test-only injection still exercises SKIP/system failures.
- Summary is exact generated text, e.g. `Synthetic fixture position 2: FAIL.
  No external target was tested.` No arbitrary executor text is admitted.
- Summary bound 512 characters; payload bound 2048 UTF-8 bytes. Unknown payload
  fields, environment/credential/path/header dumps and unsupported sources reject.
  Source identity is bounded to 64 characters; future executors must add explicit
  typed, safe payload variants and source validation, not pass arbitrary dictionaries.
  The common storage envelope does not require new synthetic-specific columns.
- At most 20 evidence records/test, unique contiguous sequences assigned by the
  writer; maximum 1000 tests/Run remains unchanged. The composite FK references
  the full RunTest/Run/Campaign/Project owner identity. Durable record IDs and
  `(run_test_id, sequence)` are unique.
- Frozen domain contracts and insert-only repository behavior are reinforced by
  SQLite UPDATE/DELETE rejection triggers. No HTTP evidence write/edit/delete
  endpoint exists. Direct database replacement/trigger removal is outside the
  application trust boundary; this is not tamper-proof storage.
- recorded_at is the host's real recording time, not a claimed target timestamp.
  Synthetic evidence never claims screenshots, HTTP/browser/DOM observations,
  application/database logs, target filesystem access or StayFinder behavior.

## Closed typed variant / policy boundary (review patch)

The generic envelope and `TestExecutionResult` import `EvidencePayload`, a native
Pydantic discriminated boundary defined in `domain/evidence_variants.py`. Today its
closed `oneOf` contains only `SyntheticObservation`. The immutable policy registry
maps reviewed payload classes and discriminator identities to their validation and
presentation policy. There is no runtime registration API, arbitrary JSON payload,
third-party plugin loading or operator-configured schema.

`SyntheticEvidencePolicy` alone owns source compatibility, supported strategy,
exact safe summary, observation outcome == completed QA result and observation
position == immutable RunTest position. Generic result validation dispatches a policy
hook; generic persistence dispatches snapshot validation. Neither reads universal
`payload.outcome`, `.position` or `.strategy` fields. Atomic write/lifecycle rules
stay unchanged. Unknown classes, discriminators or envelope identities fail closed.

A future reviewed observation variant requires its typed model, policy, addition to
the closed discriminated type alias and explicit registry entry in that module.
The common result, repository, lifecycle and frontend components need no executor
branches. No API/browser/screenshot variant is implemented here. Existing protocol
version/kind continue to apply; protocol changes require separate review.

Pre-patch 0011 payloads lack `variant`. Only the explicitly registered historical
identity may use its typed default discriminator. Reads neither update stored JSON
nor clear/rewrite evidence. Other unknown or malformed identities still reject.

Read-only `QARunEvidenceView` adds a server-derived `presentation`: variant identity,
display_label and at most eight typed text detail pairs. Label bounds are 64 characters,
values 512. The policy constructs this projection from validated payloads; executors
cannot supply it as evidence input and it is not a database column. The generic UI
renders the projection without inspecting raw payload fields. Synthetic labeling and
strategy/position/outcome detail names live in the Synthetic policy only.

### Policy values versus fixed safety invariants

- Source compatibility, display label, detail projection and variant-specific result/
  snapshot validation are reviewed policy values in one closed registry module.
- Executor selection stays at the trusted execution composition boundary. This task
  preserves the existing explicit Synthetic Start; it adds no selection configuration,
  environment-specific paths/URLs/credentials, or new executor.
- Schema/discriminator/strategy versions and `EXECUTION_OBSERVATION` are immutable
  protocol identities. The position-v1 fixture behavior remains versioned, not an
  operator override.
- `MAX_TEST_EVIDENCE=20`, `EVIDENCE_PREVIEW_LIMIT=5`, `MAX_EVIDENCE_BYTES=2048`,
  `MAX_EVIDENCE_SUMMARY_CHARS=512`, identity/detail bounds and existing snapshot/
  pagination limits are fixed domain/security invariants. They cap accepted data,
  memory/output and queries and must not be loosened via configuration.
- Runtime evidence bounds are named in `evidence_variants.py`; API cursor validation
  reuses the application-exported bound. Versioned migration 0011/ORM SQL constraints
  retain their accepted literal limits unchanged. UI explicit evidence read size comes
  from the authoritative test evidence_count rather than a duplicated executor cap.

“Configurable” must not weaken evidence validation. New policies require code review;
no arbitrary schema or secret-bearing payload becomes admissible through configuration.

## Bounded authoritative reads

Under `/api/v1/projects/{project_id}/campaigns/{campaign_id}/runs/{run_id}`:

| GET suffix | Response |
| --- | --- |
| `/results?limit=50&after_position=0` | Run metadata, full persisted summary, bounded tests with evidence count and preview |
| `/tests/{test_id}/evidence?limit=50&after_sequence=0` | Explicit bounded evidence page for one scoped RunTest |

Existing Run/list/snapshot routes remain compatible. Project/Campaign/Run checks
retain existing safe mismatch/not-found errors. A foreign/missing RunTest returns
RUN_NOT_FOUND without disclosing the owner. Shared hosted session/CSRF behavior is
unchanged. Both new operations are read-only and perform no model/provider,
subprocess, target filesystem, mutation, live preparation or executor action.

Results test pages default to 50, maximum 200, with exclusive position cursor
0–1000. Counts cover all persisted tests, not the displayed page: total, completed,
passed, failed, skipped, not_evaluated, remaining. Completed = PASS + FAIL + SKIP;
remaining = NOT_EVALUATED (including interrupted/unstarted/blocked). SKIP is
completed but does not fabricate PASS. Total must match immutable Run test_count;
inconsistent persisted summary fails safely rather than hiding missing snapshots.
Counts are derived SQL visibility, not new workflow truth or stored counters.

A single batched window query supplies exact evidence counts and first five records
per returned test, ordered by sequence. Both preview and explicit pages carry the
same bounded policy-derived presentation without extra SQL or per-record API calls. At most 1000 preview records return for a
200-test page; storage cardinality is separately capped at 20/test. Query count
is independent of page row count. No automatic per-row API/detail fan-out occurs.
The explicit evidence endpoint accepts the existing 1–200 collection limit but
can return at most the stored 20 records/test; its cursor is 0–20. Both collections
expose total_returned/truncated honestly.

## Results workspace

Run Detail shows execution status and QA outcome separately, plus global result
counts above a dense Test Results table. Immutable local key/title and position
identify each test; execution, QA result and evidence count remain distinct.

Shared row disclosure supports broad noninteractive clicks, native summary and
focused-row Enter/Space. Evidence is human-readable with an explicit **SYNTHETIC**
label, source/kind/strategy/position/host time/order and readable summary. Additional
evidence is fetched only by an explicit bounded action after a truncated preview;
controls do not toggle the outer row. Snapshot steps, expected behavior, linked
Requirement snapshot IDs and provenance stay read-only. Required evidence
*descriptions* from preparation are explicitly distinguished from collected evidence.

A FAILED Run explains the system failure and preserves completed QA results and
never-evaluated tests. Historical pre-0011 completed tests show zero evidence with
an honest absence notice; no evidence is backfilled or inferred. Requirement snapshot
context remains available below results, independent of later live revisions.

## Migration and checks

0011 follows 0010, adds `qa_run_evidence` and a composite unique RunTest ownership
key, and preserves all prior snapshot/lifecycle data. Empty-evidence downgrade to
0010 is supported; any saved evidence blocks downgrade before destructive DDL.
Existing older evidence-protecting downgrade guards still apply. Packaged migrations
and the host required revision advance to 0011; local startup still requires an
explicit manual migration when stale, never silently migrates during local start.
No dependencies are added.

Offline regression includes guarded runtime field access proving that result,
persistence and read projection access Synthetic fields only inside its policy,
strict unknown-variant rejection, mismatched outcome/position/strategy checks and
unchanged legacy 0011 JSON reads. A frontend fixture with no readable payload proves
the generic renderer consumes only authoritative metadata.

Offline regression covers FAIL continuation and per-test durability, insert rollback,
late system failure, strict schemas/bounds/immutability/ownership, ordered previews,
constant SQL query count, API scoping/cursors, migration upgrade/reopen/empty downgrade
and evidence-loss refusal, including completed pre-evidence historical Runs.
Frontend regressions cover authoritative totals despite pagination, separate statuses,
readable synthetic evidence, explicit bounded reads, row controls/keyboard, immutable
identity, stale navigation and accepted Start semantics.

## Manual showcase after review

Use synthetic prepared data; no real provider or target is required.

1. Create a Run with three or more approved Test Cases. Confirm creation does not start.
2. Start Synthetic Run. Inspect COMPLETED + FAIL with PASS/FAIL/PASS rows and correct
   global counts. Ordinary FAIL must not hide later results.
3. Open rows by broad click, summary and keyboard; inspect SYNTHETIC evidence and
   immutable step/expected/link context. Buttons/nested controls remain independent.
4. Refresh/navigate/paginate; counts must remain global and reads must not start work.
5. Inspect an old completed Run with no evidence; absence must be disclosed, not filled.
6. Use an offline failure fixture to inspect FAILED/PARTIAL, earlier completed
   results/evidence, interrupted RUNNING and remaining NOT_STARTED tests.
7. Review desktop/narrow scrolling and focus visibility. There is no screenshot,
   HTTP evidence, analyzer, defect, report, real executor or retry/resume UI.
