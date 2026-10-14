# Phase 5.8F implementation plan — Issue #101 including authoritative UX addendum

Base: f6e3f3eb790417f408fa0339a3901a77d8b62c64.
Branch: feature/phase-5-task-5-8f-browser-grounding-contract-fix.

1. Confirm normal overall-summary equality gate and literal-only grounding mismatch through focused regressions.
2. Add a closed typed semantic bridge at canonical Test intent: account for composed summaries, successful page load, visible/text heading wording. Preserve legacy literal intent hashes and reject unsupported claims. Bind only exact unique current observed elements/paths; validate every model reference and seal the exact action manifest.
3. Execute a typed successful-load assertion through secured Chromium and record what it checks. Constituent step outcomes support the summary; never claim a separately asserted overall result.
4. Put the existing supported-findings generation workflow first in Test Design; link Generate from Specs to that same panel, keep Import Test Cases obvious, and preserve explicit selection/review/generation.
5. Replace normal trusted-local bulk reviewer/note inputs with an explicit local-operator provenance contract recorded in existing immutable receipt fields, distinguished from authenticated identity. Preserve legacy operator assertions, authorization/CSRF, conflict and item results.
6. Expose bounded row sizes and current-page header selection; distinguish loaded selected Tests from server-filter approval descriptors and unloaded records. Preserve exact explicit Run IDs and the 500 bound. Keep Advanced Browser secondary and native keyboard controls.
7. Progressively verify semantic regressions, preparation/batches, controlled real Chromium, browser/security regressions, one final Python suite, frontend suite/build, diff hygiene. No dependencies/migrations, unrelated UI or Phase 6 work.
8. Commit/push only the task branch and post one complete FINAL REPORT on #101 including UX acceptance and provenance/selection semantics. NOT MERGED; manual A/B/C acceptance after review/merge remains required.

## Completion and verification record

Implementation steps 1-6 are complete, including local-operator approval before Target selection without changing source-free eligibility. The final affected UI checks passed (53 tests across ProductV2, TestCasesWorkspace and BrowserBatches), and TypeScript/Vite production build passed.

One final Python suite ran: 2,567 passed, 11 skipped, 3 failed. The API import-boundary failure was fixed by placing provenance input handling in the application layer and its focused guard passed. Both original Chromium failures passed in focused follow-up. That follow-up had 137 passed and one different observation cleanup failure (BROWSER_CLEANUP_FAILED); the three controlled Chromium cases then passed in isolation. This remains an intermittent runtime/cleanup validation risk, not a clean full-suite result. No browser limit, retry or policy was relaxed.

Focused browser/security/schema/UI regressions recorded 142 passed; final local provenance, eligibility, import-boundary and missing-response checks recorded 9 passed. The frontend suite recorded 537 passed before the last capability-loading guard; its affected 53 tests were checked after that guard. Full suites were not restarted after the usage-limit interruption, as requested.

Delivery remains limited to the dedicated branch and one FINAL REPORT on #101. NOT MERGED. Live-provider operator acceptance A/B/C, including visible Headed Chromium and responsive/manual accessibility verification, remains pending review/merge.
