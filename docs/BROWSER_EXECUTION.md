# Browser execution contracts and Chromium runtime (Tasks 5.1–5.6)

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
including scheme/port checks and rebinding protection. Task 5.6 adds bounded
same-origin main-frame GET redirects through this same boundary, detailed below.
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

Task 5.2 initially refused all redirects. Task 5.6 permits only the controlled
same-origin navigation redirects detailed below. It still refuses
chunked/compressed/unknown-length responses,
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

No frontend/dependency changes, public planning/acceptance UX, DOM/screenshot AI
planning or locator healing. Task 5.4 adds the trusted local composition below;
Hermes/Jev/Phase 6 remain separate future work.


## Task 5.4: generic controlled local end-to-end flow

`qa-sentinel local web` composes the existing application, BrowserPlanGenerator,
configured Planner role/official Responses adapter and PlaywrightBrowserExecutor.
It is a trusted local operator CLI, independent of normal HTTP host composition.
Demo/preview/hosted HTTP modes and public Start remain synthetic-only. No new API,
worker, workflow, executor, evidence store or workspace binding is introduced.
Target != source repository != execution workspace. Example/demo Targets are
replaceable validation fixtures, never hard-coded product dependencies.

Prerequisites: explicitly install the existing browser extra and Chromium (above),
manually migrate the operator DB to 0015, and use the normal Project/Target and
Campaign preparation flow. Associate a WEB Target; import a current Test linked
to approved Requirements; include one strict browser-facts-v1 JSON precondition
using the existing CSV/Markdown importer; explicitly review/approve that Test.
Supply only non-secret operator-known facts, literal expectations and test data.
No DOM/source lookup or fact inference occurs. General prose, unsupported actions
or insufficient facts produce a persisted bounded failure, not guessed execution.
No source repository, local pytest configuration or frontend build is required by
this CLI. Existing lower-level host configuration is unchanged.

### Explicit operator commands (PowerShell)

Set the existing operator DB and scoped UUIDs, not an execution workspace:

```powershell
$db = "C:\operator\state.sqlite3" # replace with your existing migrated DB
$project = "<Project UUID>"
$campaign = "<Campaign UUID>"
$test = "<approved current Test UUID>"
$env:OPENAI_API_KEY = "<set locally; never put it in documents or command arguments>"
qa-sentinel local web generate --database $db --project-id $project --campaign-id $campaign --test-id $test
```

Generate makes one configured provider call (default: existing Planner model and
budgets; optional `--model` changes only the configured model). It makes no Target
request, DNS resolution or browser launch, and creates no Run. It returns the
bounded durable candidate record: UUID, approved input snapshots/hashes, configured
and provider-reported model/usage (missing usage remains null), status, strict plan
and plan hash. No credentials/raw provider response/hidden reasoning is emitted.

Review the full candidate against the approved facts and Test intent; generation
success alone is not authorization. Then explicitly accept the same candidate:

```powershell
$generation = "<SUCCEEDED generation UUID>"
qa-sentinel local web candidate --database $db --project-id $project --campaign-id $campaign --generation-id $generation
qa-sentinel local web accept --database $db --project-id $project --campaign-id $campaign --generation-id $generation --idempotency-key "<unique acceptance intent>"
```

Accept reuses Task 5.3 current Test/approval/Target revalidation and the immutable
AI-origin seal/acceptance transaction, returning a CREATED Run. It performs no
provider or Target access. Keep the same key for an intentional acceptance replay;
do not accept a different candidate through that key. It currently selects one
Test per generated-plan Run. Approval/facts authoring remains the existing Test
review boundary, with no separate approval workflow or browser UX.

Only a separate explicit Start accesses the captured Target:

```powershell
$run = "<accepted Run UUID>"
qa-sentinel local web start --database $db --project-id $project --campaign-id $campaign --run-id $run
qa-sentinel local web results --database $db --project-id $project --campaign-id $campaign --run-id $run
```

