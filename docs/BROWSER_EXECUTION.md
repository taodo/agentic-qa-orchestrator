# Browser execution foundation (Task 5.1)

Task 5.1 defines contracts and policy only. It does not perform real browser execution.

Browser assertion failure is a QA outcome. Browser/executor infrastructure failure is an execution-system failure.

WEB execution does not require application source-code access.

```text
Approved immutable Run Test + immutable WEB Target snapshot
    -> BrowserExecutionPlan + snapshot-bound candidate provenance
    -> BrowserExecutionPolicy (pure static validation)
    -> BrowserExecutor port
    -> future Playwright adapter (Task 5.2)
    -> existing TestExecutionResult + typed EvidenceDraft persistence boundary
```

## Reused architecture and executor identity

Run creation freezes approved Test/Requirement content, receipts, links and optional
WEB Target context; snapshot_fingerprint seals that context. Existing Start consumes
only persisted Run Tests and calls the synthetic executor between short committed
transactions. Test completion and evidence persist atomically. FAIL continues;
normal mixed results mean COMPLETED / FAIL. Infrastructure errors mean FAILED /
PARTIAL or NOT_EVALUATED, retaining committed earlier results.

Before Task 5.1 there was no Run executor column or selector: Start was synthetic-only.
Persisted evidence already had immutable source/schema/kind/variant/strategy identity.
The closed reviewed SyntheticEvidencePolicy now maps that identity explicitly to
ExecutorKind.SYNTHETIC. TestExecutionResult names its producing executor and validates
agreement with evidence. The read-only evidence projection adds executor_kind from
the registered typed policy, never parsing summary prose. Historical legacy payloads
retain their reviewed synthetic fallback; rows and snapshot hashes are not rewritten.
Old Runs without evidence still have no fabricated observation or producing executor.

ExecutorKind includes WEB_BROWSER for future plans, but current Create/Start input
cannot select it. UnavailableBrowserExecutor validates then raises the fixed
BROWSER_RUNTIME_UNAVAILABLE code, without synthetic fallback, DB activity, result,
evidence or state transition. It is not wired into public Start or host composition.

No migration is needed: existing immutable persisted evidence identifies its producer,
no browser Run or browser plan is accepted for durable execution yet, and no new
column/table/speculative persistence is introduced. Current migration head remains
0013 and startup never auto-migrates. A future enabled browser Run needs an immutable
executor selection/version boundary reviewed before use, not inference from Target
existence or retroactive reinterpretation of legacy synthetic Runs.

## Inert plan and locator contracts

browser-execution-plan-v1 is frozen, extra-forbidden and discriminated by action:
NAVIGATE, CLICK, FILL, SELECT, CHECK, PRESS, WAIT_FOR, ASSERT_TEXT, ASSERT_VISIBLE,
ASSERT_URL. Locators discriminate ROLE, LABEL, TEXT, TEST_ID, PLACEHOLDER and CSS.
Roles and press keys are deliberately limited literals. Exact matching is default;
no regex/code fields. CSS is bounded selector data, never an executable expression;
engine-chain and explicit alternate-engine forms are rejected. A future adapter
must force the CSS engine rather than pass an untrusted selector-engine expression.
Unknown versions/actions/fields fail closed. No evaluate/code, method name, browser
args, process, shell, filesystem, generated spec, downloads or sleep actions exist.
Text resembling code stays literal input/expected text, never evaluated.

Bounds:
- 1–50 actions; action timeout 100–30,000 ms;
- test timeout 1,000–120,000 ms; no action timeout above its test budget;
- text/FILL input up to 4,000 characters; general locator/SELECT values up to 512;
- CSS up to 256; relative destinations up to 2,048;
- at most 5 redirects, 20 evidence envelopes, 3 screenshots, 2 MiB per screenshot
  (thus at most 6 MiB screenshot budget), subject to future storage/secret policy.
- WAIT_FOR means a named locator condition (visible/hidden/attached/detached), never
  an arbitrary delay. These are contracts, not pretend timers or screenshots.
Existing evidence remains capped at 20 records/test and 2,048 bytes/payload.

## Navigation policy and runtime security gap

NAVIGATE and ASSERT_URL use origin-root-relative paths, such as /courses. They
cannot replace the captured Target authority. Absolute/network-path destinations,
backslashes, malformed percent encoding, control/space characters and encoded
leading authority escapes fail closed. TargetSnapshot revalidation retains HTTP(S)
only/no userinfo authority. Default admission rejects known nonglobal IPs, mapped
private IPs, localhost, single-label/internal hostnames and ambiguous numeric hosts.
Private destinations require explicit trusted host policy construction; a plan or
public request cannot enable it. No DNS lookup or Target probe is performed.

Static strings do NOT secure redirects, DNS rebinding, public names resolving to
private networks, service workers, popups, subresource requests or browser traffic.
Task 5.2 must apply same-origin/resolved-address policy to every request and redirect,
including scheme/port checks and rebinding protection, before enabling real execution.
It must enforce actual overall/action deadlines, redirect/evidence/screenshot budgets
and cleanup. Do not translate this policy pass into a reachability/health claim.

## Candidate provenance and Task 5.2 handoff

BrowserPlanEnvelope is an inert candidate, not a new approval receipt or execution
record. It binds Project/Campaign/Run/Run Test IDs, MANUAL/DETERMINISTIC/AI origin,
SHA-256 of canonical versioned plan content and its bounds, immutable Test snapshot
(including approved content receipt/links, excluding progress/outcome) and captured
Target snapshot. validate_envelope consumes authoritative detached repository Run
and Test records, checks ownership and all hashes, revalidates models and admission.
The plan is frozen; execution must revalidate the exact sealed plan against those
records, never a live Target or changed Test design. AI is a provenance label only;
no planner/provider call exists. No claim that a candidate plan was human-approved
or executed is made. The approved Test receipt identifies approved source content;
plan_hash identifies validated executable intent, not equivalent approval.

Task 5.2 must decide and persist immutable executor choice/plan provenance before
execution, within accepted Run/persistence boundaries. Reuse Start lifecycle and
atomic result/evidence handling, not a second workflow. Extend TestExecutionResult
and the existing closed evidence policies only with reviewed typed browser variants
and truthful executor agreement. Do not fill synthetic evidence with browser claims.
Navigation/assertion/screenshot/page-error/console variants and screenshot artifact
storage/redaction are deferred until actual observations can be produced safely.
Never store secrets/raw console dumps/arbitrary JSON/local filesystem paths.

Install/map Playwright only in that separately authorized task. Assert mismatches
produce completed QA FAIL and continue eligible tests. Launch/crash/unavailable
runtime errors remain system failures. No source workspace dependency is introduced.
