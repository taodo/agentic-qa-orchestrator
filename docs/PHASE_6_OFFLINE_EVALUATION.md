# Tasks 6.4A + 6.5: offline evaluation boundaries

Issue #102; starting SHA `ad8a0b7ee84223f061f861d4092b56bab6d4fddd`.
Predecessor #100 is APPROVED WITH NOTES, NOT MERGED and remains frozen.
This is a stacked branch, not a new develop-based implementation. Phase 5 #101/#92
changes are isolated; both Phase 6 branches need reconciliation/re-review and Tao's
explicit approval before merge. No active routing, host, browser or UI changes.

## Reproduction

From the task checkout root, without provider keys or installation:

```powershell
python scripts/evaluate_decision_safety.py
python scripts/evaluate_decision_safety.py --format json
python scripts/evaluate_experience_poc.py
python scripts/evaluate_experience_poc.py --format json
```

Both scripts load that checkout's source, so an editable install pointing at another
worktree cannot accidentally select its evaluation code. CLI output is bounded and
invalid fixture errors disclose a fixed code, not payloads/exceptions. The input path
is an explicit operator fixture argument; nothing discovers/reads operator databases,
Hermes profiles, credentials, source repositories or Target pages. Reports are saved
reference outputs under `benchmarks/`; no production store is opened/written.

## 6.4A oracle and metrics

`decision_safety_v1.json` is a human-labeled fixed adversarial corpus based on Issue
#102 and accepted contract semantics. Each row declares the intended accepted/rejected
advice, final role, escalation and reason. Sources and case IDs are explicit; SHA-256
binds the exact bytes. The runner reuses DecisionRequest, DecisionRouter, final
`arbitrate` policy and the existing TypeSafe adapter with MockTransport. It creates no
parallel policy/router and never selects a live transport/provider.

Trusted risk/permission/evidence flags originate in fixture construction, never in
provider advice. Typed request rejection covers raw instruction/secret/foreign-scope
fields; it does not prove general natural-language injection detection. Model metadata
is validated by the adapter; unknown provider/schema pairs are rejected by contracts.
Known provider labels alone are not cryptographic identity: active wiring must bind a
trusted adapter/configuration and validate the producer of risk/scope/evidence signals.

The suite includes an actual allowlisted alternative outside a workflow stage, where
baseline Planner and advisory Researcher differ. All six role/stage cases keep the canonical role locked. It also includes forbidden privileges/actions/approval, confidence
manipulation, expiry, changed correlation/hash replay, permission/evidence locks,
unknown model, malformed/oversized/duplicate JSON, noul thresholds, failures, rate,
request/observed-token/estimated-spend gating, reconstruction reset and canary redaction.

Deterministic clock and identities make reports byte-reproducible. Cases are at most
100, each at most three decisions, with no sleeps/retries. Fixture reads cap at 64 KiB
before parsing; duplicate keys/nonfinite JSON are rejected; output caps at 64 KiB.
Existing parser request/response bounds remain intact. These are structural bounds,
not an operating-system wall-clock or live-provider SLA claim.

Metrics are computed from actual returned receipts: oracle agreement, baseline oracle
agreement, invalid output, rejected request, fallback, unsafe accepted advice,
false/missed final escalation, fake proposal/mock HTTP counts and audit-canary leaks.
A mismatch fails the runner (exit 1); corrupt oracle tests prove it cannot manufacture
PASS. Invalid fixture is exit 2. No receipt causes a transition/action or QA outcome.

Reference result: **76 cases, 82 decisions, 82 oracle matches, 64 fallbacks, zero
unsafe accepted advice, false/missed final escalation or canary leaks**. Baseline
agreement is separately recorded, not renamed model accuracy. Each adapter instance
has its own budget; reconstruction demonstrably resets it. Audit retains at most two
receipts in the experiment; the production default remains 64/max128. Advisory replay
is not a single-use execution permission: correlation/hash/expiry rejects changed or
expired inputs, but identical bounded advice may be requested again within lifetime.

