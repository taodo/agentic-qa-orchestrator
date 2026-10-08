# Preparation workflow (Task 3.10)

PRD ingestion, explicit extraction/revision, human approval and test generation remain
separate actions. Saving clarification is inert source ingestion. Preparation status,
coverage, readiness, Run lifecycle and QA outcome retain their accepted meanings.

## Generation reliability

The offline reproduction uses eight Requirement snapshots and the installed SDK with
mock HTTP. Previously `responses.parse` applied JSON/Pydantic parsing before returning
the provider envelope. A malformed structured payload therefore raised before the
adapter captured metadata; even an incomplete response could be classified as
`MODEL_MALFORMED_RESPONSE` with unavailable provider/usage. The pre-fix regression
reproduced both failures. The exact historical live payload was not retained, so its
particular invalid field or truncation cannot be inferred from that safe error alone.

The adapter now sends the same strict schema through `responses.create`, captures
provider metadata in memory, checks refusal/completion status, and validates completed
JSON against the requested Pydantic contract. Incomplete responses use
`MODEL_INCOMPLETE_RESPONSE`; invalid completed JSON/schema uses
`MODEL_MALFORMED_RESPONSE`. Application selected-ID/link validation remains a separate
boundary. No prose fallback, repair, retry, verifier or second provider call is added.
No raw envelope/text is persisted or rendered; provider usage remains independently
reported, including null/unknown and authoritative zero. The SDK's strict-schema helper
is internal to the SDK and confined to this adapter; SDK upgrades must run adapter
contract tests. No new SDK version, dependency, model or budget is introduced.

The generation prompt spells out UUID references, exact enums, contiguous 1-based step
indices, missing-information markers and concise complete output. Validators remain
strict, including duplicate keys/behavior, link selection and output size limits.

## Approval gate and history

New requests must contain 1–20 unique current APPROVED Requirement IDs owned by the
Campaign/Project. A single unapproved member rejects the whole selection with
`GENERATION_REQUIREMENT_NOT_APPROVED` (409), before attempt reservation or provider work.
Superseded versions retain `REQUIREMENT_REVISION_CONFLICT`. Reservation rechecks the
current version, approval status and full snapshot identity before external execution.
A transaction never spans the provider call. STARTED reconciliation and terminal replay
for identical eligible snapshots remain unchanged. Pre-policy unapproved attempts and
inherited clarification facts remain readable through existing bounded history/detail
routes; they do not grant new generation eligibility. Generated Test Specifications
still require human review and never imply execution or coverage acceptance.

## Operator workflow

Requirements show compact local keys/titles and status/criteria/coverage. Audit UUID and
logical identity remain in row details. Filters count only returned current rows, never
pretend to be global totals, and clear selection. Select all visible excludes approved
and out-of-list detail rows; selected clarification-blocked rows are explicitly ignored
for bulk approval. Only selected, visible current READY_FOR_REVIEW rows without markers
are submitted through existing single-record approval requests, sequentially and with
operator label/note validation. Progress and each success/failure remain visible. There
is no automatic retry; an authorization failure stops remaining requests, and navigation
stops undispatched requests. In-flight requests cannot be undone. Review conflicts require
operator inspection. Source intake remains below the table.

Each clarification form is scoped to one row. Explicitly selected details outside the
bounded current list remain readable, but cannot be bulk-selected or approved there.
No detail fan-out is used to discover eligibility.

Traceability is the primary Test Design Workbench. Its authoritative bounded rows drive
eligibility; optional Requirement names never hide or gate coverage. UUID fallback and
independent truncation notices remain. Select all approved visible takes at most the
first 20 rows in displayed order, with an explicit notice when more are present. A
single-row Generate button uses exactly that approved row. Rendering, refreshing,
navigation and history reads never generate tests. The retained Test Specifications
selection is secondary and applies the same approved-only and select/deselect rules.

Success displays action-local accepted-output counts, configured/provider model names
and distinct token categories from the existing Task 3.7 result contract. The operator
chooses Go to Test Cases (existing Test Specifications destination) or Stay on
Traceability. Failed/uncertain output displays its status, safe code and only known
metadata, without a success navigation action. Nothing auto-redirects or retries.

## Manual showcase after review

Use synthetic prepared records for visual checks. Inspect mixed statuses, all filters,
select/deselect, bounded notices, sequential approvals including a conflict, and two
independent clarification forms. On Traceability inspect disabled reasons, UUID fallback,
selection of more than 20 approved rows, and generation success/failure completion with
known and unknown usage. Confirm both explicit navigation choices and no automatic work.
A live StayFinder generation was NOT RUN during implementation. After technical review,
the operator may choose one bounded live attempt to inspect the original failure using
the improved safe provider status/usage; no success is claimed without that execution.

Migration: NONE. Dependencies added: NONE. No Test Cases redesign/export or real Campaign
executor is included. Public/demo authentication and synthetic-only runtime composition,
trusted target interpreter isolation and repository-read safety are unchanged.
