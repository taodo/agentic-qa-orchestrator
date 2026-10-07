# Campaign test specifications (Task 2.3)

Two explicit paths converge on one durable executor-neutral Campaign child:
existing CSV/Markdown import and AI design from selected structured Requirements.
Neither executes tests, changes [Campaign preparation](CAMPAIGNS.md), nor creates
Task, ExecutionJob, workflow invocation/event, test-run or mutation evidence.
No repository, target URL, runtime binding or executor is required by the domain
or application. Individual future test FAIL remains a QA outcome: this preparation
contract defines no execution outcome or fail-fast policy.

## Normalized design contract

CampaignTestSpecification contains immutable UUID, Project/Campaign ownership,
source-qualified logical key, document-local key, title, linked requirement UUIDs,
test_type, priority, preconditions, ordered steps, overall_expected_result,
required_evidence, information_markers, unresolved_requirement_refs, provenance,
review_status and aware timestamps. Steps have contiguous one-based index, action
and expected text (or explicit null for unknown behavior). These are human-readable
instructions, never executor payloads. No selector/request/command/SQL schema is
accepted. API, WEB and DATA are descriptive labels only, not supported executors.

Types: FUNCTIONAL, REGRESSION, SMOKE, NEGATIVE, BOUNDARY, INTEGRATION, API, WEB,
DATA, OTHER. Priority: LOW, MEDIUM, HIGH, CRITICAL. Review: DRAFT,
NEEDS_CLARIFICATION, READY_FOR_REVIEW and (Task 2.4) APPROVED. Any information
marker derives NEEDS_CLARIFICATION; otherwise newly produced specs are
READY_FOR_REVIEW. Neither status certifies behavior or coverage. Task 2.4 owns
[explicit review/approval/readiness](CAMPAIGN_REVIEW.md).

Bounds per case: key 1–64 uppercase letters/digits/underscore/hyphen, title 200
characters, preconditions at most 20 x 512 characters, 1–20 steps (action/expected
at most 2,000 characters each), overall result at most 4,000 characters, evidence
at most 20 x 512 characters, markers at most 20 x 512 characters, and at most 20
linked/unresolved requirement references. Unknown expected behavior or absent
evidence requires a MISSING_INFORMATION marker. Extra executor/configuration
fields and out-of-order/duplicate step indices are rejected.

## Deterministic import

POST test-imports accepts JSON name, format (CSV/MARKDOWN/XLSX) and content.
The application also accepts bounded bytes, allowing honest invalid-UTF-8/binary
rejection. It does not read server paths or use models to parse input.

Input max 65,536 original UTF-8 bytes, 4,096 LF lines, and 100 cases. Normalization
utf8-nfc-lf-v1 removes an initial UTF-8 BOM, normalizes document text to NFC and
CRLF/CR to LF, otherwise retaining whitespace/trailing newline. It does not
canonicalize JSON escapes, cell layout or case order into a generic semantic
cache. SHA-256 identifies original bytes and normalized document text.

Source POST, test-imports POST and generate-tests POST reuse the accepted streamed
512 KiB pre-JSON request-body guard. Decoded import content still obeys the smaller
byte limit. Oversize returns SOURCE_SIZE_LIMIT (413) with no import record.
Malformed schema, invalid UTF-8, binary controls, duplicate case keys, too many
cases/lines and unsupported XLSX produce REJECTED import metadata with a fixed
safe code, zero cases and no retained parsed text. No partial cases are inserted.
A valid import and all specs/links commit atomically.

XLSX is recognized but REJECTED / XLSX_UNSUPPORTED. The bundled environment has
openpyxl, but it is not a project dependency. No spreadsheet dependency/parser,
ZIP/XML processing, formula evaluator, macros or package installation is added.
A future narrowly reviewed parser must define accepted worksheet/column contracts
and compressed-file/row/cell bounds. There is no pandas dependency or PDF work.

All imported content is inert data. Formulas such as =HYPERLINK(...), scripts,
URLs and embedded prompt text remain strings, are never evaluated/followed, and
never become policy authority. The importer uses only standard-library CSV/JSON
parsing and typed domain validation.

### CSV contract

UTF-8 CSV uses comma delimiter and standard double-quote quoting. Required header
order is exact, with no extra/duplicate columns:

```text
key,title,requirement_refs,test_type,priority,preconditions,steps,overall_expected_result,required_evidence,information_markers
```

