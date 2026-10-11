# Product UX V2

The primary journey is **Specification → Test Design → Execution → Results**.
A Project owns QA workspaces; each workspace still uses the existing QACampaign
aggregate internally. Overview shows authoritative preparation counts. Project
Settings reads host readiness; it never saves credentials or target paths.
Advanced / Audit retains requirement versions, citations, AI attempts, usage,
traceability and whole-workspace readiness. Existing deep links remain supported.

## Specification

Choose/drop a PDF, DOCX, Markdown or plain-text file, then Upload. Upload is inert;
Analyze specification is a separate explicit model action. Files are held in
memory, never extracted to a filesystem directory. The server validates filenames,
formats, structure and bounds rather than trusting browser MIME.

Uploads are at most 2 MiB. UTF-8 TXT/MD and extracted document text are at most
65,536 bytes and 4,096 LF lines. Complete numbered model context retains its
60,000-character bound: an oversized rendered context fails before a provider
call, rather than silently truncating the specification.

PDF uses `pypdf>=6.20,<7`, a focused parsing dependency needed for safe text
extraction. Encrypted, malformed, unreadable and over-limit documents fail closed.
PDFs have at most 100 pages and bounded stream decoding/page-tree traversal.
DOCX uses standard-library ZIP/XML parsing, with 256 entries, 4 MiB expanded
content and a compression-ratio cap; archive traversal, duplicate entries,
macros and XML DTD/entities are rejected. Relationships/includes are not followed.

This is textual extraction, **not OCR or vision**. PDF always discloses that image
and layout content was not analyzed. DOCX reports body-only/layout limitations
and unexamined embedded media. Page/paragraph ordinals map to normalized LF line
ranges only; there are no fabricated visual regions. Raw-byte hash, text hash,
parser, coordinates and limitations are persisted separately. Source list views
omit full text and coordinate arrays; explicit source detail preserves both. Exact binary identity matters for document deduplication.

Legacy text-entry APIs and historical PDF_UNSUPPORTED records remain readable.
XLSX export is supported; XLSX import remains unsupported.

## Test Design and human review

Supported findings are explicitly reviewed before generation, preserving the
accepted approved-Requirement generation boundary. Choose up to 20 approved
findings per AI generation. Findings needing information remain unresolved.
Generation and analysis audit details are progressively disclosed; viewing,
refreshing, saving facts, approving or exporting never invokes a provider.

READY maps to READY_FOR_REVIEW (or an already approved test), NEEDS_INFO maps to
NEEDS_CLARIFICATION, and DRAFT remains DRAFT. Approval is shown separately.
The backend still validates completeness, current versions and traceability.
Only READY_FOR_REVIEW tests can receive a fresh explicit human approval receipt;
whole-Campaign approval is not required to approve unrelated ready cases.

Test Design pages contain 50 current tests. Search/filter/select-all apply only to
that page. Edits preserve the test key and requirement links, validate the full
structured design and source freshness hash, and create a new immutable human
version with its own facts source and review receipt. The old version is superseded
for current preparation but remains available for historical Runs and audit.
New versions require new approval. Version chains are bounded to 10. Missing
facts cannot be erased while expected behavior/evidence remains incomplete.
Test data is not a separate domain field; exports disclose that honestly.

Add information on the affected test row. Enter expected behavior, facts/reason
and reviewer label; new human facts never masquerade as original PRD text.
Requirement-level clarification/revision remains available in Audit for source
finding ambiguity. The revision prompt no longer includes historical citation
identities in `revision_target`; it explicitly requires active combined-source
identity and an addendum facts range. Existing strict ID/hash/range/excerpt
validation is unchanged. Offline context regression passes; the reported live
EXTRACTION_INVALID_CITATION scenario has **not** been rerun against StayFinder,
so a provider choosing an invalid range may still fail honestly with that code.

