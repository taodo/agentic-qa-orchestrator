# Preparation recovery (Task 3.5)

Recovery is explicit and auditable. It does not execute tests or change Campaign
preparation status automatically. Campaign APPROVED remains separate from derived
READY; individual test FAIL remains a QA outcome, not a system failure.

## Extraction attempts

Initial Extract keeps its original idempotency: repeated submission returns the
original terminal attempt. Refresh and GET never invoke a model. Each immutable
source supports at most three attempts. Attempt 1 has no parent; attempts 2 and 3
reference the preceding failed attempt. Each has its own UUID, source/hash,
contract, timestamps, safe error, configured/provider model and provider usage.
Successful Requirements retain their extraction_id linkage. Failed attempts are
never overwritten by a successful retry.

Retry is allowed only for FAILED attempts below the limit with one of:

- EXTRACTION_INVALID_CITATION or EXTRACTION_INVALID_OUTPUT;
- MODEL_RATE_LIMIT, MODEL_TIMEOUT, MODEL_CONNECTION or MODEL_SERVER_ERROR;
- MODEL_MALFORMED_RESPONSE or MODEL_INCOMPLETE_RESPONSE.

Authentication, configuration, refusal, invalid request, context limit,
unsupported role and unknown provider errors are not retryable. Correct local
configuration or provide corrected source evidence; do not blindly replay.
STARTED means uncertain provider work and is never retried by this feature.

POST /extractions/{attempt_id}/retry is an explicit new-attempt intent. The parent
UUID is the idempotency key: one unique child per parent plus unique source/attempt
number. Repeating that intent returns its terminal child; a pending child gives
EXTRACTION_RETRY_CONFLICT. A further retry must explicitly target the failed child.
The existing SQLite writer reservation rechecks ownership/eligibility and commits
STARTED before one provider call outside the transaction. There is no retry loop
or distributed lock. Failed completion persistence leaves STARTED for investigation,
never an automatic provider replay.

Each actual call records independent authoritative usage. Unknown stays null;
known zero stays zero. Campaign usage sums attempts using existing partial/truncated
semantics. History retains failures after success and labels latest/current honestly.

## Grounded clarification

Only a current NEEDS_CLARIFICATION Requirement can receive this recovery path.
POST /requirements/{requirement_id}/clarifications accepts request_key and content.
Facts are non-empty, at most 4,000 UTF-8 bytes and normalized with existing LF/NFC
source ingestion. Same Campaign key, Requirement and normalized facts replay the
saved addendum; changed facts under the same key conflict. Identical combined
content under a different key conflicts rather than duplicating revision work.

The persisted clarification links Project, Campaign, original Requirement and a
new immutable source. That source contains the full original extraction source,
an explicit Requirement heading and the supplied facts, with a stored first-fact
line and facts hash. Source limits remain 65,536 UTF-8 bytes / 4,096 lines. Source
history grows explicitly; nothing is silently truncated. The existing 60,000
character context bound applies to the complete serialized source plus target;
if it cannot fit, EXTRACTION_CONTEXT_LIMIT stops before a provider call.

Saving facts is deterministic and never calls a model. Revise Requirement is a
separate explicit extraction from the addendum source, with the complete target
Requirement as untrusted user data. Output must contain exactly one Requirement
with the same local key, exact source/hash/full analyzed range, valid citations
and at least one citation within the appended facts. Markers remain when evidence
does not resolve ambiguity. Citation validity does not establish factual truth;
the operator must review semantic correctness. Text cannot become system/developer
instructions, tools, executable markup or authority. Reviewer labels remain
operator-asserted, not verified identities.

## Versions, dependent tests and readiness

Successful revision creates a new Requirement UUID and source-qualified logical
key, plus an explicit supersession edge and version (maximum ten versions per
chain). The old content, status, citations and review receipts remain immutable.
Concurrent revisions cannot fork a current Requirement. Failed revisions do not
supersede anything. New content is READY_FOR_REVIEW or NEEDS_CLARIFICATION and
never inherits approval. No Resolve-to-Approved shortcut exists.

