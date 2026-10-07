# Human approval, traceability and readiness (Task 2.4)

Task 2.4 completes the Phase 2 domain/API preparation foundation. These are
operator review and deterministic read operations. They do not execute tests.
[Campaign preparation](CAMPAIGNS.md), [requirements](REQUIREMENTS.md) and
[test specifications](TEST_SPECIFICATIONS.md) retain distinct identities and
provenance. A source repository or runtime binding is unnecessary.

## Explicit approval and immutable content

Requirement and Test Specification review statuses are DRAFT,
NEEDS_CLARIFICATION, READY_FOR_REVIEW and APPROVED. The only new transition is
READY_FOR_REVIEW -> APPROVED, through an explicit APPROVE command. DRAFT and
NEEDS_CLARIFICATION cannot jump to APPROVED. Information markers, unknown
Requirement references and missing traceability block approval. Import,
extraction and generation cannot write APPROVED, including through their
persistence boundaries. Valid structured output or a citation is not approval.

Existing content/provenance is immutable. Task 2.4 adds no content editor,
clarification resolution, generic status update, rejection, reopen or reverse
transition. Blocked snapshots stay blocked; a future explicit revision flow must
resolve gaps rather than erase markers. Approved content cannot be edited by
any current API. New separately ingested/extracted/imported/generated content
can still be added; it is not implicitly approved and can change readiness.
Campaign name/objective editing keeps its existing independent semantics.

## Reviewer label and audit contract

Existing hosts have trusted local access, preview Basic authentication, or a
single-operator hosted session; they have no stable authenticated user ID.
Approval therefore requires an explicit operator-supplied `reviewer_label`.
It is a safe audit label, not a verified account ID or RBAC identity. Use a
non-secret label such as `qa-human`; never use credentials, session tokens,
API keys or other secrets as the label or note. No identity is inferred from
authentication username/password, session nonce, environment, or AI output.
Call the in-process service only from trusted operator/application code.
Public HTTP commands retain the existing Basic/session authentication and
hosted CSRF protection; no auth/session behavior changes.

The label is 1–64 ASCII letters/digits/underscore/period/hyphen and starts with
a letter. Optional note is strict text of 1–1,000 characters, preserved as data.
Notes never enter provider prompts or activate policies/tools. Entire review
JSON bodies are limited to 8,192 bytes before JSON parsing, including streams.
Oversized requests return 413 REVIEW_SIZE_LIMIT. Extra fields, other actions,
missing/invalid labels and oversized notes return the existing safe 422 envelope.

A separate immutable approval receipt stores object UUID/kind, Project/Campaign
ownership, APPROVED, reviewer label, optional note, aware UTC approved_at and a
SHA-256 snapshot identity. The hash includes all immutable facts, links,
provenance and object identity; it excludes review_status and updated_at.
The receipt and the child's status/time change commit atomically. No AI model
metadata or workflow AuditRecord is reused for human approval.

One receipt per immutable object is enforced by its PK. Identical repeated
approval intent (same label/note) returns the original receipt/time without
inserting another record. Different label/note returns 409 REVIEW_CONFLICT,
including a concurrent request that loses to another intent. Writes reuse the
accepted short SQLite BEGIN IMMEDIATE boundary before reads and a conditional
READY_FOR_REVIEW update; no distributed lock or external work inside transactions.
A failed commit rolls both status and receipt back. Existing receipt reads/retries
validate its snapshot hash and ownership; mismatch or APPROVED without a receipt
returns 409 REVIEW_EVIDENCE_INVALID rather than replacing history.

## Application and API

All paths below are beneath
`/api/v1/projects/{project_id}/campaigns/{campaign_id}`. Existing Project,
Campaign and reviewed child ownership is checked before any write/read.
Cross-project/campaign operations use the existing safe mismatch/not-found errors.

| Operation | Application operation / response |
| --- | --- |
| POST /requirements/{requirement_id}/review | review_campaign_requirement -> ReviewState |
| GET /requirements/{requirement_id}/review | get_campaign_requirement_review -> ReviewState |
| POST /test-specifications/{test_spec_id}/review | review_campaign_test_specification -> ReviewState |
| GET /test-specifications/{test_spec_id}/review | get_campaign_test_specification_review -> ReviewState |
| GET /traceability?limit=50 | get_campaign_traceability -> CampaignTraceability |
| GET /readiness | get_campaign_readiness -> Readiness |

All successes return 200. ReviewState includes object kind/UUID/ownership,
review_status and nullable evidence. Existing child detail/list routes expose
the expanded review_status. Example explicit command:

```json
{"action":"APPROVE","reviewer_label":"qa-human","note":"Checked source evidence and test design."}
```

