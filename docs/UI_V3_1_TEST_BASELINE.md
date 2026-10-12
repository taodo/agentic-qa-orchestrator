# UI V3.1 frontend baseline cleanup

Base: feature/develop at 2c75bfa4a955c35b71a5c1a3fbba526c2f8fd8ae.
Branch: feature/ui-v3-1-test-baseline-cleanup. NOT MERGED.

## Diagnostic classification

The five scoped files reproduced the 19 known baseline failures, plus one
intermittent native disclosure assertion (20 failures / 95 passes initially).

| Failing group/test | Classification | Evidence and repair |
| --- | --- | --- |
| CampaignPreparation: five deep links | A: stale expectation | AppShell intentionally exposes seven product links, not six legacy diagnostic links. Assert exact names and active Overview; legacy deep links stay supported without a falsely active product stage. |
| CampaignPreparation: Approved vs Not ready | A: stale placement | Overview uses compact counts; full saved approval/readiness assessment is in Audit/readiness. Open the existing disclosure, retain exact approval/blocker/aggregate and two-read assertions. |
| CampaignPreparation Overview fixture | B: stale mock | ProductOverview performs one bounded Run metadata read. Mock runs?limit=50 as an empty page; do not suppress unexpected fetch errors. |
| PreparationActions: blocked Draft/links | A: stale navigation | Test Cases diagnostic content is reachable through Advanced / Audit and Legacy test detail / import. Keep exact no-approval/no-POST assertions. |
| PreparationActions: focus then Traceability | A: stale navigation | Follow Advanced / Audit to Traceability; retain focus, one traceability read and one explicit approval POST. |
| PreparationActions: lifecycle progression | D: production regression | CampaignTransition existed only in unused CampaignOverviewPage. No mounted App route exposed Submit/Approve. Mount the existing component in Audit with the existing Campaign context/transition callback. Keep exact DRAFT -> READY_FOR_REVIEW -> APPROVED payloads and separate Not ready evidence. |
| PreparationActions: pending transition/navigation | D: same regression | Exercise Audit, retaining pending duplicate prevention, disabled action, unmount and no late refresh assertions. |
| ProjectCampaigns: empty list | A: stale wording | Current empty state is No QA workspaces yet. Retain loading and empty-state checks. |
| ProjectCampaigns: creation, safe failure, late Project completion, two invalid names, oversized objective (six tests) | A: stale accessible labels | Workspace name / Create QA workspace are current CampaignForm labels. Preserve exact metadata payload, one POST, returned identity, retained values, no automatic retry, stale completion and client bounds. |
| ProductHelp: routing/form | A: stale accessible label | Create QA workspace replaces Create Campaign. Preserve synthetic notice, exact request counts, no-network help and no hidden Task creation. |
| TestCasesWorkspace: local identity/navigation | A: stale navigation | Primary Test Design replaces legacy Test Cases link. Retain exact route, current-only filters, visible selection, truncation, CSV and no-POST assertions. |
| TestCasesWorkspace: keyboard/native disclosure | C: intermittent timing observation | Existing exact Enter/Space/native summary test failed on initial grouped run, passed on machine-readable repeat and focused/final runs. No arbitrary delay, assertion weakening or production change was made for this transient. |

No tests deleted, skipped, snapshot-regenerated or error output suppressed. JSON
reporting captured diagnostics without large DOM output; existing warnings remained
in the diagnostic logs. No generic timing workaround was introduced.

## Production scope

Only ProductV2 AuditPage mounts the existing CampaignTransition with campaign and
transition from useCampaign, in a small existing-style preparation section. No new
lifecycle logic, endpoint, readiness derivation, automatic action or request exists.
Existing usePreparationAction owns duplicate/unmount/error handling. Overview,
sidebar, themes, Target, approval gates, selected Run snapshots, evidence and
synthetic execution remain unchanged.

## Validation

Focused group results: CampaignPreparation 55, PreparationActions 34,
ProjectCampaigns 8, TestCasesWorkspace 16, ProductHelp 2 tests passed.

One final full frontend run after final source changes: 486 passed, zero failures,
31 test files. Executed via the installed Vitest entry point with JSON reporter
(equivalent test selection to npm test -- --run). Production build: TypeScript and
Vite passed, 101 modules. git diff --check passed.

Python suite not run: no backend changes. No live provider/network/Target calls;
tests use fake fetch and deny real browser transports. Dependencies, API changes,
migrations and persistence changes: NONE. No UI redesign. No manual live review.

The transient native disclosure timing deserves investigation only if reproducible;
this cleanup does not claim to have diagnosed or fixed its underlying timing.
