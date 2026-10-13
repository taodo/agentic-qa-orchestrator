# Bounded browser grounding — Task 5.8B

This is an internal trusted-local preparation capability. It observes a public WEB
Target and records a machine-grounding receipt for an already human-approved Test.
It does not create a QA Run, execute its assertions, claim QA PASS/FAIL, accept a
Browser Plan, finish a preparation item, or implement the final Run UX.

## Composition and provenance

The host may explicitly inject `PlaywrightBrowserObserver` and
`BrowserGroundingReasoner` into `QASentinelApplication`. Normal trusted-local composition now injects them for automatic batches;
demo/preview/hosted composition does not. There is no arbitrary observation HTTP endpoint. The existing exhaustive safe-error mapper covers the
two new internal artifact/reconciliation codes; no payload contract changes. The internal
`ground_browser_preparation_item` requires the exact Project, Campaign, preparation,
item and active attempt UUID. Immutable Test/approval/Target snapshots come from
that preparation, never replacement mutable live inputs.

STARTED is committed before inspection. Chromium/DNS and the model run outside
transactions. An immutable observation is committed before the single structured
model call. Short transactions validate and seal the outcome. Repeating a terminal
attempt reads its receipt without new work. An interrupted STARTED attempt or failed
completion persistence requires explicit reconciliation; it is never silently rerun.
No new worker, retry loop or generic cache exists.

`browser-grounding-observation-v1` contains scoped identity/hashes, fixed policy and
bounds, runtime identity, timestamps, page title/current path, visible semantic
candidate facts and observation-local `e1..eN` / `p1..pN` references. Its SHA-256 covers
canonical UTF-8 JSON excluding its own hash. No raw DOM, input values, cookie data,
storage, screenshot, arbitrary attributes or response bodies are stored/sent.

`browser-grounding-v1` is STARTED → GROUNDED / NEEDS_ATTENTION / SYSTEM_ERROR.
It retains exact observation identity/hash, Test and approval hash, Target hash,
scoped attempt identity, intent hash, typed mapping, deterministic constraints,
configured model settings and provider-authoritative metadata. Unknown usage stays
null. Context accounting measures the actual complete serialized input. Reasons
and deterministic action hints are fixed codes/text, never raw SDK exceptions.

## Bounds and supported surface

| Resource | Limit |
| --- | --- |
| Pages inspected | 1; no link traversal or clicks |
| Same-origin redirects during initial observation | 1 |
| Candidate nodes scanned, including hidden nodes | 80 |
| Path candidates | 20 |
| Page title / element text / name | 512 / 512 / 256 characters |
| Aggregate title, names, text and paths | 16,384 characters |
| Canonical observation | 65,536 UTF-8 bytes |
| Grounding model input | 60,000 characters and 196,608 UTF-8 bytes |
| Structured grounding output | 16,384 UTF-8 bytes |
| Test steps / operations per step / total manifest actions | 20 / 4 / 50 |
| Distinct grounded locators / paths / values | 20 each |
| Test-derived input value | 64 characters |
| Grounding receipt | 131,072 UTF-8 bytes |
| Inspection / navigation timeout | 20 seconds / 10 seconds |
| Automatic provider/application retries | 0 |

Exceeding any required bound is a typed limitation; there is no successful truncated
capture. The existing pinned transport retains 100 requests, 4 MiB per response,
32 MiB total response bytes, 100 headers / 16 KiB, bounded DNS and connection deadlines.
Browser startup and each cleanup operation retain the existing independent deadlines.

Fixed semantic queries observe native headings, buttons, links, textboxes,
checkboxes and comboboxes. Exact role/name, aria-label and textbox placeholder
locators are constructed and counted by tools. Unavailable labels and unsupported
semantics remain unavailable rather than guessed. Duplicate matches are ambiguous.
Unsupported native input types (including file/range/number/date controls) fail
closed instead of being relabeled as textboxes. Password/OTP/autocomplete-sensitive controls carry no name/text/locator/value.
Secret-looking page text causes a limitation rather than capture. Heuristic secret
rejection is conservative, not a universal sensitive-content detector; authenticated
and credential-dependent pages are unsupported.

