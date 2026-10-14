# Phase 5.8F-R1 — Manual smoke RCA and fix for #101

Status: implementation and focused verification complete; commit/push explicitly approved for the R1 branch. **NOT MERGED**. Stop after branch delivery for review. No Phase 5 acceptance claimed.

Repository: `taodo/agentic-qa-orchestrator`.
Accepted baseline: `feature/develop`, merge `fc0ca59157d82e53dbd36b12425f7ce20a31bcf7`.
Original fix: `f7045a4c5f22612871fd9bfde1fbc8662f52718b`.
Working branch: `codex/phase-5-8f-r1-manual-smoke-fix`, created from that exact merge.

## Verdict and runtime verification

**Confirmed implementation grammar gap; restarting the accepted merge alone cannot resolve this Test.** The running backend was using the v2 preparation path, and a fresh import of unchanged accepted-merge code reproduces the exact failure. This is not a Headed/Headless execution difference or Chromium cleanup failure.

Before edits, tracked checkout was clean on `feature/develop` at the accepted merge. Existing untracked logs/config/databases were preserved. Read-only process/port inspection identified PID 28076 serving `127.0.0.1:8000`, Python 3.12.10, started 2026-10-14 13:44:06 Asia/Bangkok:

```text
"C:\Users\spman\AppData\Local\Programs\Python\Python312\python.exe" "C:\Users\spman\AppData\Local\Programs\Python\Python312\Scripts\qa-sentinel.exe" local start --config .\qa-sentinel.local.json
```

A fresh probe using that exact interpreter resolved the editable `qa-sentinel` package to this checkout. The semantic/application files were written at 13:43:38, before process startup; the merge was committed at 13:39:38. Before R1 edits, the semantic source matched `git show` of the accepted merge after newline normalization. Its on-disk SHA256 was `6469e59d662ddea1535400c23e908526d1febde4e728a3b5ffdfd7b727870c87`.

These are provenance checks, not a claim that a fresh interpreter dumps the already-running process's Python modules. There is no live source-hash endpoint. Independent durable runtime evidence resolves the relevant ambiguity: all three failed smoke grounding receipts explicitly record `browser-grounder-v2`; live capability GET returns HTTP 200 and `local_operator_review: AVAILABLE` (the merged 5.8F API). A stale-only explanation is contradicted by the same exact rejection on fresh accepted code.

The local config selects `C:\Users\spman\.qa-sentinel\demo\state.sqlite3`, revision `0018`, and this checkout's `frontend/dist`. SQLite was opened only with `mode=ro`; no operator migration/update/delete was performed. Live `/` returned HTTP 200 with bytes identical to configured `dist/index.html` (SHA256 `f7dd76c1698a03870619f4aacc0a3de764146effb0786f2ddc4218f512372aa6`). The frontend is served by this backend; there was no separate listener on 5173. Backend planning/execution/automatic capabilities were AVAILABLE. No backend environment/key dump was taken; the diagnostic caller's missing `OPENAI_API_KEY` is not evidence that the running backend lacks its key. The host was not restarted or reconfigured.

## HAR, approval and reproduction evidence

The supplied `C:/Users/spman/Downloads/127.0.0.1.har` was available and examined as data. It has 13 entries, 2026-10-14 06:55:02–06:55:26 UTC. Both HEADLESS and HEADED POSTs return 201; polling transitions PREPARING → COMPLETED (200), with selected 1, runnable 0, needs attention 1, preparation errors 0, `run: null`, no QA outcome/evidence, and `INSUFFICIENT_TEST_INFORMATION` with no affected step.

| Mode | Batch ID | Grounding receipt ID |
| --- | --- | --- |
| HEADLESS | `c23c9073-ff6e-4eaa-8927-146887529993` | `89d8a441-d417-4ddf-a78c-cec4ccc50434` |
| HEADED | `896670b2-1665-4bbd-ae35-a67809ccef97` | `dc4dd999-055b-4f44-9c4c-a57c00923133` |
| Earlier HEADED, from DB/history | `d133e9f0-ea71-4980-8fc9-1ee4a90abeba` | `c3ce9721-f415-457a-87b7-634a199d4678` |

