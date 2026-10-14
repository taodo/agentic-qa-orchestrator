# Phase 6.1–6.3: dormant decision intelligence

Issue #100; parent #99. Base: `f6e3f3eb790417f408fa0339a3901a77d8b62c64`.
Research date: 2026-10-14. Verdict: **CONDITIONAL GO for a dormant adapter only**.
**LIVE NOT VERIFIED. NOT ACTIVATED.** Phase 5 operator smoke and Tao's approval
remain prerequisites to merge/activation. Task 6.4 is a separate review gate.

## Current ownership and baseline

`agents/base.py:STATE_AGENTS` selects the canonical role for each workflow stage.
`CompositeAgentRuntime` selects an explicitly configured runtime; `RoleModelConfig`
selects the configured role model. There is no existing general prose-routing LLM.
`WorkflowRunner` maps typed Planner/Investigator/Reviewer outputs, verifies gates,
and delegates every state transition to `WorkflowEngine` and the canonical graph.
`ReliabilityService` owns retry budgets and durable Investigator escalation; its
pure policy evaluates confidence, hypotheses, evidence conflict and defect cycles.
These decisions are unchanged. Browser grounding/planning, Run and evidence
composition are unchanged. QA assertion FAIL remains an outcome, not a system failure.

Current role-model defaults are recorded in `models/config.py`; the benchmark
executes no role model and measures no OpenAI cost. Existing provider usage metadata
is authoritative; missing usage is unknown. This task does not change that pipeline.

The versioned 20-case corpus contains all six roles, bounded classification,
Investigator escalation boundaries, architecture/security requests, incomplete or
conflicting evidence, untrusted input, permission/policy denial, and unavailable/
timeout scenarios. Labels are explicit. Six human safety-review expectations outside
Investigator are intentionally absent from existing routing, rather than invented
as existing escalation behavior. Adversarial malformed inputs are tested separately.

Reproduce from the repository root:

```powershell
python scripts/benchmark_decisions.py
python scripts/benchmark_decisions.py --mode offline-poc
```

Corpus SHA-256 and measured p50/p95 local latency are in
`benchmarks/decision_baseline_v1.json` and `decision_offline_poc_v1.json`.
Baseline: 20/20 role labels, 0 false escalations, 6 missed safety-review expectations,
0 policy violations, 0 invalid output, 0 provider requests.
Offline PoC: 20/20 role labels, the same escalation results, 8 policy/error fallbacks,
14 fake proposal calls, **0 external requests**. This is a fixture contract exercise,
not a model-quality result or improvement claim. Single-pass 20-sample timings are
local Python overhead, not provider latency/SLA; no meaningful statistical comparison
or provider cost is available. No live-provider benchmark was performed.

## Official API findings

Primary sources checked:

