# Browser execution contracts and Chromium runtime (Tasks 5.1–5.3)

Task 5.1 defined contracts and policy only. Task 5.2 implements Chromium execution through an explicit trusted internal application service; public/browser Start remains synthetic-only.

Browser assertion failure is a QA outcome. Browser/executor infrastructure failure is an execution-system failure.

WEB execution does not require application source-code access.

```text
Approved immutable Run Test + immutable WEB Target snapshot
    -> BrowserExecutionPlan + snapshot-bound candidate provenance
    -> BrowserExecutionPolicy (pure static validation)
    -> BrowserExecutor port
    -> Playwright Chromium adapter (Task 5.2)
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
Old Runs without evidence still have no fabricated observation; their Run executor identity is truthfully backfilled SYNTHETIC.

ExecutorKind includes WEB_BROWSER, but public Create/Start input cannot select it. UnavailableBrowserExecutor validates then raises the fixed
BROWSER_RUNTIME_UNAVAILABLE code, without synthetic fallback, DB activity, result,
evidence or state transition. It is not wired into public Start or host composition.

Task 5.1 did not need a migration: existing immutable persisted evidence identifies its producer,
Task 5.1 did not accept browser Runs/plans for durable execution. Task 5.2 adds migration 0014 for executor/runtime identity, safe browser error code and per-test sealed plan columns; startup never auto-migrates. A browser-enabled Run now has an immutable
executor selection/version boundary, not inference from Target
existence or retroactive reinterpretation of legacy synthetic Runs.

## Inert plan and locator contracts

browser-execution-plan-v1 is frozen, extra-forbidden and discriminated by action:
NAVIGATE, CLICK, FILL, SELECT, CHECK, PRESS, WAIT_FOR, ASSERT_TEXT, ASSERT_VISIBLE,
ASSERT_URL. Locators discriminate ROLE, LABEL, TEXT, TEST_ID, PLACEHOLDER and CSS.
Roles and press keys are deliberately limited literals. Exact matching is default;
no regex/code fields. CSS is bounded selector data, never an executable expression;
engine-chain and explicit alternate-engine forms are rejected. The adapter forces
the CSS engine rather than passing an untrusted selector-engine expression.
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

## Static navigation policy and runtime enforcement

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
The Task 5.2 adapter adds same-origin/resolved-address policy for intercepted requests,
including scheme/port checks and rebinding protection, and rejects all redirects.
It enforces actual overall/action deadlines, evidence budgets and cleanup; screenshots
remain unsupported, as detailed below. Do not translate this policy pass into a reachability/health claim.

## Candidate provenance and durable execution seals

BrowserPlanEnvelope describes executable intent, not a new approval receipt.
Task 5.2 persists it as a sealed Run Test plan before execution. It binds Project/Campaign/Run/Run Test IDs, MANUAL/DETERMINISTIC/AI origin,
SHA-256 of canonical versioned plan content and its bounds, immutable Test snapshot
(including approved content receipt/links, excluding progress/outcome) and captured
Target snapshot. validate_envelope consumes authoritative detached repository Run
and Test records, checks ownership and all hashes, revalidates models and admission.
The plan is frozen; execution must revalidate the exact sealed plan against those
records, never a live Target or changed Test design. Task 5.3 adds a separate reasoning-only generator, described below.
Static validation and the deterministic runtime never invoke a model. No claim that a candidate plan was human-approved
or executed is made. The approved Test receipt identifies approved source content;
plan_hash identifies validated executable intent, not equivalent approval.

Task 5.2 persists immutable executor choice/plan provenance before execution within
accepted Run/persistence boundaries, as detailed below. Reuse Start lifecycle and
atomic result/evidence handling, not a second workflow. Extend TestExecutionResult
and the existing closed evidence policies only with reviewed typed browser variants
and truthful executor agreement. Do not fill synthetic evidence with browser claims.
Navigation/assertion observations are implemented below. Screenshot/page-error/console
variants and binary artifact storage/redaction remain deferred.
Never store secrets/raw console dumps/arbitrary JSON/local filesystem paths.

Playwright installation is explicit and separate from startup, as detailed below. Assert mismatches
produce completed QA FAIL and continue eligible tests. Launch/crash/unavailable
runtime errors remain system failures. No source workspace dependency is introduced.


## Task 5.2: what is actually executable

```text
Immutable Run + WEB Target + executor/runtime identity
    -> sealed manual BrowserExecutionPlan in each Run Test
    -> static admission + pinned runtime network policy
    -> official Playwright Chromium adapter
    -> real navigation/assertion observations
    -> typed TestExecutionResult / EvidenceDraft
    -> existing atomic Run Test/evidence completion