The action defaults to APPROVE if omitted; reviewer_label remains mandatory.
No status field is accepted. Invalid preparation approval returns 409
REVIEW_NOT_REVIEWABLE; conflicting intent and invalid evidence are distinct errors.
The API remains a thin one-use-case transport with detached application contracts.

## Traceability and bounds

Each requirement has its own review status, linked_test_count,
approved_test_count, linked_test_review_states counts, and coverage:

- COVERED: at least one eligible APPROVED linked Test Specification.
- PARTIAL: links exist but no eligible approved test links.
- NOT_COVERED: no test links exist.

Eligible approved tests have durable approval evidence, no information markers,
no unresolved references, required evidence/expected behavior and a known link.
Additional non-approved linked tests do not remove existing approved coverage.
A NEEDS_CLARIFICATION requirement may be COVERED in the traceability sense, but
cannot be ready. Imported unlinked tests cover no requirement. Zero generated
tests is a gap, never evidence of successful testing. Counts do not prove quality,
execution PASS, code coverage or defect closure.

Traceability returns two independent CollectionPage collections: requirements
and explicit Requirement/Test links. Both use the same strict limit 1–200,
default 50; each materializes at most limit+1 rows and sets truncated separately.
Requirements sort by UUID, links by Requirement UUID then Test UUID. Linked
review-state counts group into at most four statuses per selected requirement;
large test bodies and source documents are not loaded. Counts cover all links
for each displayed requirement even if the links collection is truncated.
There is no pagination cursor in this increment; truncated is explicit.

## Derived readiness

Readiness is computed through scoped SQL aggregate/count queries in a single
read transaction over all persisted campaign content, independent of the
traceability response limit. No readiness flag/table, cache, review scan through
models, repository/filesystem reads, or silent workflow transition exists.

READY requires all of the following:

1. Campaign preparation is explicitly APPROVED.
2. At least one persisted Requirement exists; every Requirement is in scope.
3. All Requirements are APPROVED and no Requirement needs clarification.
4. At least one Test Specification exists.
5. Every Requirement is linked to at least one eligible APPROVED test.
6. Every approved Requirement has approval evidence and no unresolved markers.
7. Every approved test has approval evidence, known links and no unresolved
   ambiguity/missing-information/traceability markers or imported references.

Extra non-approved tests are not automatically approved and do not block an
otherwise fully covered approved set. Missing approval evidence fails closed.
Database contents are trusted persistence; SQL aggregate reads do not recompute
all cryptographic hashes across an unbounded collection. Supported writes are
immutable, and individual evidence reads/retries validate the stored hash.

The response includes Project/Campaign IDs, campaign_preparation_status,
READY/NOT_READY, total/approved/clarification Requirement counts, total/approved
Test Specification counts, covered/partial/uncovered Requirement counts,
invalid-approved counts and ordered blocker_codes. Codes are:
CAMPAIGN_NOT_APPROVED, NO_REQUIREMENTS, REQUIREMENTS_NOT_APPROVED,
REQUIREMENTS_NEED_CLARIFICATION, NO_TEST_SPECIFICATIONS, REQUIREMENT_COVERAGE_GAP,
INVALID_REQUIREMENT_APPROVAL, INVALID_TEST_APPROVAL. No volatile evaluation
clock is included: unchanged persisted state yields identical responses.

Campaign APPROVED with readiness NOT_READY is valid, including empty content,
review blockers or coverage gaps. Readiness never changes Campaign preparation
or Task/workflow state. Future execution status and QA outcome remain separate:
individual test FAIL is a QA outcome and must not stop remaining eligible tests.
No campaign executor, QA Run, PASS/FAIL state or execution endpoint is added here.

## Persistence and safety

Migration 0007 expands the two child status constraints, adds
campaign_requirement_reviews and campaign_test_reviews, and indexes scoped
Requirement/Test linkage and review selection. Composite FKs bind each receipt
to its actual child's Project/Campaign ownership. The migration uses accepted
SQLite batch recreation and final FK verification, preserves all 0004–0006 rows,
and is packaged for host bootstrap. No dependencies are added.

Upgrade/downgrade/check and restart/reopen are tested. Downgrade to 0006 is
supported only while there are no approvals/APPROVED objects; otherwise it
refuses transactionally before dropping evidence. Downgrading an approved
installation needs a future explicit data retention/migration decision.

Review/traceability/readiness have zero provider calls, token usage records,
subprocess/test execution, repository reads, mutation, hidden Tasks/jobs/events,
or runtime resolution. Existing [Phase 1 model usage](MODEL_USAGE.md) remains
unchanged, including missing usage = unknown. Demo/public modes remain synthetic;
real local execution and target-interpreter boundaries are unchanged.

Phase 2 preparation domain/API work is complete through Task 2.4. The next
handoff is Phase 3 QA-oriented UX / Run Lifecycle; review UI, clarification
revision and any executor/run contracts require their own explicit task.
