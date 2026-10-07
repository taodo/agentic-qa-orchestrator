# Controlled real repair demonstration — Task 26

This runbook describes an explicitly authorized operator run against a prepared
external repository. Task 26's product hardening fixes a Planner/Implementer
stage-capability mismatch; it does **not** claim the live repair demonstration
has succeeded. No live StayFinder rerun was performed during implementation.
Automated regressions use mock Responses and temporary repositories only.

## Clean proving and scenario preparation

Operator example only; no runtime path, branch, commit or suite count is hard-coded:

| Setting | Value |
| --- | --- |
| Repository | taodo/stayfinder-demo |
| Example full workspace root | D:\stayfinder-demo |
| Clean branch | baseline/clean-v1 |
| Accepted clean ancestor | bd9c3f0847b384a47cd90bb7cfba23f4d111d2ac |
| Intentionally defective scenario branch | scenario/task-26-overbooking |
| Relative test cwd / target | backend / tests |
| Logical persisted Project key | stayfinder |

Before preparing the scenario, verify the clean ancestor independently, run the
[Task 25 target-check and target-test](REAL_TARGETS.md), and retain the clean
proving result. The known clean suite is 56 passed, 0 failed with reliable counts;
this is an operator baseline, not a product assertion.

The operator prepares the scenario **outside QA Sentinel**: exactly one intentional
production-code defect, no test modifications, all preparation committed on the
scenario branch, otherwise clean checkout. Keep trusted test dependencies ready.
QA Sentinel does not clone/fetch/check out repositories, inject defects, manipulate
Git, install packages, commit or push the target. The intentionally defective
scenario must **never be merged into baseline/clean-v1 or main**.

Stop other hosts/workflows, keep exclusive trusted access and inspect any prior
Task/job/reconciliation uncertainty before starting. Tests/conftest remain trusted
executable Python under Task 6, not an OS sandbox. Only local-real can execute;
public preview and hosted demo remain synthetic fake-only.

## Real local configuration

Use an existing current-schema host database and existing Project identity. Keep
host DB/config/frontend outside the target. For example, substitute your actual
private host paths and frontend build:

```powershell
qa-sentinel local target-check --database C:\private\qa-sentinel\state.sqlite3 --project-key stayfinder --workspace D:\stayfinder-demo --test-cwd backend --pytest-target tests --target-python D:\stayfinder-demo\.venv\Scripts\python.exe
qa-sentinel local init --database C:\private\qa-sentinel\state.sqlite3 --frontend-dist C:\work\qa-sentinel-repo\frontend\dist --project-key stayfinder --workspace D:\stayfinder-demo --test-cwd backend --pytest-target tests --target-python D:\stayfinder-demo\.venv\Scripts\python.exe --config C:\private\qa-sentinel\local.json
qa-sentinel local validate --config C:\private\qa-sentinel\local.json
qa-sentinel serve --config C:\private\qa-sentinel\local.json
```