- [Official OpenAPI](https://api.typesafe.ai/openapi.json), version 0.2.0;
  checked-in public schema fixture: `benchmarks/typesafe_openapi_0_2_0.json`.
- [API docs](https://api.typesafe.ai/docs) and
  [ReDoc](https://api.typesafe.ai/redoc).
- [Official public pricing](https://typesafe.ai/).
- [Account usage](https://console.typesafe.ai/usage) redirects to login.
- [Customer agreement](https://typesafe.ai/legal/mca): account/order usage and
  credit terms can differ; operator must verify applicable terms.

Verified documented contract: Bearer auth; authenticated `GET /v1/models` returns
model names/aliases, descriptions and release dates; `POST /v1/systemone` accepts
`model`, bounded `state`, and named `questions`. Questions support choice, noul
(yes/no probability), and score. Choice answers supply a selected choice,
confidence and probabilities. Responses supply reported model plus input/output
usage. Reported model may differ from configured alias. The adapter uses choice
and optional noul only, revalidating all outputs rather than trusting schema claims.

`jev-latest` is an official **example**, not a verified account model. No model is
hard-coded/defaulted. An unauthenticated model-list probe returned HTTP 403. Enabled
adapter discovery must verify the operator's model and reported identity against
that account's bounded model list; release date is retained as provenance. Discovery
is lazy and cached at most five minutes, never performed on construction/startup.

Public advertised pricing: $0.042 / million input tokens and free output, as observed
on the research date. It is not hard-coded in production. Actual account tariff,
billing/credit balance, numeric account rate limits, availability, model versions,
latency and SLA are **unverified**. Marketing latency/quality claims are not
QA Sentinel measurements. No key was requested, printed or inspected and no live
inference/authenticated discovery was attempted. No new service was activated.

## Contracts and final policy

`decisions/contracts.py` defines strict, frozen, versioned `DecisionRequest`,
`DecisionProposal`, `DecisionReceipt`, and a minimal proposal-only `DecisionProvider`.
Requests contain trusted baseline/allowlisted roles, optional workflow stage,
bounded risk/complexity/permission/evidence signals, at most 16 UUID evidence refs,
and a correlation UUID and expiry of at most 30 seconds. No raw prompt/document/
DOM/cookies/credential field exists. Unknown fields are rejected, not silently lost.
This foundation supports structured advisory triage only, not arbitrary natural
language classification or evidence summarization.

`decisions/policy.py` is the final arbiter called by the standalone orchestration
`DecisionRouter`. High risk, incomplete/conflicting evidence, untrusted input,
permission requirement or policy denial skips the provider and retains baseline.
Expiry/future timestamps, correlation/hash mismatch, disallowed role/escalation,
and confidence below 0.8 reject advice. An optional noul escalation probability
between 0.2 and 0.8 is uncertain and also falls back; it is never relabeled as no. A supplied workflow stage locks the canonical
stage role even if another role appears in the allowlist. Advice cannot suppress
an existing baseline escalation. Advisory escalation neither reserves a reliability
budget nor escalates a model nor changes state; existing owners must separately
validate any future application. Provider output cannot grant permissions or approve
Tests, mutate code, run tools, reinterpret evidence or move workflow state.

The router retains at most 64 (configurable 1–128) typed sanitized receipts in memory:
the bounded typed request signals/references, UUID/hash, enums, identity, policy reason
and numeric usage/estimate. No unrestricted
context/exception is retained. There are no durable authoritative workflow decisions
in this isolated foundation, so it does not invent Task rows or attach advisory
receipts to existing Task audit/decision tables. Durable audit integration is deferred
to an explicitly reviewed activation design; receipts disappear on process restart.

## Dormant integration and operator configuration

No active CLI, HTTP, host, workflow or browser path imports/constructs this adapter.
Environment configuration alone **does not enable production routing**. Standalone
reviewed code must explicitly construct a router and its provider:

```python
from qa_sentinel.decisions.typesafe import TypeSafeSettings, TypeSafeDecisionProvider
from qa_sentinel.orchestration.decision_router import DecisionRouter

settings = TypeSafeSettings.from_environment()  # OFF unless flag is exactly true
router = DecisionRouter(TypeSafeDecisionProvider(settings), enabled=settings.enabled)
# router.decide(trusted_bounded_request) returns advice only; it executes nothing.
```

Environment names for an independently approved smoke: `QA_SENTINEL_TYPESAFE_ENABLED`
(exact `true`/`false`, default `false`), `QA_SENTINEL_TYPESAFE_MODEL` (no default),
`TYPESAFE_API_KEY` (server-side process environment only). Do not put keys in config,
logs, audit, request context or Git. Existing local/demo/preview/hosted behavior and
OpenAI role configuration are unchanged. OFF mode performs zero discovery/inference
requests and preserves baseline routing. Do not activate this on production.

The narrow adapter reuses existing `httpx` from the approved OpenAI runtime dependency;
no SDK or dependency addition. It pins the official HTTPS origin, rejects redirects,
disables environment proxies, never retries, rejects encoded/malformed/duplicate-key
responses, limits JSON responses to 16 KiB, requests to 4 KiB, discovered models to 32,
and choices to six. Response usage must match the verified schema; malformed/missing
usage makes the attempt invalid, never fabricated zero. Provider-reported cost is
always unknown because no currency field is supplied. Configured and reported model
identities remain distinct, with reported release-date provenance.

Default timeout is three seconds (maximum five) shared across discovery and inference.
HTTP connect/read/write/pool timeouts use remaining time; the deadline is checked on
every raw response chunk and completion. A blocking socket read may finish after
the deadline by up to its remaining transport timeout; OS DNS resolution may have
platform scheduling limits. Late output is rejected, never authorized. No thread or
second execution framework is introduced. One nonblocking lock prevents overlapping
calls; discovery + inference is at most two HTTP requests per attempt. Defaults:
four HTTP requests/provider instance and four/minute, including discovery/failures;
10,000 observed input tokens. Budgets are process-instance bounds, not durable/global
account limits. Restart/reconstruction resets them; production promotion needs review.

Optional operator-supplied input/output rates in `TypeSafeSettings` produce explicitly
labeled Decimal **estimates**, separate from unknown provider-billed cost. Observed
input-token/estimated-spend thresholds stop subsequent requests. They are **not hard
billing caps**: no verified API input/output token ceiling exists and one in-flight
call can exceed the observation threshold. Failed/unparseable responses may have
unknown consumed tokens/cost; the hard request-count bound still consumes that attempt.
No pricing defaults or automatic rate refresh is present.

Timeout, invalid key, rate limit, unavailable model/key, exhausted budget, malformed/
oversized response and provider errors fall back to the trusted deterministic baseline
with fixed reason codes. Raw HTTP/provider exceptions/bodies are not propagated or
audited. No retry-until-desired-answer and no privilege escalation.

## Validation and scope

Focused offline baseline, policy and fake-HTTP tests cover disabled/enabled behavior,
allowlists, canonical role preservation, lifecycle/correlation, low confidence,
malformed/oversized output, usage, model/schema identity, budget/rate/timeout,
credential reflection, bounded audit, contention and no active host/tool wiring.
Relevant existing routing/reliability/model/gate/state tests and one final Python
suite follow focused validation. No frontend or schema production changes; no migration.
No Phase 5 fixes, Hermes, experience learning or Task 6.4 implementation.

Inspection expanded from routing/model contracts to the existing role mapping and
reliability policy only to measure the real baseline, and to audit/persistence patterns
to decide against creating fake durable workflow history. Packaging was inspected to
confirm the existing HTTP dependency. No broad repository rediscovery.

Next gate: ChatGPT review, Phase 5 manual smoke and Tao's explicit merge/activation
approval; then separately authorize live account verification and Task 6.4 comparative
safety/quality/cost evaluation. No comparative provider improvement is claimed.
