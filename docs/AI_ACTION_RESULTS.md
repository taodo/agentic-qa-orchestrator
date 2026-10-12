# AI preparation action results

Task 3.7 observes existing preparation actions. It does not approve records, decide
readiness, execute tests, estimate costs or change provider invocation/retry policy.

## Authoritative fields

| UI fact | Existing persisted source / read projection |
| --- | --- |
| Status / safe error code / timestamps | RequirementExtraction or TestGeneration rows; ExtractionView / TestGenerationView |
| Configured model | Persisted attempt `model` exposed as `configured_model` |
| Provider model / provider | Persisted ModelMetadata `model` / `provider`, validated through `safe_metadata`; absent metadata stays unavailable |
| Input / Output / Reasoning / Total | Respective persisted ModelMetadata fields through unchanged Phase 1 `totals([metadata])` and UsageTotals.<category>.total |
| Generated/revised count | Persisted campaign_requirements.extraction_id or campaign_test_specifications.generation_id matches, scoped to the attempt owner |
| Ready for review / Needs clarification at creation | Immutable output information_markers: canonical creation status was READY_FOR_REVIEW when empty, NEEDS_CLARIFICATION otherwise |
| Revised Requirement UUID/key/logical key/version | Matched persisted Requirement and campaign_requirement_revisions row, including historical versions |
| Inherited clarification count | Distinct generated outputs linked through persisted test/Requirement links to immutable selected Requirements with markers |
| Retry eligibility | Existing extraction_retryable attempt policy; UI does not recompute it |

The OpenAI adapter already maps provider usage.input_tokens, output_tokens,
output_tokens_details.reasoning_tokens and total_tokens independently into
ModelMetadata. This task changes neither that adapter nor token accounting.
Reasoning may be a subset of output: the UI never adds categories or derives a
missing total. A category with null/missing total displays Unavailable, including
when a known_sum exists. Integer zero is shown only when supplied authoritatively.
Completely missing usage has an explicit unavailable notice. No pricing is used.

## Bounded read-model addition

Both action views already exposed all four UsageTotals categories. The frontend
previously typed only extraction total usage and omitted generation usage metadata.
Generation already had durable list/detail endpoints; no new history persistence
or route is required.

Additive `provider` and `output` fields expose existing facts. The output projection
selects metadata only (no document/test bodies), batches at most 200 scoped attempts
and at most 100 persisted outputs per attempt, with a sentinel and per-action bound
check. Original/retired outputs are included so later revisions or approval do not
rewrite the historical AI result. STARTED output details are unavailable. FAILED
attempts have zero accepted outputs under existing persistence contracts.

This is a creation-time distribution, not current review state. The summary says
so explicitly. Existing review screens remain authoritative for current approval.
Inherited counts attribute persisted selected-Requirement markers, without guessing
from model prose or claiming all clarification originated from Requirements.

Source list/latest attempt, extraction history and terminal extraction/retry returns
share this projection. Generation returns and existing list/detail reads do too.
Campaign-wide model-usage aggregates retain their existing usage-only semantics;
output defaults to unavailable there without adding output queries to analytics.
No database migration, dependency, schema persistence or provider call was added.

## Browser behavior

AIActionSummary is pure presentation reused by extraction/revision and generation.
Successful extraction/revision completion is retained at Requirement-page level
below the focused results heading, before scoped refresh removes the old record. The source attempt history remains the durable
reload source. Failed revisions retain their attempt/error and existing retry rules.

Generation history loads only after explicit View/Refresh generation history, via
GET test-generations?limit=50, disclosing truncation. Passive viewing, navigation,
rendering and refresh never create/retry an action. In-flight action/history responses
are discarded on unmount through existing hooks. No browser storage is introduced.

Saving clarification is still inert source ingestion. It shows no model or token
summary; explicit revision is a separate action. Equivalent terminal requests may
return a prior attempt: summaries display that attempt's outputs, not claims of new
work. Approval, readiness, traceability, Run snapshots and synthetic behavior stay
unchanged.

## Manual review

Use existing persisted Campaign data or synthetic fixtures; do not spend tokens
solely to make screenshots.

1. Requirements: inspect successful extraction summary with local generated/review
   counts, distinct model labels, four token categories and Review requirements.
2. Open failed/retryable extraction if available: safe FAILED/code, recorded usage,
   existing retry eligibility and old/new attempt history. Viewing is GET-only.
3. Inspect revision summary/new key/version/UUID, including a version still marked
   NEEDS_CLARIFICATION. Saving clarification alone must show no AI usage summary.
4. Tests: inspect successful generation and inherited-clarification explanation.
   Counts must match this attempt, including when Campaign totals differ.
5. Compare full, total-only, missing and authoritative-zero usage. Unknown categories
   stay Unavailable; totals are never inferred and reasoning remains separate.
6. Reload and explicitly open generation/extraction history. Verify durable facts,
   truncation notice, safe failure handling and no POST/provider invocation on reads.
7. Check desktop/narrow layout and keyboard access using the Task 3.6 foundation.

Limitations: no global analytics, costs, current-review counters in historical
summaries, model selection, new retry behavior or real executor. Pre-reservation
HTTP failures expose existing safe errors without inventing an attempt or usage.