HAR execution-candidates marks canonical AI-generated TEST-001 `33462093-9000-5349-ae57-d528e543cbbb` APPROVED and eligible. Its approved hash and every preparation Test hash are `bfb72750c1c31adbc6ae793ae5475a4900a6d368c9f75fc5d4ebdb236109f4d0`, independently recomputed from the canonical HAR Test. Approval time is `2026-10-14T06:47:27.648538Z`. The sealed Target is `https://example.com`; all three scopes use Target hash `c72666639b90651556bb88e488827210416304dea151052b2eb6dd5a5bd8bef6`. Approval hash is `c1734646faed6585517974a4a0bf420ed09bf58bbbfbf18e1ae68e0bf503b093`.

The actual approved wording is:

- Title: Example Domain home page loads and displays its main heading.
- Precondition: The Example Domain home page is available for access.
- Step 1: Open the Example Domain home page. Expected: The home page loads successfully.
- Step 2: Observe the visible page heading. Expected: The heading "Example Domain" is visibly displayed.
- Overall: The Example Domain home page loads successfully and visibly displays the heading "Example Domain".
- Required evidence: Evidence of the successfully loaded home page with the visible heading "Example Domain".

All failed v2 receipts have null observation, model metadata, intent hash and browser error; DB observation count for this Test is zero. Trace: batch preparation → `application.browser_grounding.ground` → `test_intent` → `validate_summary`. The parser does not recognize `is visibly displayed`, so step 2 has no typed outcome and the supported two-outcome summary check rejects at the old `browser_test_semantics.py:42`. This occurs before observation/provider/materialization/execution.

The baseline probe isolated both gaps: correcting only the expected wording advances to `assertion_for` and fails at step 2 because `Observe the visible page heading` is not admitted. Correcting only the action still fails summary validation. Original smoke wording passes. Legacy v1 independently rejects the composed summary at its unchanged equality gate.

## Minimal implementation

Only the deterministic human-Test grammar changes in production: `is visibly displayed` maps to existing `HEADING_VISIBLE`; `Observe/Verify/Assert the visible page heading` is admitted only with a visibility outcome. A text-only outcome cannot discard the action's visibility claim. Matching is anchored; extra action/expectation claims remain rejected.

The original approved Test is not rewritten. The exact HAR Test hash remains unchanged after parsing. Unique exact current observed heading identity, sealed destination, PAGE_LOAD checks, exact text plus visibility, operation ordering, provider reference validation, immutable approval/Target seals and explicit execution remain in place. Failed historical receipts stay immutable and are not reused as successful preparations. No API/frontend/security/timeout/policy/retry changes, new dependencies or migrations.

Changed files:

- `src/qa_sentinel/agents/browser_test_semantics.py`: two bounded wording alternatives.
- `tests/integration/test_browser_semantic_bridge.py`: exact HAR fixture; original/manual wording × generated/imported × Headless/Headed; no-Spec/no-Requirement and unchanged content/Target seals; new wording in missing/ambiguous/malformed-output and real Chromium checks; extra claims/text-only visibility rejection.
- `docs/BROWSER_GROUNDING.md`: bounded wording contract.
- `docs/PHASE_5_8F_R1_REPORT.md`: this report and operator retest instructions.

## Exact verification commands and results

Commands run from the checkout; `.venv` tests use disposable migrated fixture databases, never the operator DB.

```powershell
# Before production fix: demonstrate exact manual wording failing in all four paths.
.venv/Scripts/python.exe -m pytest tests/integration/test_browser_semantic_bridge.py -k 'exact_smoke and manual' -q --tb=short
# Result: 4 failed, 22 deselected; Runnable 0. Expected red regression.

# After fix: semantic/generated/imported/mode and fail-closed regressions.
.venv/Scripts/python.exe -m pytest tests/integration/test_browser_semantic_bridge.py -k 'not real_chromium' -q --tb=short
# Result: 26 passed, 3 deselected, 17.56s.

# Affected existing grounding/receipt/policy regressions only.
.venv/Scripts/python.exe -m pytest tests/integration/test_browser_grounding.py -k 'not real_chromium' -q --tb=short
# Result: 53 passed, 15 deselected, 33.74s.

# Exactly one controlled real Chromium headless smoke, offline provider, new wording.
.venv/Scripts/python.exe -m pytest 'tests/integration/test_browser_semantic_bridge.py::test_real_chromium_load_and_visible_heading_evidence[200-Example Domain]' -q --tb=short
# Result: 1 passed, 6.42s.

git diff --check
# Result: passed.
```

