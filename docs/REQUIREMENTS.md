# Campaign sources and structured requirements (Task 2.2)

A Campaign can ingest specifications without a source repository, workspace,
URL, executor or Task. Ingestion and semantic extraction are separate explicit
operations. Neither changes Campaign preparation status, creates a Task or
ExecutionJob, nor enters a workflow stage. The [Campaign lifecycle](CAMPAIGNS.md)
remains DRAFT -> READY_FOR_REVIEW -> APPROVED through explicit transitions.
Requirement review status is independent; READY_FOR_REVIEW is not approval.

## Deterministic source ingestion

The API accepts JSON content, not server filesystem paths or multipart uploads:

```json
{"name":"Checkout PRD","source_type":"MARKDOWN","content":"# Checkout\nA signed-in user can check out.\n"}
```

TEXT and MARKDOWN use the same bounded parser. Content is untrusted data: the
parser does not render Markdown, follow URLs, resolve includes, run scripts,
inspect repositories or call models. Normalization version utf8-nfc-lf-v1:

1. Enforce at most 65,536 original UTF-8 bytes; decode strictly as utf-8-sig.
2. Remove an initial UTF-8 BOM, normalize Unicode to NFC, and replace CRLF/CR
   with LF. Preserve other whitespace and trailing newline.
3. Reject non-text control characters except tab/LF, empty text, or more than
   4,096 lines. Line numbers start at 1; split on LF, including a final empty line.
4. Compute SHA-256 of original bytes (raw_hash) and normalized UTF-8 text
   (content_hash). Keep normalized text, line count and character length.

Oversized input fails with SOURCE_SIZE_LIMIT (413) without a source record.
Invalid UTF-8, binary controls, empty text and excess lines produce immutable
REJECTED records with safe error codes and bounded hash/size metadata, no text.
HTTP source POST bodies also have a 512 KiB pre-JSON limit, enforced on actual
streamed bytes, including absent/incorrect Content-Length. This accommodates JSON
escaping while the decoded content still obeys the smaller UTF-8 limit.

PDF is a recognized source type but deterministically REJECTED with
PDF_UNSUPPORTED. No binary PDF bytes are decoded as successful text. Available
bundled document libraries are not project dependencies; Task 2.2 adds no parser,
OCR or dependency. A future bounded PDF implementation must define a new
normalization/location contract and preserve honest parsing outcomes.

Sources have immutable UUID, Project/Campaign ownership, type/name, hashes,
normalization version, metadata, status and created_at. Within a Campaign, the
same type + normalized hash + normalization version returns the existing source;
its first name/raw hash remain unchanged. Changed text creates a new snapshot.
Equivalent sources in different Campaigns remain separate. No edit/delete API is
introduced. List responses project metadata only; source detail returns the
complete normalized text for lazy reading.

## Explicit structured extraction

A trusted application composition optionally injects RequirementExtractor. It
uses the existing RESEARCHER role/model with a specialized system instruction
and Pydantic output schema through the accepted model adapter. It has no tools,
repository authority, shell, mutation or test-execution access. Document text is
supplied only as untrusted source data, never as system instructions. Prompts
require explicit supported facts, ambiguity/missing-information markers, and
no invented details or test-case generation.

The complete normalized source plus UUID/hash/line metadata is serialized once.
The entire serialized context must fit the existing 60,000-character ModelRequest
bound. Otherwise EXTRACTION_CONTEXT_LIMIT (422) occurs before a reservation or
provider call. There is no truncation, chunking, summarization or generic cache.
Whole-source coverage fields must match lines 1 through line_count. A model's
coverage declaration and semantic fidelity cannot be proven deterministically;
source citations and later human review remain necessary.

Output is schema-native structured data, revalidated after the adapter returns:
source UUID/hash, coverage range, at most 100 unique requirement keys and at most
131,072 serialized UTF-8 bytes. Each requirement has a stable UUID, Project and
Campaign IDs, extraction ID, logical key, title (200 characters), description
(4,000 characters), ordered acceptance criteria (at most 20), evidence references
(1–8), information markers (at most 20), review status and timestamps. Stable
UUIDs derive from source UUID + contract version + local key; logical keys include
the source UUID so changed snapshots cannot overwrite earlier requirements.

Each reference carries source UUID/hash, LINES location type, inclusive normalized
start/end line and a supporting excerpt of at most 512 characters. Deterministic
validation requires the selected source/hash, valid range and an exact excerpt
within those lines. All requirements and references are validated before any
requirement insert. Invalid evidence/output fails the whole extraction atomically;
no unsupported requirement is accepted. Exact excerpts cannot prove the semantic
inference: a citation may be real while a model interpretation is wrong.