Current Requirement lists, traceability and readiness exclude superseded versions.
A Test Specification linked to any superseded Requirement is conservatively retired
from current preparation lists, coverage, readiness and new Run selection. Its
content and historical approval are preserved; direct scoped detail/review reads
remain available. Reapproving an old Test or Requirement cannot restore currency.
Import or generate replacement Tests linked to the new UUID, then explicitly
review them. There is no automatic relinking or approval transfer. Historical
Tests can be recovered from saved import/generation IDs and existing Run snapshots.

This adds only current-content filtering to the accepted Run snapshot selection
boundary. Existing Run snapshots and synthetic execution are untouched. Readiness
still checks all Task 2.4 evidence/hash/approval/coverage rules against current
content; Campaign status does not change due to ingestion, clarification or revision.

## Scoped API

All suffixes below use /api/v1/projects/{project_id}/campaigns/{campaign_id}.
Existing source/extraction/review endpoints remain compatible, with additive source
latest_extraction / clarification_requirement_id and attempt lineage/read metadata.

| Method and suffix | Behavior |
| --- | --- |
| GET /sources/{source_id}/extractions?limit=50 | Newest attempts first; bounded to three |
| POST /extractions/{attempt_id}/retry | Empty body or {}; explicit new child or idempotent replay |
| POST /requirements/{requirement_id}/clarifications | Save inert facts; no provider call |
| GET /requirements/{requirement_id}/history | Oldest-to-current chain; bounded to ten |

Standard bounded list limits apply. Clarification/retry bodies use the existing
8 KiB preparation request envelope limit. Extra fields reject. Scope is validated
before work; foreign attempt IDs return EXTRACTION_ATTEMPT_NOT_FOUND without revealing
existence. Safe conflicts include EXTRACTION_RETRY_NOT_ALLOWED,
EXTRACTION_RETRY_CONFLICT and REQUIREMENT_REVISION_CONFLICT; invalid facts use
CLARIFICATION_INVALID. Shared Basic/session/CSRF behavior and no-auth-replay remain.
Public demo composition still has no real extractor; no provider/mutation/repository
or subprocess capability is introduced. No raw provider errors/responses or hidden
reasoning are persisted/rendered by recovery.

## Persistence

Migration 0010 replaces single-source attempt uniqueness with source/number and
parent uniqueness, backfills old attempts as number 1 with no parent, and adds
campaign_clarifications and campaign_requirement_revisions with composite owner
foreign keys. No old Requirement/Test content or approval hash shape changes.
Upgrade preserves existing successes, failures and all previous data. Downgrade
refuses when retries, clarifications or revisions exist, preserving audit history;
it can round-trip databases containing only original attempts. No dependency added.

## Manual showcase recovery

1. Use the accepted trusted local host and migrate its database to 0010. Keep the
   existing trusted interpreter/provider configuration; do not expose real mode publicly.
2. Open Project -> Campaign -> Requirements. Refresh Sources. For the saved
   FAILED / EXTRACTION_INVALID_CITATION attempt, open View extraction history,
   confirm eligibility, then click Retry Extraction once. It is a new paid provider
   call. Wait for the terminal result; inspect both failed and new attempts. Do not
   repeat initial Extract expecting new work. After three failures, correct source
   evidence rather than bypassing the bound.
3. For NEEDS_CLARIFICATION, inspect the blockers/citations. Choose Add Clarification /
   Provide Missing Information and supply only known missing facts. Save Clarification
   persists evidence without a model call. Click Revise Requirement separately.
   After navigation/reload, the saved source is labeled as a clarification addendum
   with the original Requirement UUID and the same Revise Requirement action.
4. Inspect Requirement version history and the new citations/criteria. Remaining
   uncertainty stays NEEDS_CLARIFICATION. Otherwise explicitly approve the new
   READY_FOR_REVIEW Requirement, import/generate replacement Tests linked to it,
   review those Tests, and refresh Traceability/Readiness. Old approved tests cannot
   falsely satisfy coverage. Campaign submission/approval remains a separate action.
5. Never replay STARTED or assume a safe terminal error proves a provider call did
   not occur. Reads/navigation perform no retries. No live showcase is claimed by
   automated validation; tests use deterministic fake provider responses.