The real smoke serves an isolated local HTTP 200 page with the unique heading. It creates a completed Run with PASS and actual ordered evidence: NAVIGATE, ASSERT_PAGE_LOAD, ASSERT_TEXT, ASSERT_VISIBLE. Mode parity/generated execution uses explicit offline fixtures; it is not a live-provider/visible-Headed acceptance claim. Focused results contain existing Starlette deprecation and SQLAlchemy migration-cycle warnings. No new cleanup failure occurred in this one real smoke.

Read-only RCA commands included `git status --short`, `git branch --show-current`, `git rev-parse HEAD`, `git rev-parse feature/develop`, `git remote get-url origin`, `git show fc0ca59157d82e53dbd36b12425f7ce20a31bcf7:src/qa_sentinel/agents/browser_test_semantics.py`, and process/port inspection:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|pythonw|node|uvicorn)(\.exe)?$' }
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 8000,5173 }
```

Inline Python probes parsed only relevant HAR bodies, instantiated canonical `CampaignTestSpecification`/`TargetSnapshot`, recomputed `content_hash`, isolated `test_intent` variants and queried the selected SQLite rows read-only. Logs: `.task101r1-rca-baseline.log`, `.task101r1-rca-after.log`, `.task101r1-red.log`, `.task101r1-semantic.log`, `.task101r1-grounding.log`, `.task101r1-chromium.log`. No HAR credentials were printed or copied into source/report. No full suite, frontend suite/build, live-provider model call or real visible-Headed smoke was run for R1; frontend production code did not change. Historical Chromium cleanup instability remains unresolved and must not be hidden by retries or timeout changes.

## Operator retest after review/approval

1. Activate the reviewed R1 changes in this editable checkout. In the existing backend terminal, stop gracefully with Ctrl+C, then restart from this repository using its documented workflow and the existing process environment/key:

   ```powershell
   Set-Location 'C:\Users\spman\Documents\Codex\2026-09-30\files-pasted-by-the-user-you\outputs\agentic-qa-orchestrator'
   git branch --show-current
   git status --short
   qa-sentinel local start --config .\qa-sentinel.local.json
   ```

   This rebuilds frontend, validates the configured DB and starts loopback service; it runs no test suite or automatic migration. Do not delete/reset the DB. The currently running host has not loaded this new grammar and requires that restart.
2. Refresh `http://127.0.0.1:8000`. Select the same approved TEST-001 with the same `https://example.com` Target. Do not edit/regenerate its wording, Browser Facts or plan. Submit a **new** explicit Headless batch; old completed Needs-attention batches remain historical failures.
3. A: exercise Spec → Generate → explicit Approve → Run selected → Headless. Verify a runnable Test creates a real Run and Results/Evidence. The exact prior TEST-001 should now pass semantic preparation if the live observation uniquely supports it; QA PASS still requires actual 2xx load, exact heading text and visibility at execution.
4. B: import an equivalent human Test into a campaign with no Specification/Requirement links, explicitly approve it, then Run selected Headless. Verify the same sealed assertions and real Results/Evidence.
5. C: Run the small approved Test in Headed mode; observe the visible Chromium window and inspect persisted Results/Evidence. Automated fixture parity alone is not acceptance of this step.
6. If any attempt fails, retain its new batch/grounding/Run IDs, structured reason/affected step/browser error, backend startup/version evidence and relevant HAR. Do not repeat until PASS. Observation/runtime failures remain separate from Needs attention and QA FAIL.

**Manual A/B/C must be rerun. Commit/push is authorized only for the R1 branch; no merge, deploy, issue closure or Phase 6 changes.**