```

Creation/start are explicit internal service methods, not new public endpoints:
create_browser_qa_run and start_browser_qa_run. Configure the application with a
PlaywrightBrowserExecutor only in trusted local code. Existing API Start refuses
WEB_BROWSER Runs, and normal host/demo/preview/hosted composition never constructs
this executor. There is no public browser start/authoring UI. The separate Task 5.3
internal candidate generator is described below.

The Run seals executor_kind=WEB_BROWSER and adapter version, engine CHROMIUM,
official SDK version, Chromium revision and expected browser version. Every Test
owns its complete typed plan/envelope. Its plan hash and target/test provenance
are fingerprinted into the Run; immutability triggers prevent later identity/plan
updates. Actual browser version must match the seal before navigation. Runtime
executes only the persisted plan. Historical Runs backfill SYNTHETIC, keeping their
original preparation fingerprints and observations. 0014 downgrade refuses browser
history loss; safe downgrade preserves older SQLite immutability triggers.

### Installation and controlled local use

Install optional runtime dependencies explicitly:

```powershell
python -m pip install -e ".[browser]"
python -m playwright install chromium
```

Browser download is separate. No browser installation/download happens during startup or tests; configured local startup refuses outdated schemas and requires explicit operator migration to current head 0015. Official Playwright is pinned to 1.63.0. Chromium is the only
engine; executable paths, profiles and launch arguments cannot be supplied by plans
or operator request configuration. Fixed internal network safety switches are used.
Perform operator DB migration explicitly with the existing documented Alembic
configuration before opening the host; admission now requires 0015.

For a controlled fixture, create PlaywrightBrowserExecutor(trusted_local_origin=
"http://127.0.0.1:PORT") and inject it as browser_executor into the existing
QASentinelApplication. The trusted override accepts only a literal loopback origin
and only that exact scheme/host/port. Select approved tests and pass a UUID-to-
BrowserExecutionPlan mapping to create_browser_qa_run; then start_browser_qa_run
with its returned Run identity. Plans use non-secret manual test data, not credentials;
password filling/authentication is unsupported. No source workspace is required.
The integration fixture in tests/integration/test_playwright_runtime.py demonstrates
this composition without a live provider or external campaign.

### Network/resource enforcement and deliberate limitations

All intercepted HTTP(S) requests are forwarded by a bounded transport to a validated
pinned IP, with the original Host and verified TLS SNI/certificate. Every request
rechecks the resolved set; private/mixed sets or address changes fail closed. Chromium
cannot independently resolve/reach Targets: its direct traffic hits a deny-only local
proxy, loopback bypass is disabled and non-proxied WebRTC UDP is disabled. Service
workers are blocked; WebSockets, extra frames/pages, popups and downloads are refused.
No Playwright evaluate/JS injection, scripts/specs or arbitrary method dispatch exists.
Application JavaScript may execute normally within this restricted browser context.

Initial runtime refuses **all redirects**, rather than allowing a redirect path that
bypasses interception. It also refuses chunked/compressed/unknown-length responses,
attachments and responses over 4 MiB; request bodies are limited to 64 KiB, headers
to 16 KiB, requests to 100/test and concurrent forwarding to eight. These constraints
are explicit system/unsupported failures, never weakened assertions or fake success.
This is a controlled runtime foundation, not broad production website compatibility.
DNS uses at most four bounded daemon workers: an unresponsive OS resolver occupies
its slot until OS completion, while admission times out and creates no browser or
connection; exhaustion fails closed. No unbounded resolver queue or executor-shutdown
wait is introduced. No public internet is used by automated tests.

Per-action and overall test deadlines are enforced with async timeouts. All browser
page/context/browser/driver resources close in finally paths with separate deadlines
(one second for context, two each for browser and driver; one for proxy shutdown),
so a stalled context cannot prevent later cleanup attempts. Cleanup failure is a system failure. One process, isolated context
and controlled page per test; no persistent profile or saved download.

Assertion mismatches complete QA FAIL and remaining tests continue. Action timeouts,
DNS/TLS/unreachable/policy/launch/crash/overall-timeout/internal/cleanup failures are
system failures with fixed BrowserErrorCode values; existing RUN_EXECUTION_FAILED
and partial-result semantics are retained. Earlier committed evidence survives.
No browser-to-synthetic fallback exists. Raw SDK errors, paths, cookies, auth headers,
DOM/HTML/console dumps or observed text are never persisted as diagnostics.

BrowserObservation v1 records only navigation/assertion category, sealed test/plan
identity, step/action, match boolean, final QA outcome and actual Chromium version.
Existing policy projection displays WEB_BROWSER; synthetic legacy payloads remain
readable. Screenshot capture/storage is deferred: no suitable reviewed binary
artifact boundary exists, and nonzero screenshot requests fail closed.

Minimal frontend changes only correct stored-executor labels and hide Synthetic
Start for browser history; no visual redesign or browser execution control is added.
SDK-double cleanup/error tests remain active without browsers. Real integration tests
skip only if the package/binary is genuinely unavailable; the implementation validation
actually installed and ran Chromium against the controlled local server.

Broader safe network/response compatibility, authentication, self-healing and the
first external campaign remain later separately authorized tasks.


Runtime API references: [Playwright routing](https://playwright.dev/python/docs/api/class-route),
[BrowserContext isolation/routing](https://playwright.dev/python/docs/api/class-browsercontext),
[Chromium WebRTC IP handling](https://chromium.googlesource.com/chromium/src/+/376fc41e87a058f7a7b300b0ec3a4982b4ec0960/components/policy/resources/templates/policy_definitions/Miscellaneous/WebRtcIPHandling.yaml).


## Task 5.3: reasoning-only generation and explicit acceptance

```text
Approved immutable Test + receipt + immutable WEB Target
    -> bounded BrowserPlanGenerator / existing ModelAdapter (no tools)
    -> strict BrowserPlanOutput candidate, never generated code
    -> schema + static policy + approved-fact/literal-intent validation
    -> durable AI generation record (not evidence or authorization)
    -> explicit acceptance: same Task 5.2 seal + append-only receipt, one transaction
    -> separately invoked deterministic Start; no runtime model call