Start needs no API key/model and executes only the exact stored plan and Target
snapshot through Task 5.2. Changing the live Target after acceptance does not
replace that snapshot. Run/test RUNNING commits before execution. PASS or assertion
FAIL returns execution COMPLETED (CLI exit 0 for both); infrastructure failure
returns execution FAILED and a fixed browser error (exit 1), never synthetic fallback.
Start cannot restart a terminal or uncertain Run. No automatic provider retry,
plan regeneration, locator healing, weakened assertion or runtime AI is introduced.
Results reuses existing bounded stored reads (10 Tests/page, evidence previews;
`--after-position` selects the next page). It needs neither provider credentials
nor the browser SDK and performs no Target requests. Run runtime identity, captured
Target, AI plan origin/hash and typed actual observations remain auditable in the
existing Results UI/read APIs too. No screenshots/network/DOM evidence is fabricated.
All command JSON escapes control characters and has a one-MiB output limit; overflow
returns a safe error without silently truncating. Generated records retain their
existing 256-KiB bound. Failed post-action output does not undo persisted history;
use Candidate/Results reads to inspect it rather than repeating side effects.

For a disposable local HTTP fixture ONLY, add `--trusted-local-origin
http://127.0.0.1:PORT` to Generate, Accept and Start. This reuses the existing exact
numeric-loopback scheme/host/port exception; the URL still comes from the normal
configured Target and immutable snapshot, never from a substituted fixture. Omit
this option for a public WEB Target. There is no named-site exception or private
network general allowlist. Optional manual external validation requires an
operator-selected compatible Target, approved facts and locally supplied credentials.
Do not infer success if provider/network/runtime is unavailable; retain the safe
failure and report it. Existing redirects, response framing, authentication,
subresource/origin and screenshots limitations above still apply unchanged.

Automated proof: `python -m pytest tests/integration/test_local_web_e2e.py -q`
uses two replaceable disposable HTTP applications with different Project/Target
URLs, paths, locators and expectations, the real Chromium adapter and an offline
provider transport. It proves zero Target access during Generate/Accept, exact AI
seal, durable Results, PASS, QA FAIL and unavailable-target system failure. It uses
no external site, source repository or real provider token. Broader browser authoring
UX and Results UI expansion remain later Phase 5 tasks.


## Task 5.5: stored browser Results presentation

Run Results displays the stored WEB_BROWSER executor and Playwright/Chromium
runtime versions/revision/adapter identity. It uses the immutable Run Target
snapshot, never the current Target. Each browser Test disclosure shows the sealed
plan origin/version and shortened hash; native Full plan hash disclosure exposes
the full hash as inert wrapped text, with no network interaction. Plan operations,
input values and mutable generation candidates are not displayed.

Evidence uses only the existing bounded server policy presentation: navigation,
text/visibility/URL assertion, snapshot step, Matched/Mismatch, recorded Chromium
version, source/executor, host recording time and sequence. Observed URL/path,
locator and expected/actual text are deliberately absent from this projection;
Results does not guess them from the sealed plan or Target. Preparation expectations
remain separately labeled snapshot content. No raw payload JSON, screenshots,
DOM/console/network/trace viewer or extra evidence is introduced.

COMPLETED + QA FAIL remains an assertion outcome, distinct from FAILED execution
with the stored safe system/browser code and NOT_EVALUATED/PARTIAL results. Missing
evidence is disclosed, not backfilled. Existing synthetic history stays synthetic;
backend legacy compatibility identifies old Runs as SYNTHETIC. If wire identity or
browser fields are missing, the UI shows unavailable rather than inferring them
from a WEB Target, evidence prose or defaults.

Only existing bounded Results/snapshot reads and explicit evidence expansion are
used. No Generate/Accept/browser Start control, provider/browser/Target/DNS/source
operation or new API is added. UI V3 styles, wrapping, native keyboard disclosures,
dark/light tokens and pagination remain unchanged. Broader browser authoring,
screenshots and richer evidence remain deferred.


## Task 5.6: deterministic resilience and security hardening

### Failure semantics and lifecycle

Existing BrowserErrorCode values remain authoritative; no duplicate error family,
API or schema is added:

| Surface | Bounded system code / behavior |
| --- | --- |
| SDK/driver/browser/context/page startup | BROWSER_LAUNCH_FAILED; acquired resources still close |
| DNS failure/deadline/worker exhaustion | BROWSER_DNS_FAILED |
| TCP/no response or bounded proxy request deadline | BROWSER_TARGET_UNREACHABLE |
| TLS/certificate validation | BROWSER_TLS_FAILED; strict original-host SNI/certificate verification |
| Origin/private address/rebinding/peer mismatch | BROWSER_NETWORK_DENIED |
| Redirect escape/malformed Location/loop budget | BROWSER_REDIRECT_DENIED |
| Navigation/operation/protocol observation deadline | BROWSER_ACTION_TIMEOUT |
| Whole Test deadline | BROWSER_TEST_TIMEOUT |
| Unexpected page/context/browser closure/crash | BROWSER_CRASHED |
| Unsupported capability/framing/header/body/request/resource bound | BROWSER_UNSUPPORTED_FEATURE |
| Cleanup/finalization deadline/failure | BROWSER_CLEANUP_FAILED |
| Non-network SDK action error (including invalid/ambiguous locators), unknown exception | BROWSER_INTERNAL_ERROR; recorded transport/policy errors and disconnected-browser CRASH retain precedence; raw SDK messages are never classified or exposed |

