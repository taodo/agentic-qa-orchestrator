# Automatic browser batches — Task 5.8C–E

## Normal operator flow

Configure a Project-owned WEB Target and associate it with the Campaign. In Test
Design, either **Import Test Cases** (canonical CSV/Markdown) or **Generate from
Specs**. Specifications are optional for legitimate source-free browser Tests.
Review complete Test meaning and explicitly approve it with a reviewer label.
Missing traceability is informational under the existing source-free approval
policy; unresolved explicit Requirement references, missing expectations/evidence
and other information markers still block approval. Approval never visits the
Target, calls a model or starts Chromium.

Select approved executable Tests (up to 500) in Test Design, imported Test Cases or
Execution. Click **Run selected**, choose **Headless** (default, recommended) or
**Headed** (visible execution), then **Run**. The explicit Run action authorizes the
automatic preparation and execution batch. Normal use requires no Browser Facts,
locators, candidate acceptance, executor selection or hashes. Advanced browser
planning remains a distinct manual Generate → Accept → Start capability; reserved
`browser-facts-v1` content stays protected.

The durable submission returns immediately. The existing single-host worker
processes one workflow at a time, observes each immutable Target/Test selection,
then makes at most one tool-free structured grounding request per inspected item.
The deterministic application reloads persisted observation/grounding artifacts,
revalidates scope/hash/approval and materializes the exact approved action manifest
through `BrowserPlanOutput` and the existing system-candidate/policy validator.
Plan compilation requires no second model call. It never guesses a missing action,
locator, path or value, inserts machine Browser Facts into human Test content, or
executes generated code. Observation uses the accepted headless secured observer;
execution uses the selected mode with the same plan/policy/evidence semantics.

## Whole-batch truth and recovery

All selected items remain in immutable Browser Preparation history. Needs-attention
items carry safe reasons, affected steps when known, and remediation hints; they do
not become QA FAIL/SKIP. Preparation system errors are also isolated per item.
Only sealed runnable items enter a `qa-run-browser-v3` WEB_BROWSER Run. Zero
runnable items create no Run or QA result. The existing Run executor records actual
navigation/assertion evidence atomically, continues after assertion FAIL, and stops
on genuine execution-system failure while preserving earlier completed evidence.

Results lists browser batch history as well as Runs. Batch detail prioritizes all
selected Test identities, PASS/FAIL/Needs attention/execution errors, bounded
step/evidence previews and actual execution duration. Evidence details reuse Run
Results pagination. Immutable Target/runtime audit context is secondary.

Same-key/same-selection/mode submission reuses the batch; changed selection/mode
conflicts. Explicit UI retries retain the same key and never automatically replay
auth failures. Reads/navigation/refresh invoke neither model nor browser. Polling
is sequential and stops at terminal state, interruption, navigation or unmount.
Persisted CREATED submissions and sealed CREATED Runs can resume safely. Stranded
PREPARING/STARTED or RUNNING work is never replayed. Explicit **Acknowledge reviewed
interruption** retains STARTED history and any uncertain RUNNING Run; it does not
fabricate completion, clear evidence, rerun assertions, or retry grounding. Review
saved outcomes before explicitly submitting a new batch. This is not exactly-once
execution, a cancellation API or an automatic reconciliation/retry mechanism.

## Secure local setup

Use the QA Sentinel runtime interpreter for these explicit operator commands:

```powershell
python -m pip install -e ".[browser]"
Remove-Item Env:PLAYWRIGHT_BROWSERS_PATH -ErrorAction SilentlyContinue
python -m playwright install chromium
```

**The supported installation is Playwright's default per-user browser cache**, under
`%LOCALAPPDATA%\ms-playwright` on Windows (`~/.cache/ms-playwright` on Linux,
`~/Library/Caches/ms-playwright` on macOS). Install and run as the same OS account,
with the accepted pinned Playwright SDK. Install Chromium explicitly; there is no
startup/test-time installation, arbitrary executable path, custom browser-folder
configuration or automatic dependency management. An earlier custom-folder install
does not satisfy this contract: unset `PLAYWRIGHT_BROWSERS_PATH` and explicitly
install into the default cache. Runtime rejects that override even if it is empty,
along with `PLAYWRIGHT_NODEJS_PATH`, `NODE_OPTIONS`, `PWDEBUG` and `DEBUG`. Remove
those variables from the host process environment before starting. The SDK identity
check is read-only; missing browser binaries are reported at launch as a safe
runtime failure, never Synthetic fallback.

Stop the host, back up the operator DB, and explicitly migrate **that configured
DB** to head **0018** with the existing [local hosting procedure](HOSTING.md).
Startup/validation do not auto-migrate. The new additive tables record submission,
immutable machine plan receipts and Run-Test links; existing snapshot fingerprints,
grounding history and evidence are unchanged. Downgrade refuses new batch history
loss. No dependency is added by Task 5.8C–E.

Browser-only local configuration remains `browser_only: true`: no source repository,
workspace, pytest target or target interpreter is needed. Run the normal
`qa-sentinel local start --config ...` with `OPENAI_API_KEY` supplied only in the
server environment. Do not enter credentials into Test input/expectations or model
requests. Numeric loopback/same-origin protections and the accepted DNS/IP-pinned,
private-network/redirect/resource/time policy remain mandatory. No private-address
allowlist or custom runtime flags are exposed to normal operator requests. Demo,
preview and hosted-demo remain fake-only and mount no real batch execution routes.

## Bounded implementation and limitations

New local routes below `/api/v1/projects/{p}/campaigns/{c}/browser`:

- `POST tests/{t}/review`, `POST tests/approve-selection`: explicit human review;
- `POST batches`: bounded immutable selection/mode/idempotency command;
- `GET batches`: at most 20 column-projected history records;
- `GET batches/{id}`: at most 100 selected rows (UI 50), two evidence previews each;
- `POST batches/{id}/acknowledge-interruption`: explicit non-retrying acknowledgement.

The selected batch is bounded to 500. Ordinary browser request bodies remain 32 KiB;
only hash-pinned bulk approval allows 128 KiB for up to 500 IDs/hashes. No HTTP
endpoint accepts observation/grounding/plan claims or request-selected URL/policy.
Fixed observation bounds remain one page, 80 elements, 20 paths, 16,384 text
characters and 65,536 serialized bytes. Unsupported authentication, multi-page
exploration, downloads, unsafe network access, secret input or ambiguous/missing
controls become Needs attention; no self-healing or retry-until-PASS is implemented.
A GUI smoke remains necessary for visual Headed confirmation on the operator host.