```

Only internal application methods are provided: generate_browser_plan,
retry_browser_plan_generation, get/list_browser_plan_generations,
get_browser_plan_acceptance and accept_browser_plan_generation. Inject an explicit
BrowserPlanGenerator(adapter, ModelSettings(...)) into trusted application code.
No model default is added; public/demo/hosted composition and HTTP Start remain
unchanged. Generation never starts a browser, resolves a Target, reads DOM/source,
or creates a Run/evidence/legacy Task/job. Acceptance creates one selected-test
WEB_BROWSER Run in CREATED; start_browser_qa_run remains a separate operation.

### Grounding limitation: explicit approved facts, not guessed page structure

There is no DOM inspection, semantic locator oracle or natural-language classifier.
A Test can supply one strict JSON precondition with contract_version=browser-facts-v1.
It is ordinary immutable Test content, reviewed through the existing human Test
approval; there is no new facts approval workflow or public configuration route.
Example (non-secret operator-known facts):

```json
{"contract_version":"browser-facts-v1","required_actions":[["NAVIGATE"]],"locators":[{"strategy":"ROLE","role":"heading","name":"Courses","exact":true}],"paths":["/courses"],"input_values":[]}
```

required_actions contains the exact non-assertion operation sequence for each
one-based approved QA Test step. Total required operations are at most 50. Locators,
paths and literal input/key/condition/check values must come from these supplied
facts; the configured Target base path is also a known navigation destination.
The model cannot manufacture additional facts. Output step_bindings maps each
plan step to an approved Test step, in nondecreasing order. The validator requires
all approved operations and an exact assertion for every step expectation, plus
the overall expected result. Supported literal expectations are exact ASSERT_TEXT,
ASSERT_URL for an authorized literal path, or VISIBLE/HIDDEN. Substring assertions,
unlisted locators/values/paths, missing operations/expectations and unsupported
runtime features are rejected. Navigation must be first; redirects/screenshots
must be zero. There is no automatic assertion weakening or retry-until-pass.

General human prose may be insufficient to safely compile into literal browser
assertions. Return CANNOT_PLAN/insufficient-information rather than guessing.
Matching allowed facts does not prove their semantic association with every human
step; the trusted caller must review the candidate before explicitly accepting it.
Refining a Test/facts uses existing review/version boundaries, never silent model
edits. No credentials are supported; operator facts/test values must be non-secret.

### Provenance, recovery and compatibility

Migration 0015 adds browser_plan_generations and browser_plan_acceptances only.
Generation snapshots include the approved Test/receipt, Target and SHA-256 hashes,
AI origin, prompt contract browser-plan-generator-v1, configured ModelSettings,
provider-reported ModelMetadata (independent model identity and authoritative usage),
timestamps/status, safe failure code and validated plan/hash. Missing usage remains
unknown/null; it is not fabricated zero or estimated pricing. No chain-of-thought,
raw response/request, refusal prose, credentials or prompt logs are stored.
These internal records are not folded into existing extraction/test-design usage
collections or execution evidence. Per-generation usage is readable here.

STARTED commits before one provider call, with no transaction spanning it. Context
contains complete immutable inputs and actual schema/capabilities, at most 60,000
characters / 196,608 UTF-8 bytes. Accounting uses actual rendered context; overflow
fails honestly without truncation. Domain records are capped at 256 KiB; the SQL
JSON envelope also has a one-MiB serialization ceiling. Reads/lists are scoped and
bounded to at most 50 records in deterministic timestamp/UUID order.

No automatic retries. Explicit transient/malformed/incomplete-response retry makes
an immutable linked candidate using identical input snapshots/settings/prompt,
maximum three attempts and one child per predecessor. Provider credentials/refusal,
policy/grounding/insufficient-input failures cannot be retried this way. Unresolved
STARTED attempts require reconciliation and are never silently replayed. New explicit
generation creates a different identity; it never rewrites a candidate or sealed Run.

Explicit acceptance rereads the candidate in the existing reserved Run creation
transaction, rechecks current eligible approved content/receipt and exact Target
hash, revalidates policy/grounding, and seals the exact plan with origin AI. A separate
immutable receipt binds generation ID to Run/Test/plan hash. Stale input or identity
mismatch refuses acceptance before commit. Replaying the same acceptance key returns
the original Run; a different candidate/key cannot repurpose its history. No model
or browser is called by acceptance. Runtime only executes the stored Task 5.2 plan.

Terminal generation history and acceptance receipts cannot update/delete. Downgrade
refuses any planning history; empty downgrade/re-upgrade is supported. Operator
migration remains explicit/manual, never startup. Existing 0014 browser envelopes
and fingerprints are unchanged; no new nullable envelope field alters old hashes.
SYNTHETIC and Task 5.2 runtime/network/FAIL/evidence rules remain unchanged.

No frontend/dependency changes, public planning/acceptance UX, external campaign,
DOM/screenshot AI planning or locator healing. Task 5.4 and Hermes/Jev/Phase 6 remain
separate future work.