key/title/test_type/priority are plain cells. All other cells are JSON:

| Column | JSON shape |
| --- | --- |
| requirement_refs | Array of exact UUIDs/keys as strings; [] allowed |
| preconditions | Array of descriptive strings |
| steps | Array of objects: index, action, expected (string or null) |
| overall_expected_result | String or null (JSON quotes are required for a string) |
| required_evidence | Array of descriptive strings |
| information_markers | Array of objects: kind, description |

Each physical CSV record becomes one case; quoted multiline cells are supported
within the total line/byte bound. Provenance records inclusive normalized physical
line range, starting after the header. JSON rejects duplicate object keys and
NaN/Infinity; object/array shapes and field bounds are validated, with no expression
evaluation. Blank required cells do not become default values.

### Markdown contract

Exact document heading # Test cases, then one section per case: ## KEY followed
immediately by a json fenced object and closing fence. Blank lines are permitted
between sections. The JSON fields match CSV's typed case fields except key,
which comes only from the heading. Arbitrary prose/tables/includes and additional
fields are rejected; this is a template parser, not general Markdown or AI parsing.

````markdown
# Test cases

## LOGIN
```json
{
  "title": "Sign in",
  "requirement_refs": ["LOGIN"],
  "test_type": "FUNCTIONAL",
  "priority": "HIGH",
  "preconditions": ["Existing user"],
  "steps": [{"index": 1, "action": "Sign in", "expected": "User is signed in"}],
  "overall_expected_result": "User is signed in",
  "required_evidence": ["Observed sign-in state"],
  "information_markers": []
}
```
````

Section provenance is its inclusive normalized heading-to-closing-fence line
range. Formats are separate import identities even when they describe similar cases.

### Import traceability and identity

References resolve only within the same Campaign, with Project ownership checked
first. UUIDs resolve exactly; otherwise source-qualified logical keys or an
unambiguous document-local requirement key can resolve. There is no fuzzy matching.
An unknown, foreign or ambiguous reference is preserved in unresolved_requirement_refs
with UNRESOLVED_REQUIREMENT. No known link adds MISSING_TRACEABILITY. Such cases
remain imported and NEEDS_CLARIFICATION, not fabricated or silently discarded.
Known IDs are unique and canonically ordered. Foreign requirement existence is not
revealed through import resolution; it is simply unresolved in this Campaign.

One immutable result per Campaign + format + normalized hash + test-import-v1.
Repeated input returns the same import/spec identities, retaining first name/raw
hash and original mapping decisions. Later requirements do not silently rebind an
existing unmapped import. Changed text creates a new snapshot, preserving earlier
specs. Logical keys include the origin UUID; UUIDs derive from origin UUID +
contract + case key. There is no overwrite/rebind/delete/update endpoint.

## Explicit AI design

POST generate-tests accepts only 1–20 unique selected Requirement UUIDs, all owned
by the same existing Project/Campaign. No caller-supplied model, tool, shell,
workspace or generation settings are accepted. Unknown/cross-scope selection fails
before a provider call. The existing PLANNER role/model is specialized with a
schema-native GeneratedTestsOutput through the existing Responses model adapter.
Tools and provider storage remain disabled; SDK retries are disabled. No new role,
workflow framework, provider client or Task ReliabilityService retry loop is added.

Context contains every selected structured Requirement, including acceptance
criteria, source references and information markers. It contains no raw PRD,
Campaign history, unrelated requirements/artifacts, repository files or secrets.
Canonical ordering and selected IDs are explicit. Complete serialized context
must fit the existing 60,000-character ModelRequest bound, or
GENERATION_CONTEXT_LIMIT (422) occurs before reservation/provider work. No batching,
truncation or omitted-selection claims are introduced.

The prompt treats all supplied text as untrusted data and prohibits guessing product
behavior or inventing IDs. Supported happy/negative/boundary/state/concurrency
cases are requested only where the requirement supports them. Output is revalidated:
all selected IDs echoed exactly, at most 100 unique keys, at least one supplied
requirement ID per generated test, and at most 131,072 serialized UTF-8 bytes.
Identical structured cases (ignoring key/title/priority/markers, canonicalizing link
order) are rejected; semantic paraphrase equivalence cannot be proven deterministically.
An empty test list may honestly mean no supported design; it does not imply coverage.