Use separate operator-prepared environments for QA Sentinel and StayFinder. Their
FastAPI/Uvicorn pins can conflict; do not merge them into one environment. The
--target-python example above must name the same trusted target Python for clean
proving and the normal workflow's stored local config. Prepare the target .venv
and test dependencies manually outside this product; do not put interpreter paths
into Task/model payloads. See [interpreter constraints](REAL_TARGETS.md#isolated-target-interpreter--task-26),
including rejection of wrappers and linked paths and the POSIX copy requirement.
Validation reads only bounded interpreter headers and metadata, performs no
subprocess/probe, and does not prove target dependency availability. No live rerun
was performed as part of this interpreter hardening.

Supply OPENAI_API_KEY securely through the local process environment before real
validation/hosting, never chat, JSON, requirements, source, browser storage or
command flags. Validation presence-checks the key only; it makes no provider call.
Proving does not need a key. Host remains loopback-only at 127.0.0.1:8000 by default.
The workspace is the full repository, with backend only as test cwd. Existing
binding, read/mutation services, runner and application boundaries remain in use.
[Local setup and limits](HOSTING.md#real-project-onboarding).

## Blind requirement and Run

Create a Project-owned Task through the existing local UI/API using:

> Booking creation must never confirm a room when inventory is exhausted. A second request for the last available room must return room_unavailable, and concurrent requests for the final room must not create more confirmed bookings than available inventory. Diagnose and repair the implementation using repository evidence and existing tests. Preserve the documented booking contract and do not weaken tests to make the suite pass.

Do not add the injected diff, file/line/operator hint, known repair or unapproved
source snapshots. Researcher/Planner obtain bounded repository evidence through
accepted read-only turns. Implementer receives only accepted scope and controlled
source snapshots and proposes full-file CREATE/MODIFY with SHA preconditions.

Use normal **Run** through the existing host/application flow. Browser Run uses
the durable ExecutionJob; job SUCCEEDED is not Task DONE. Inspect refreshed Task
state and evidence. Expected happy progression is CREATED → RESEARCHING → PLANNING
→ IMPLEMENTING → TESTING → REVIEWING → DONE. ANALYZING/INVESTIGATING may occur only
if actual deterministic failure evidence and existing rules require them. Never
force a state, bypass a gate, edit accepted evidence or use target-test as workflow
TESTING. A fresh Task needs its own evidence; clean proving is not Task test proof.

For a safe stop, inspect the correlated gate/error/decision records and read-only
reconciliation first. Resume remains a separate synchronous restoration of stored
BLOCKED state; it does not repair evidence, reset budgets or execute tests. Do not
blindly Resume/Run unresolved calls, mutation or test reservations. The first
operator run's immutable incompatible Plan is not rewritten by this fix. After
review/reconciliation of prior work, the operator should use a fresh Task for a
fresh Planner output. Resume does not regenerate a completed rejected Plan.

## Planner stage boundary

The live finding reported successful research and passed Research/Plan gates,
followed by a valid proposal rejected as IMPLEMENTATION_GATE_REJECTED before any
mutation or TESTING. The Plan required both the repair and running tests as
implementation steps, despite already containing test_strategy. ImplementationGate
correctly requires every step COMPLETED; controlled Implementer cannot execute
pytest and canonical implementation commands_executed remains empty.

Task 26 adds a typed ImplementationStep.kind declaration:

- CODE_CHANGE: authorized production-code or test-file changes.
- STATIC_REVIEW: checks attestable from supplied source, such as comparing the
  lock/transaction code for preservation; no execution claim. Review-only files
  remain available in bounded snapshots but grant no write authority unless
  independently authorized by files_to_modify, a CODE_CHANGE step, or files_to_create
  for the corresponding operation.
- TEST_EXECUTION: downstream work, rejected inside implementation_steps by
  PlanGate's IMPLEMENTING_STEP_KINDS check.

Planner instructions and schema descriptions put all executable verification in
test_strategy / TESTING, never a duplicated required implementation step. A
correct plan lists the inventory guard repair and source-preservation checks in
implementation_steps, with existing exhaustion/concurrency tests only in
test_strategy. Writing authorized tests is code work, not executing them.
Implementer still has no pytest, shell, arbitrary commands, package-manager or
provider-side execution tools. If a plan nonetheless requires unsupported work,
it must report BLOCKED/replan rather than claim it ran. No required step is dropped,
skipped, automatically moved, or falsely completed to unblock mutation.

Declared mismatch stops through the existing PLANNING → BLOCKED path before
Implementer/source capture/mutation/tests. Existing gate/decision evidence includes
PLAN_STAGE_CAPABILITY_MISMATCH. No UI/error aggregation work is added; that is
outside this task. ImplementationGate's exact required steps, uniqueness, completed
work and no-replan guarantees are unchanged, including STATIC_REVIEW steps.

**Semantic limitation:** kind is a typed declaration, not proof that arbitrary prose
matches its label. A wrongly labelled CODE_CHANGE description such as “run tests”
cannot be fully identified by these structured fields. There is no natural-language
classifier or keyword heuristic. The prompt/Implementer refusal boundary remains
necessary. Legacy persisted plans without kind load as CODE_CHANGE for compatibility;
the existing strict provider schema requires explicit kind on new outputs. This
fallback makes no semantic assertion about legacy descriptions, and no old artifact
is edited or automatically reaccepted/repaired. Kind also narrows mutation scope:
STATIC_REVIEW-only paths are source context, not write-authorized paths. Legacy
CODE_CHANGE authorization remains compatible. The [mutation boundary](MUTATION.md#source-selection-and-limits)
shares write-scope calculation with the prompt and preserves all source limits.
No workflow state or execution capability is added.

## Evidence inspection and post-run verification

Inspect the Task's own records, rather than model or job success claims:

- Repository evidence linked to Researcher/Planner turns; blind diagnosis grounded
  in accepted reads, not operator hints or hidden reasoning.
- PLAN, declared step kinds, production repair scope, AC references and test_strategy.
- IMPLEMENTATION_PROPOSAL and applied IMPLEMENTATION, SHA preconditions/result hashes,
  mutation events, exact step results, and empty commands_executed.
- Real TEST_RESULT/TestRun from TestExecutionService with COMPLETED/PASS, reliable
  counts and correlated TEST_EXECUTION_STARTED/COMPLETED. The current expected
  suite is 56, not a runtime constant; failed tests never authorize DONE.
- Test Analyzer/Investigator records only if invoked, independent REVIEW coverage,
  gate/transition/decision evidence and actual final Task state.

After the workflow stops, independently inspect the external checkout using operator
Git, for example:

```powershell
git -C D:\stayfinder-demo status --short --branch
git -C D:\stayfinder-demo diff --stat
git -C D:\stayfinder-demo diff --check
git -C D:\stayfinder-demo diff -- backend/tests
```

Review the complete diff against the prepared scenario: only the authorized minimal
production repair may differ. Confirm tests/assertions and unrelated source are
unchanged and no unexpected files appeared. Preserve the observed Task/evidence
IDs, statuses, counts/reliability, provider-role invocations, exact scenario commit
and Git inspection result privately. Do not publish credentials, raw provider
responses or chain-of-thought. No live outcome can be claimed from automated
fixture success or the historical live-finding comment.

## Operator reset to the clean baseline

QA Sentinel performs no reset or Git rollback. Stop the host, verify no in-flight
execution or unresolved side effect, archive the scenario/repair diff and needed
Task evidence, and confirm the intended target root/reference before discarding
anything. Never merge the defective scenario into the clean branch.

Only after the operator explicitly decides to discard the scenario's tracked
changes, these manual commands restore tracked content to the accepted baseline
and switch to the existing clean branch:

```powershell
git -C D:\stayfinder-demo restore --source=bd9c3f0847b384a47cd90bb7cfba23f4d111d2ac --staged --worktree -- .
git -C D:\stayfinder-demo switch baseline/clean-v1
git -C D:\stayfinder-demo rev-parse HEAD
git -C D:\stayfinder-demo status --short --branch
```

Require the accepted clean commit and clean status. Archive/resolve unexpected
untracked files separately; these commands do not remove them. Re-prove the clean
baseline if needed. Keep prior Task evidence immutable; do not reuse a previously
bound repair Task against reset source or bypass its reconciliation checks.