A deterministically observed assertion mismatch remains COMPLETED + QA FAIL;
subsequent selected Tests continue. A missing assertion condition reported by the
SDK's bounded condition timeout retains the accepted assertion semantics, but an
async execution/transport stall is a system action timeout. CLICK/FILL/other operation
inability is never manufactured assertion evidence. HTTP 4xx/5xx responses with
supported bounded framing are real responses: status alone neither fails the
execution system nor invents QA FAIL; sealed assertions decide the QA outcome.
Unsupported framing still fails independently of status.

Run/test RUNNING and each prior result/evidence completion retain existing short
committed transactions. No transaction spans browser/network work. Later runtime
or cleanup failure preserves earlier committed results/evidence and leaves the
uncertain Test unevaluated; no per-step buffered observation becomes a fabricated
completion. No runtime step retry, new context after failure or duplicate evidence.

The context drains admitted routing handlers within the overall deadline before
completion. Failure from a late background request cannot silently become PASS.
Route abort/websocket close errors are contained in safe event-task handling.
Unexpected close/disconnect events are distinct from deliberate final cleanup.
Context/browser/driver/proxy close deadlines remain independently 1/2/2/1 seconds;
a failed partial driver startup also closes its SDK manager within two seconds.
Cleanup failure remains a system failure, including after observed assertions.

There is no accepted Campaign browser Stop/cancellation API. In-process async
interruption still runs finally cleanup and propagates interruption without
fabricating FAIL. Abrupt host/process termination cannot guarantee Python finally;
RUNNING history is never silently replayed, and Start does not restart it. No new
Stop/resume/reconciliation product workflow is introduced here.

### Controlled same-origin redirects

The sealed plan's existing redirect_limit (0–5; unchanged default 3) now bounds
cumulative HTTP redirect hops across the Test. Zero denies all redirects; loops
terminate at the budget. Accepted statuses are 301/302/303/307/308; other 3xx,
missing/ambiguous Location, unsafe scheme, credentials, fragment, controls,
malformed/deep escapes, changed scheme/host/port and overlong destinations reject.
Relative and absolute same-origin Locations may include queries, but URLs/query
values/headers are ephemeral transport data and never error/evidence text.

Origin remains the immutable Target snapshot, never a live Target. Each followed
request revalidates DNS/address sets, private/mixed/global policy and rebinding,
connects to the pinned literal IP, verifies the peer, and uses strict original-host
TLS. The trusted local exception is still only the exact sealed numeric loopback
origin. No general cross-origin, private-network or named-site allowlist exists.

Chromium never receives a 3xx response. Playwright native redirect handling may
skip interception; the runtime withholds the response, deliberately aborts that
navigation, waits within the same action deadline for Chromium's internal abort
interstitial commit, then issues one fresh controlled navigation to the validated
Location. Each hop is fetched once; the terminal response is not fetched twice,
the original operation is not retried, the same page/context is retained, and
ASSERT_URL sees the actual terminal URL. The internal handoff has no evidence.
Unexpected/non-internal transitions remain denied. No invented HTML/error document
or JavaScript injection is used.

Initial compatibility is deliberately **main-frame GET navigation only**, including
GET navigation initiated by CLICK. Non-GET redirects, subresource redirects and
redirect Set-Cookie semantics are unsupported rather than silently rewriting a
method/replaying a body, losing cookie changes or allowing native egress. Fragments,
authentication and broader redirect compatibility remain deferred. Task 5.3 AI
candidate validation remains unchanged and requires redirect_limit=0; positive
budgets are available through the already accepted manual/deterministic plan path.
Historical seals/Run snapshots are not rewritten or rerun.

### Resource bounds and unsupported capabilities

- 100 requests/Test, including all redirect hops; eight concurrent forwards.
- 100 headers and 16 KiB wire headers in each direction. Strict HTTP status/header
  syntax and duplicate rejection prevent ambiguous framing/Location handling.