Required clarification facts from each linked Requirement are merged into the
canonical spec even if the model omits them. Identical typed markers are reused;
distinct required markers are never truncated. More than 20 combined markers
fails the output honestly instead of creating a false READY_FOR_REVIEW case.
Missing expected behavior must use null and an explicit marker. Citations and
structured links cannot prove semantic correctness or that a model obeyed every
instruction; human review remains required.

### Generation durability and idempotency

Canonical selected Requirement UUIDs + SHA-256 fingerprints of their complete
structured snapshots + test-specs-v1 define request identity, scoped to Campaign.
Permuted selection produces the same identity; changed selection or requirement
snapshot produces another identity. Model configuration changes alone do not
silently replay the same versioned request. There are no optional generation knobs.

One attempt per request identity persists STARTED before one provider call, closing
its transaction before model work. Terminal attempt/metadata and all specs/links
commit atomically afterward. Repeated SUCCEEDED/FAILED returns the same result;
STARTED returns GENERATION_RECONCILIATION_REQUIRED. Crash or failed completion
persistence never silently replays the provider, inserts partial designs or
fabricates usage/completion. No retry/reconciliation action endpoint exists yet.
This policy does not claim exactly-once external execution.

## Persistence, API, usage and handoff

Alembic 0006 adds campaign_test_imports, campaign_test_generations,
campaign_test_specifications and campaign_test_requirement_links. Composite
foreign keys enforce Project/Campaign/origin/link ownership; a related unique
Campaign Requirement identity index supports Requirement links. Bounded ordered
steps/conditions/evidence/markers/provenance/selected snapshot fingerprints use
JSON consistent with existing typed storage. No unrelated core columns/lifecycle
change. Downgrade to 0005 removes these four tables and supporting index, preserving
all earlier Campaign/source/requirement/Task/evidence/job records. Host/package
migration registration moves to 0006. Dependencies added: NONE.

Under /api/v1/projects/{project_id}/campaigns/{campaign_id}:

| Method and suffix | Operation |
| --- | --- |
| POST /test-imports | Deterministic import; 201 with IMPORTED/REJECTED metadata |
| GET /test-imports | Bounded metadata list, no normalized document replay |
| GET /test-imports/{import_id} | Lazy detail with complete accepted normalized input |
| POST /generate-tests | Explicit design from selected Requirement UUIDs |
| GET /test-generations | Bounded attempt/status/usage list |
| GET /test-generations/{generation_id} | Safe attempt/status/usage result |
| GET /test-specifications | Bounded executor-neutral designs and links |
| GET /test-specifications/{test_spec_id} | One design and immutable provenance |

Lists default 50, valid 1–200, retrieving limit+1 and reporting honest truncation;
order is oldest UTC created_at/started_at, then UUID. Child ownership mismatch is
409, missing records 404, malformed/extra/bounded request data 422. All use cases
check Project/Campaign scoping. No generic metadata update/approval API is added.
[Existing API](API.md) and Task 2.1/2.2 operations remain compatible after migration.

[Campaign model usage](MODEL_USAGE.md) combines bounded extraction and generation
attempts, with PLANNER / TEST_SPEC_GENERATION as observational identity/purpose,
not TaskState or QA Run. Per-attempt input/output/total/reasoning usage remains
provider-authoritative, including real reported zero. Missing usage stays unknown
with missing_records; known_sum remains partial and truncated complete totals
remain null. Context-size diagnostics and bounded top consumers remain available.
Cost stays NOT_CONFIGURED/null without pricing configuration. Import has no model
usage. Raw provider responses, prompts, refusal text and hidden reasoning are not
stored in attempt records or operational responses.

Real generation is injected only by trusted local composition (loopback policy
unchanged). demo/preview-demo/hosted-demo have no real generator and return
GENERATION_NOT_CONFIGURED for valid explicit selections. Deterministic synthetic
imports remain usable under existing Basic/session/CSRF protections. No public
real executor, runtime/mutation or provider access is introduced. The application
works with an empty runtime registry; existing host-local workspace onboarding is
unchanged, not redesigned into a source-only operator profile here.

Task 2.4 can use stable designs, exact Requirement links, origin evidence and
clarification statuses for explicit approval/coverage/readiness. Those operations,
executors, QA Runs/results, defects and dashboard UX are not implemented in Task 2.3.