CSV and real OOXML XLSX export the explicit current-page selection (backend cap
200 cases / 4 MiB). Requirement labels use batched reads with UUID fallback.
CSV formula-like values are quoted as text; XLSX uses inline string cells, never
formulas. Unrepresentable/oversized spreadsheet cells fail rather than truncate.

## Execution and Results

Execution pages show backend-derived eligibility with a safe reason when blocked.
Select individually or select eligible tests on the page. Selection survives
pagination, is visibly counted, can be cleared, and is bounded to 500 tests.
Run selected revalidates every selected current test, its immutable approval
receipt and its current approved supporting Requirements on the backend.
Unrelated unresolved work does not block that exact selection. Reads and receipt
validation are batched. Create replay is tied to the same idempotency key, note
and exact test identity set. There is no automatic create/start retry.

Explicit selection produces `qa-run-selection-v2`; the global readiness assessment
is recorded honestly, including NOT_READY. Full selected content, original version
identities, links and approval receipts are sealed into an immutable Run snapshot.
No unselected test results are created. Legacy requests without selection retain
`qa-run-snapshot-v1` and their whole-Campaign READY prerequisite. Existing snapshot
hashes, historical results and evidence remain readable.

Execution is **SYNTHETIC only** in these Campaign Runs. No real API/browser/target
execution is introduced. Results preserve Task 4.1 authoritative totals, closed
evidence variants, lazy bounded evidence detail, and historical missing-evidence
notices. Individual FAIL records evidence and continues remaining tests; system
FAILED remains separate. Snapshot hashes and readiness internals sit in Audit
disclosures rather than dominating the result summary.

## API and schema

New Project/Campaign-scoped endpoints under `/api/v1`:
- POST `documents`: bounded base64 upload, no model call.
- GET `execution-candidates?limit=50&after_id=<UUID>`: keyset page, at most 200.
- POST `test-specifications/{id}/edits`: structured human version with previous hash.
- GET `test-specifications/{id}/edit-evidence`: lazy immutable human receipt.
- POST `test-exports`: selected IDs and CSV/XLSX format, literal bounded output.
- POST `runs`: optional `test_specification_ids` (1–500 unique IDs); legacy shape remains valid.

Migration **0012** adds source document/purpose metadata, human test edit receipts
and the selected Run contract version. Migration 0011 is unchanged. Upgrade keeps
historical records and backfills clarification source purposes. Downgrade refuses
if it would discard V2 documents, human review evidence, selected Runs, or collapse
distinct source provenance. It is not a rollback strategy for used V2 data.

Stop the host, back up the actual operator database, and use the private Alembic
configuration documented in [Hosting](HOSTING.md#database-and-migration-lifetime). Run `current`
then explicitly `upgrade head` for that database before restart. Never assume the
repository default database is the operator database. Local start does not migrate.

Local validation/runtime admission requires revision 0012; older 0011 is not V2
ready. An `alembic current` against the checkout's default `qa-sentinel.db` says
nothing about the separate database configured in local JSON. Verify `current`
using the private migration configuration for that exact operator database.
Admission checks the bounded revision marker, not every physical schema object;
a manually stamped/corrupt database still needs explicit schema investigation.
The regression guard also checks that the required runtime revision matches the
available migration head, including installed migration-bundle discovery.

## Validation and manual review

Automated coverage is offline and scoped to the changed components. No external
StayFinder workspace or live provider is used. **FULL SUITES NOT RUN BY USER REQUEST.**

Manual review: migrate a backed-up local database; upload one real file of each
supported format; verify image/layout notices; explicitly analyze and review
findings; generate and edit a NEEDS_INFO test; confirm approval resets; approve
only ready cases; inspect CSV/XLSX in a spreadsheet; select across pages; run the
synthetic selection with unrelated unresolved cases; inspect FAIL plus later PASS
and synthetic evidence; reopen older Runs; use Audit and Project Settings. Manual
browser, real-document/provider and StayFinder verification are not claimed.