- Request body 64 KiB; response body 4 MiB; new aggregate reserved response budget
  32 MiB/Test, including concurrent/incomplete transfers.
- Full admitted request lifetime 15 seconds; existing DNS/connect/drain/header/body
  sub-deadlines are 2/3/3/5/5 seconds, all subordinate to action/overall deadlines.
- Existing plan action/overall, evidence count/size and cleanup budgets are unchanged.
  HEAD and HTTP 204/205 have honest no-body handling; ordinary bodies need a bounded
  unambiguous Content-Length.

Chunked/compressed/unknown-length bodies and attachments remain explicitly
unsupported. Adding safe chunk/decompression parsing needs separately reviewed
wire/decoded byte and framing accounting; no unbounded compatibility shortcut was
added. Duplicate response headers, including multi-Set-Cookie, fail closed.

Popups, downloads, frames, workers/service workers and sockets remain blocked with
safe unsupported failures. Context permissions are explicitly empty and a fixed
internal deny-permission-prompts Chromium safety switch refuses permission prompts;
no plan/operator browser flags, clipboard/geolocation/device grants, credentials,
password filling, arbitrary evaluate/JS, extensions, screenshots/video/trace or
filesystem actions are enabled. Site JavaScript may execute under the accepted
restricted browser, but no generated code or runtime AI is added. This remains a
controlled browser boundary, not an OS sandbox or universal website compatibility
claim.