Missing acceptance criteria require an explicit MISSING_INFORMATION marker.
Any marker derives NEEDS_CLARIFICATION; otherwise output is READY_FOR_REVIEW.
DRAFT remains a separate domain review status. There is no requirement approval,
readiness evaluation, edit/review UI, or test generation in Task 2.2.

## Durability, duplication and usage

A dedicated requirement-extraction record persists STARTED before a provider
call. Its transaction closes before model work. Requirements, terminal status
(SUCCEEDED/FAILED), safe error code and provider-neutral metadata persist in one
short transaction afterward. This record is not TaskState, Campaign status or
ExecutionJobStatus, and does not create hidden workflow evidence.

One requirements-v1 attempt is allowed per immutable source. Repeated requests
return the existing terminal result, including FAILED, without another model
call or duplicate requirements. Concurrent requests for STARTED return
EXTRACTION_RECONCILIATION_REQUIRED. A process crash or failed completion
persistence leaves STARTED visible and cannot be replayed automatically. There
is no retry/recovery endpoint in this increment, no raw exception/refusal text,
and no fabricated completion or usage. New contract versions/re-extraction need
an explicit future policy rather than changing this source uniqueness silently.
SDK transport retries remain disabled; application extraction does not duplicate
Task ReliabilityService policy or retry automatically.

The existing adapter supplies [Phase 1 model metadata and usage](MODEL_USAGE.md).
Campaign model-usage reads expose bounded per-attempt input/output/total/cached/
reasoning metrics, context-size diagnostics, agent/model/purpose aggregates and
up to 10 top consumers. Purpose REQUIREMENT_EXTRACTION is not a workflow state.
Known provider values are authoritative; missing usage is unknown (null), and
provider-reported zero remains zero. known_sum and missing_records distinguish
partial totals; truncated collections withhold complete totals. Attempt UUIDs
are counted, not provider response IDs. Cost remains NOT_CONFIGURED/null without
pricing configuration. Raw responses, reasoning, prompts and provider IDs are
not returned by these operational reads. Task/Run usage stays separate and
unchanged; Campaign execution/QA Runs are not implemented here.

## Application, HTTP and host safety

All operations validate existing Project, Campaign and selected child ownership.
No ownership can be body-supplied or reassigned. Scoped mismatch returns safe 409;
missing entities return 404. Extra fields, invalid UUIDs and bounds return safe
422. CollectionPage limits default to 50, range 1–200, querying limit+1 rows.
Sources sort newest created_at then UUID; requirements oldest created_at then
logical key; extraction usage oldest started_at then UUID. UTC ordering follows
existing repository conventions. Usage default/max limit is 200.

Under /api/v1/projects/{project_id}/campaigns/{campaign_id}:

| Method and suffix | Behavior |
| --- | --- |
| POST /sources | Deterministic ingest; 201, including immutable dedup result |
| GET /sources | Bounded metadata list |
| GET /sources/{source_id} | Detail with normalized text or rejected metadata |
| POST /sources/{source_id}/extract-requirements | Explicit one-attempt extraction; no body or empty object only |
| GET /requirements | Bounded structured requirements list |
| GET /requirements/{requirement_id} | Structured requirement and source evidence |
| GET /model-usage | Bounded extraction usage projection |

[API conventions](API.md) remain unchanged for existing Project/Task operations.
Public demo/preview-demo/hosted-demo compose no real extractor; an extraction
request returns EXTRACTION_NOT_CONFIGURED (409), with no model reservation or
fabricated synthetic facts. Existing Basic/session/CSRF protections apply.
Only trusted local host composition injects the real adapter; loopback and
existing credential-presence/preflight rules remain. The domain and application
can run source-only with an empty runtime registry; existing host local onboarding
still requires its accepted workspace configuration. Task 2.2 does not redesign
that host setup or expose real extraction publicly.

## Persistence and Task 2.3 handoff

Alembic 0005 adds campaign_sources, campaign_requirement_extractions and
campaign_requirements. Bounded ordered criteria, references and markers use JSON,
consistent with existing typed evidence storage. Composite foreign keys enforce
Project/Campaign/source/extraction ownership. An identity index on qa_campaigns
supports those composite foreign keys; no Campaign column or lifecycle changes.
Uniqueness enforces normalized source dedup and one attempt per source.

Upgrade preserves existing records. Downgrade to 0004 removes the three content
tables and supporting Campaign identity index; existing Campaign/Project/Task/
evidence/job data remains. Packaged migrations and the host revision marker move
to 0005. No dependency is added. Offline tests cover normalization, safety, context
bounds, evidence, structured SDK calls, failures/missing usage, crash/concurrency,
scoping, DB reopen, API/body limits and populated upgrade/downgrade.

Task 2.3 now consumes stable requirement identities, ordered criteria, clarification
markers and cited immutable sources for [imported/generated test specifications](TEST_SPECIFICATIONS.md).
Requirement/test approval, readiness, execution and reporting remain later work.