**LIVE EVALUATION = NOT VERIFIED. Production promotion = BLOCKED.** Fixture providers
are scripted stimuli, not Jev reasoning. No quality, calibration, latency, cost savings
or account availability improvement is claimed. Provider-billed cost remains unknown;
no price/token estimate is substituted for actual billing. Observed spend/token gates
can overshoot on an in-flight request or lose unknown usage from invalid responses;
they and request counts are instance-local, not durable/global financial caps.

## Future live comparison rubric (not implemented/authorized)

Prerequisites: Phase 5 smoke/reconciliation/re-review; Tao's explicit activation and
bounded live-call approval; authenticated model/version discovery, response compatibility,
account tariff/credit verification, trusted risk/permission producers and a reviewed
production audit/budget design. No key is available for this task.

Use the identical versioned corpus plus independently reviewed genuine-alternative
and held-out cases. Freeze labels before provider output; separate stage invariants
from routing quality. Compare baseline vs provider raw proposal vs policy-authorized
advice, including raw false/missed escalation and policy-blocked errors. Report sample
sizes, class imbalance, disagreements and uncertainty, not only aggregate accuracy.
Evaluate confidence reliability/Brier or calibration bins against independent labels
only where confidence pertains to that labeled decision; never conflate choice
confidence with noul probability. Record actual configured/reported model, usage,
request counts, measured p50/p95 latency, availability/fallback and verified monetary
rates/billing provenance. Missing usage/cost remains unknown. Match context/settings,
use a fixed maximum call budget and no retry-until-label-match. Zero observed safety
violations is necessary but not proof of universal safety or sufficient for promotion.
Any privilege/state/approval/evidence breach blocks promotion regardless of accuracy.

## 6.5 PoC scope

`experience_poc.py` is **Hermes-inspired synthetic fixture code, not Hermes integration**.
There is no Hermes import, installation, runtime, native profile, session search,
skill execution, provider call, production persistence or promotion API.

Fixtures supply separate synthetic historical evidence and a synthetic reviewed
manifest, hashed against immutable experience content. A PROMOTED label alone is
insufficient: exact Project/Campaign/Target/snapshot scope, role/lesson, review seal,
evidence identity/hash/verified flag, time and required facts are checked. Manifest
review labels are synthetic prerequisites, not approvals performed by the PoC and not
cryptographic trust attestations. Future production mapping needs real persisted QA
artifact/approval verification and authorization; this PoC does not provide that.

Current observation must be unambiguous and at most 30 seconds old. Experience must
be unexpired (maximum 90-day lifetime); current facts override contradictory history.
Historical locator/path hints are symbolic fixture keys, never executable selectors;
keys absent from current observation reject. This is not real DOM/locator validation.
CANDIDATE/VALIDATED/SUPERSEDED/RETIRED records are not usable. No state transitions or
automatic learning are performed. Duplicate/conflicting facts and identities reject.

Retrieval uses deterministic scope/role/fact matching, not embeddings/Hermes search.
At most 32 explicit experiences/evidence/reviews and 32 scenarios; one query selects
up to five hints (default three), with 128–4096-byte context bounds (default2048).
Stable ID ordering is reproducible, not a semantic ranking claim. Count/byte omissions
have explicit REJECT reasons; no silent transcript truncation. Context contains only
fixed lesson guidance and historical/current references. Free-form memory notes,
commands, secret canaries and old selector/path values never enter it. This closed
projection resists fixture injection without claiming a general prose detector.

Reference result: **24/24 scenarios match; seven hints used, seventeen rejected**.
Five role examples plus stale locator/path, scope leakage, missing/changed provenance,
unreviewed states, expiry, current contradiction, old observation, injection and byte
bounds are covered. No measured improvement in real agent quality or token savings.
See [Hermes research/ADR](PHASE_6_HERMES_RESEARCH.md) for options and recommendation.

## Validation and handoff

Focused A/B then relevant Phase 6 and existing orchestration/security/model tests,
followed by one final full Python suite and diff check. No frontend, dependency or
migration changes. No changes to reviewed predecessor code, Phase 5 or active workflow.
Task 6.6 is not implemented; recommendation is a separately reviewed QA Sentinel-owned
verified experience store design. Native Hermes runtime integration remains deferred.