Primary references: [Playwright redirect routing caveat](https://playwright.dev/python/docs/api/class-page#page-route)
and [Chromium permission denial switch](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/components/permissions/switches.cc).
Deterministic local HTTP/SDK/TLS/DNS doubles and real local Chromium tests cover
redirects, failures, limits, cleanup, FAIL continuation and preserved history. No
public internet/provider tokens are used in automated validation.


## Task 5.7: trusted local operator UI

The existing UI now exposes the accepted browser pipeline in **local mode only**.
Use the existing Project → Target → Campaign flow; no named site has special status.
UI V3 layout/styles remain unchanged. Synthetic selection/start remains available
and distinct from WEB_BROWSER; a WEB Target alone never chooses an executor.

### Source-free local setup

Create/select an existing persisted Project and explicitly migrate its operator DB
to head 0015 while stopped. Configure a browser-only local Project without dummy
workspace paths or pytest targets:

```json
{
  "database": "C:/operator/state.sqlite3",
  "frontend_dist": "C:/checkout/agentic-qa-orchestrator/frontend/dist",
  "host": "127.0.0.1",
  "port": 8000,
  "projects": [{"key": "your-existing-project", "browser_only": true}]
}
```

Use `qa-sentinel local validate --config ./local.json`, then
`qa-sentinel local start --config ./local.json`. Start rebuilds the frontend as
before. This configuration performs no repository/MutationService/pytest composition
or validation. It never creates Projects, bootstraps or auto-migrates the DB,
installs browsers/dependencies or executes tests during onboarding. The optional
accepted Playwright extra and Chromium must be installed explicitly as documented
above. A missing SDK yields unavailable browser capability; a missing Chromium
binary produces the accepted bounded launch failure at explicit Start.

Browser-only hosting may start without provider credentials, allowing stored
candidate reads, acceptance, Results and already accepted Run Start. Generation
requires OPENAI_API_KEY supplied in the **server process environment only**, never
JSON, Test facts or frontend forms. The UI receives AVAILABLE/UNAVAILABLE capability,
not the key/environment. Existing source/pytest local configs (no browser_only flag)
retain their workspace, interpreter, command and key validation. Configurations
containing browser-only Projects always require an existing migrated DB, including
lower-level serve. Source-only lower-level bootstrap behavior is unchanged.
`local init` remains the existing source/pytest config initializer; author the bounded
browser-only JSON above explicitly. The CLI `local web` remains available.

### Explicit preparation and execution

1. In **Test Design**, open a Test's review and choose **Prepare browser facts**.
   Author ordered required operations per Test step, one of the six accepted
   locator strategies (ROLE/LABEL/TEXT/TEST_ID/PLACEHOLDER/CSS), relative paths and
   non-secret input values. Nothing is inferred, suggested or fetched from a site.
   Saving validates ApprovedBrowserFacts, exact locator matching, step/action bounds
   and navigation paths server-side. The first required operation is NAVIGATE.
   The whole canonical facts object must fit the **existing 512-character Test
   precondition limit**; it is never split or truncated. Larger grounding remains
   unsupported, rather than changing the approval/persistence contract.
2. Saving creates an immutable **HUMAN_EDIT successor Test**, supersedes the current
   version through the accepted edit evidence boundary, and requires fresh explicit
   approval. The original approved Test, receipt and old Run snapshots remain intact.
   Approve the successor through the existing human Test approval controls. Facts
   are part of its content hash and later generation/seal provenance, not a side store.
   Passwords, credentials, cookies and authentication flows remain unsupported.
   The form requires an explicit non-secret operator declaration; it does not claim
   to infer whether arbitrary human input is secret. Runtime password filling still
   fails closed under the accepted policy.
3. In **Execution**, use **WEB_BROWSER preparation** to select one current Test.
   Server readiness distinguishes missing WEB Target, unapproved/superseded Test,
   missing/invalid facts, static policy rejection and unavailable provider capability.
   No readiness/capability read resolves DNS, probes a Target, invokes a model or
   launches Chromium. Click **Generate Browser Plan** explicitly; it persists the
   accepted one-attempt generation and may call the configured model, never the Target.
4. Review the **read-only candidate**: stored Test/Target identity and hashes,
   ordered actions, locators/paths/inputs, step bindings and limits. Configured and
   provider-reported models stay separate; each provider token category remains
   unknown when absent. No raw provider response, reasoning, SDK object or persistence
   JSON is exposed. Candidate history is loaded explicitly, limited to 20 records;
   detail is loaded on request. Generation failure/STARTED history is never auto-retried.
5. Click **Accept Browser Plan** separately. The accepted application method
   revalidates current Test/Target approval, seals the exact candidate and creates a
   CREATED WEB_BROWSER Run without model, browser or Target access. A failed response
   retains the acceptance idempotency key for explicit retry. No generated plan editing.
6. On that Run, separately click **Start Browser Run**. Only this operation launches
   Chromium/accesses the immutable Run Target. It has no model/API-key dependency
   and executes only the sealed plan. Busy actions prevent duplicate clicks; no
   auto-generation, acceptance, Start or runtime retry occurs. Completion refreshes
   the existing bounded Results/evidence. COMPLETED + QA FAIL remains a QA outcome;
   system failures preserve prior evidence and the accepted safe browser error code.

### HTTP/security boundary

New scoped routes live under `/api/v1/projects/{p}/campaigns/{c}/browser`:
- Inert typed resources: GET capability; GET tests/{t}/readiness;
  POST tests/{t}/facts (immutable human edit, never model/browser).
- **Local host only**: POST tests/{t}/generate; GET generations (20 summaries);
  GET generations/{g}; POST generations/{g}/accept (idempotency_key);
  POST runs/{r}/start. Existing Results/evidence APIs are reused.

Real operations are absent in demo/preview-demo/hosted-demo and bare API composition.
Local browser requests require a numeric loopback peer and the exact configured
numeric loopback Host/port; unsafe requests additionally require matching Origin.
Present foreign/null Origin is rejected on reads too. This prevents cross-site
browser writes and DNS rebinding; there is no CORS/private-network allowlist or
request-selected runtime/URL/browser policy. Use the advertised loopback URL and
same-origin built UI. Requests are bounded to 32 KiB before parsing; accepted typed
schemas reject extra code/command fields. Candidate responses use a named bounded
projection, not raw records; source/env/provider details remain server-side.

All Task 5.6 network/redirect/DNS/IP pinning, unsupported-capability, cleanup and
evidence restrictions remain unchanged. No screenshots, autonomous inspection,
self-healing, generated code or public browser execution service is introduced.
Automated HTTP/browser tests use disposable generic loopback fixtures and a fake
provider, including both PASS and QA FAIL. No external Target or provider token is
needed. Manual operator smoke should verify dark/light/mobile wrapping, keyboard
facts authoring and the three separate clicks with an operator-approved Target.


### Reserved facts authoring boundary

`browser-facts-v1` is a reserved Test precondition contract. Generic Test edits
cannot add, alter, reformat, duplicate or delete it. Submitted reserved strings
must exactly match existing strings; omission carries existing facts forward
unchanged while ordinary preconditions remain editable. The generic textarea
shows only ordinary preconditions. Only the dedicated application facts command
may replace reserved content, after ApprovedBrowserFacts validation and literal
`non_secret: true` declaration, through the same immutable HUMAN_EDIT successor
and fresh-approval lifecycle. Historical imported content remains readable; no
migration, rewriting or broader import-contract change is introduced.