## Reasoning and deterministic validation

The reasoner can only select current element/path/value reference IDs, supported
operations and literal assertion kinds. It has no model tools or browser handles.
The initial small Test grammar recognizes Open/Navigate/Visit, Click, Fill, Select,
Check/Uncheck and Verify/Assert. Controls require their exact observed name after
the verb (Fill uses `into`, Select uses `in`), so a name inside an input literal
cannot substitute for the intended control. Fill/Select require a leading JSON-quoted literal
(e.g. `Fill "Ada" into Name`); Check derives only true/false. Unsupported/ambiguous
prose returns Needs attention. This intentionally does not attempt general language
classification, arbitrary values or arbitrary journeys.

Element names must occur in the relevant action, or assertion grounding may use the
sole observed heading. Every Test step maps exactly once in order, including its
literal expected result; overall expected result must remain covered. Navigation
uses the observed Target base or an explicit Test path that is also observed; links
remain same-origin. No unseen page's controls can be invented. Multi-page/dynamic
journeys needing another observation are deferred.

The deterministic validator verifies ownership, immutable snapshots/approval,
current observation ID/hash, exact ordered operations, unambiguous references,
control roles/enabled state, same-step value derivation, literal expectations,
policy and bounds. Invalid outputs cannot become usable receipts. Insufficient
information, ambiguity, unsupported behavior, policy rejection, missing grounding,
invalid references and context/observation bounds are NEEDS_ATTENTION. Browser
infrastructure failures and provider unavailability are SYSTEM_ERROR. Neither is QA
FAIL, and no assertion outcome is fabricated.

The observer reuses the existing secured Chromium session and `PinnedNetwork`.
DNS admission/rebinding checks, exact pinned peer/TLS verification, same-origin
redirects, private-address denial, resource bounds, blocked workers/frames/popups/
sockets/downloads, proxy isolation and cleanup remain authoritative. Inspection
adds GET/HEAD-only admission, rejects navigation queries and credential headers,
and rejects Set-Cookie responses. A constructor-only exact loopback exception is
used solely by disposable integration fixtures, never public/operator payloads.
Inspection itself never fills, clicks or executes arbitrary JS/evaluate.

## Planner bridge and persistence

`system-browser-constraints-v1` resolves references into an exact action manifest,
step bindings and legacy-compatible allowlists. `BrowserPlanGenerator.prepare_system`
and `validate_system_candidate` use the existing structured plan/policy validator,
then require the exact grounded action/locator/path/value/assertion manifest. The
model cannot replace one allowed locator with another at a different step. Machine
provenance is explicit; no `browser-facts-v1` is inserted into Test preconditions or
pretended human-approved. Existing manual facts and reserved-facts protections stay
unchanged. B proves compatibility but does not persist a new 0015 planning receipt,
accept/seal/start a Run, or wire a public operation; those compositions belong to C.

Migration **0017** adds scoped `browser_groundings` and
`browser_grounding_observations` tables with composite ownership FKs, unique active
attempt receipts, canonical payload bounds, timestamp/terminal-shape checks and
immutable observation/terminal history triggers. Repository admission revalidates
full typed contracts and exact active attempt ownership. Existing 0015/0016 and Run
rows/fingerprints/triggers are preserved. Downgrade refuses any new history; empty
new tables can downgrade to 0016 and re-upgrade. Startup requires 0017 and never
migrates automatically. Operator migration remains explicit; operator DB/config
were not touched by this task. No dependency or external service is added.

5.8C must compose grounding and planning into audited mixed preparation/Run
materialization. 5.8D owns final Run UX and headed/headless wiring. No Hermes/Jev,
self-healing, authentication, source mutation or Phase 6 behavior is introduced.

Task 5.8C–E consumes this bounded capability through [automatic batches](BROWSER_BATCHES.md). Grounding alone remains non-execution history.
