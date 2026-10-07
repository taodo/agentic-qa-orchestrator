# Phase 1 context and token usage

Model usage is derived read-only visibility. It never drives Task states, gates,
retries, test execution or QA outcomes. Individual test FAIL remains QA evidence;
this increment adds no fail-fast execution or campaign behavior.

## Provider-authoritative usage

The Responses adapter records input_tokens, output_tokens, total_tokens and
reasoning_tokens when supplied by the provider. Missing fields remain null;
reported zero remains zero. Reasoning is a breakdown of output tokens, never an
extra amount added to output/total. See the [official Responses reasoning usage
guide](https://developers.openai.com/api/docs/guides/reasoning#managing-the-context-window).
No tokenizer estimate, model-price constant or hidden reasoning text is stored.

Optional ContextSelection metadata records original/selected user-input JSON
character counts, selected UTF-8 bytes and reused result count. These are size
diagnostics, not token usage; instructions/output schemas are outside this size
measurement. Only provider-returned usage can support token totals.

Existing event JSON holds metadata without a migration. Single-call completion
and failures with a valid received response retain safe metadata. Repository turns
retain it in MODEL_TURN_COMPLETED/MODEL_TURN_FAILED. Failures before a usable SDK
response (transport/SDK parse errors, local context rejection, interrupted
reservations) may have unavailable usage. No raw provider response/refusal/request
or credentials are recovered or persisted to guess missing consumption.

## Bounded application and HTTP reads

Use QASentinelApplication.get_task_model_usage(task_id, limit=200) or:

```text
GET /api/v1/tasks/{task_id}/model-usage?limit=200
GET /api/v1/tasks/{task_id}/model-usage?execution_job_id={job_id}&limit=200
```

The existing host authentication applies. These reads never resolve runtime
bindings, call providers, read target files, run subprocesses/tests or mutate
sources/workflow. Existing invocation/timeline API contracts are unchanged;
frontend evidence remains lazy. No new technical dashboard or campaign UX is added.

The response provides per-invocation identity, configured/provider model, reasoning
stage, usage, unresolved/inconsistent records and context-size diagnostics. Task
rollups group by agent, provider model (configured model when metadata is unavailable)
and stage, plus the top ten invocation IDs ranked by observed total_tokens.
Unknown-only invocations are not ranked as token consumers. Rankings based on
known usage are not claims about missing usage or unselected history.

Each token metric has:

- known_sum: sum of observed valid provider values, null if none are available;
- missing_records: number of selected attempt records without that field;
- total: exact sum only when that field is available for all selected records and
  the read/history is complete; otherwise null.

A reported zero is distinct from unavailable data. Reasoning may be unavailable
while input/output/total are complete. Fake-only invocations without model metadata
have applicable=false and contribute no provider attempt records; no token count
is fabricated for them. Context-size totals are null when any contributing record
lacks those diagnostics (including historical events).

One repository turn contributes once by invocation ID plus turn_index. Its final
metadata copy in AGENT_COMPLETED/AGENT_FAILED is excluded. Single-call invocation
metadata contributes once; retries/escalations are distinct invocations and count
independently. Response IDs are not global deduplication keys. Repeated or
conflicting history is flagged and exact totals withheld rather than guessed.
records counts selected evidence/attempt slots, including unavailable reservations;
it is not a guaranteed count of billable provider requests.

Selection is bounded to 1–200 earliest invocation records (default 200), at most
6,000 projected metadata event records plus a sentinel, 20 model groups and ten
top invocation IDs. Provider/source outputs are not selected by the usage SQL
projection. truncated signals invocation/event bounds; exact totals are withheld
and known_sum describes only the returned selection. model_groups_truncated
signals the top-model display cap separately; Task totals still include all
selected records. No unbounded evidence/filesystem/reconciliation scan occurs.

## Task and execution request scopes

Default scope TASK covers the selected Task invocation history. Optional scope
EXECUTION_JOB_WINDOW validates ownership and selects usage records by event time
within the persisted job's started_at/finished_at interval. For an unfinished job,
this is only the current observed snapshot; queued jobs have no started window.
It does not invent a QA Run, assign invocation ownership to a job, claim exact
billing attribution or substitute ExecutionJobStatus for TaskState. Completion
metadata is selected at completion time; an unresolved record uses its reservation
time. Cross-boundary work may therefore not be attributable by this projection.
A dedicated future QA Run identity can replace this explicit window projection
when that product phase is implemented.

## Cost scope

Phase 1 reports cost_status=NOT_CONFIGURED and estimated_cost=null. Reliable,
versioned host pricing is not configured in this increment. Provider usage alone
is not an invoice. A later host-owned pricing service can supply versioned rates,
currency, effective dates and model/version identity, with cached-token treatment
and missing-usage coverage before offering an explicit estimate. Pricing does not
belong in workflow/domain gates. No volatile prices are hard-coded.

## Lossless context selection

Accepted structured Research/Plan/Analysis/Investigation projections remain the
existing inputs to later roles; their required fields and artifact references
are retained. Repository sessions now reuse exactly identical successful result
data within one request. The first full result remains inline. Later identical
results replace data with data_ref pointing to that earlier evidence_ref in the
same supplied input, while retaining their own request, evidence_ref, call index,
status and byte accounting. The prompt explains how to resolve that data.

Equality includes the whole typed data, not SHA alone. Changed content, hash,
path or metadata remains fully present. Failure results are never compacted.
Ambiguous duplicate evidence references disable reuse. The original immutable
artifacts/events and original repository byte/call/work limits are unchanged.
No persistent cache, provider memory, external lookup, summary model call or
source hint is introduced. Required content is not silently dropped/truncated;
selected required context above the existing 60,000-character limit still fails
MODEL_CONTEXT_LIMIT before another provider request.

Synthetic offline measurement: four identical full-file results containing the
same UTF-8 source, with four distinct requests/artifact refs, changed from
60,077 original JSON characters to 16,289 selected characters (16,539 UTF-8 bytes),
reusing three result bodies: 72.89% reduction. Every original typed result can be
reconstructed exactly from the inline data/references. This is a context-size
measurement, not a claimed live/provider-token saving. The tests also prove that
one required oversized unique file still fails honestly.

## Base compatibility and limitations

This branch starts at 69e6012 (accepted Task 25 plus documentation), which does
not include Task 26's Planner-stage/STATIC_REVIEW, search-count capping or trusted
target-interpreter hardening commits. The operator explicitly chose to keep this
base and report those absent changes rather than cherry-pick them. Phase 1 does
not restore or claim that hardening; current-base repository path/byte/role safety
and Task 25's existing deterministic execution boundary remain unchanged.
Integration of accepted Task 26 hardening needs a separately reviewed branch/base
change before claiming those guarantees here. No new dependency or migration.
