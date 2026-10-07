# Real target proving — Task 25

The proving run verifies target composition and deterministic pytest execution. It does not authorize mutation and it does not itself perform QA workflow reasoning.

A passing clean proving run is a prerequisite for the first controlled StayFinder defect-repair demonstration.

## Purpose and ownership

Proving is an explicit **local-real CLI** operation on an external prepared,
trusted repository. An existing persisted Project identifies the software;
the frozen, extra-forbidden TargetProfile and ProjectWorkspaceBinding retain
its absolute workspace root only in trusted host memory. Neither Project nor
Task payloads acquire paths, credentials, commands or runtime objects. The
profile is not stored in SQLite or a proving history/configuration table.

The workspace root is the **full target repository**, including backend and
frontend. A relative test cwd such as `backend` changes only pytest's cwd and
target scope. `tests` then resolves beneath backend. Repository-read and later
mutation configuration still use the full root. Those configuration constructors
validate metadata; proving does not construct MutationService or read source
contents to prove its configuration. No model, agent, repository tool turn,
workflow runner, transition or implementation execution is invoked.

## Windows operator walkthrough — example only

The following is an operator example, not a built-in path, Project or target:

| Setting | Example |
| --- | --- |
| Target repository | taodo/stayfinder-demo |
| Clean reference branch | baseline/clean-v1 |
| Accepted clean commit | bd9c3f0847b384a47cd90bb7cfba23f4d111d2ac |
| Known current backend suite | 56 tests; informational, never asserted by QA Sentinel |
| Full workspace root | D:\stayfinder-demo |
| Relative test cwd | backend |
| Relative pytest target | tests |

1. Prepare and independently verify that trusted checkout at the clean reference.
   Verify its baseline and absence of source changes with your normal operator
   tools. Proving does not clone, fetch, inspect Git state or switch branches.
   Strongly prefer separate prepared environments: QA Sentinel in its own .venv,
   the target in its own .venv with the target's pinned test dependencies. The
   operator prepares these independently; QA Sentinel never creates virtualenvs
   or installs dependencies. Use --target-python for an explicit native Python
   executable from the target environment; tests/conftest remain trusted code.
2. Use the existing local UI/API to create/select Project key `stayfinder` in
   your initialized, current-schema QA Sentinel database. Stop the host and
   other execution against that database/workspace before proceeding. Example
   host-owned paths below are separate from the target repository. A missing
   Project or database is rejected; these commands create neither.
3. Check the target without execution, from your installed QA Sentinel environment:

   ```powershell
   qa-sentinel local target-check --database C:\private\qa-sentinel\state.sqlite3 --project-key stayfinder --workspace D:\stayfinder-demo --test-cwd backend --pytest-target tests --target-python D:\stayfinder-demo\.venv\Scripts\python.exe
   ```

   Expect fixed check codes and `Target status: TARGET_READY`, exit 0. This
   performs **zero subprocesses**, source-content reads/writes, model/provider
   calls, workflow transitions or database writes. No OPENAI_API_KEY or frontend
   build is needed. A ready snapshot does not prove package availability,
   collection success or future filesystem stability.
4. Explicitly request one deterministic proving execution:

   ```powershell
   qa-sentinel local target-test --database C:\private\qa-sentinel\state.sqlite3 --project-key stayfinder --workspace D:\stayfinder-demo --test-cwd backend --pytest-target tests --target-python D:\stayfinder-demo\.venv\Scripts\python.exe --timeout-seconds 120
   ```

   Inspect execution status, PASS/FAIL/UNKNOWN, exit code, duration, counts,
   reliability and truncation flags. Require PASS with reliable counts for a
   successful clean proving result. Do not assume exactly 56 tests in product
   logic. Independently verify the trusted checkout remains clean afterward.
5. Only after a clean proving result, configure the existing real workflow if
   desired. For example, with your actual QA Sentinel frontend build path:

   ```powershell
   qa-sentinel local init --database C:\private\qa-sentinel\state.sqlite3 --frontend-dist C:\work\qa-sentinel-repo\frontend\dist --project-key stayfinder --workspace D:\stayfinder-demo --test-cwd backend --pytest-target tests --target-python D:\stayfinder-demo\.venv\Scripts\python.exe --config C:\private\qa-sentinel\local.json
   qa-sentinel local validate --config C:\private\qa-sentinel\local.json
   ```

   Validation still checks OPENAI_API_KEY presence for **real workflow hosting**;
   proving never needs that key. Supply it securely through the local environment
   only when preparing real workflow execution. Do not put it into a command,
   config, Task, chat or report. [Hosting](HOSTING.md#real-project-onboarding)
   explains validation and `serve --config` with its loopback-only boundary.
   Proving authorizes no repair; this task implements no StayFinder defect or
   repair demonstration and no browser/frontend target testing.

Repeat `--pytest-target` for explicitly prepared directory or `.py` file targets
(maximum 16 distinct targets). `--project-id <UUID>` may replace `--project-key`;
it must resolve an existing Project. Test cwd defaults to `.`. Timeout is finite,
positive and at most 120 seconds. `--help` documents both commands. Paths with
spaces require normal shell argument quoting. Only --target-python selects the
trusted native target interpreter. Generic argv, shell/wrapper scripts, custom
environment, pytest flags and node IDs are not exposed by the proving profile.

## Isolated target interpreter — Task 26

Run the QA Sentinel CLI/server from its own prepared environment. Supply exactly
same target Python to target-check, target-test and local init. The operator example
above uses D:\stayfinder-demo\.venv\Scripts\python.exe; this is not a product constant.
local init writes python_executable inside the private host JSON projects entry;
normal workflow TESTING and CLI proving then use the same ExecutionConfig policy.
Do not put this value into Project, Task, model output or API request payloads.
Only the host-owned local config stores it; it is not persisted into SQLite or
rendered in proving/readiness output. Public/demo configurations cannot accept it.

Explicit paths must be absolute existing executable regular files with a native
Python filename (python/python3/versioned python on POSIX, python.exe on Windows).
No symlinks/junctions in any component, UNC/device paths, traversal, ADS, shell
syntax or control characters are accepted. A bounded binary header check rejects
scripts disguised as Python; it does not cryptographically prove Python identity
or discover installed pytest/dependency versions. The operator must trust and
independently verify the executable/environment. POSIX virtualenvs commonly use
symlinks; prepare a native copy-based environment outside QA Sentinel instead.
There is no automatic interpreter probe, fallback, venv creation or installation.

Without python_executable, the canonical QA Sentinel process interpreter is used
for backward compatibility. This default is unsuitable when host/target pins
conflict. Invalid explicit settings fail closed, never silently use the host.
CommandPolicy revalidates the interpreter before each run. As with existing target
paths, exclusive trusted access is required; concurrent replacement is not an OS
sandbox guarantee. -P/-s, full-root rootdir/confcutdir, backend cwd, target scope,
secret-free environment, plugin controls, timeouts and capture limits are unchanged.
The target environment must already have pytest and the trusted test dependencies.

## Path and execution policy

Absolute workspace root must exist and remain external: equality, parent and
child overlap with QA Sentinel are rejected. Host SQLite must stay outside the
target. Explicit root/cwd/target components reject symlinks and Windows junctions
before resolution. Relative cwd/targets reject traversal, absolute POSIX paths,
drive-relative/drive-rooted paths, UNC/rooted paths, alternate data streams,
options and shell-like syntax. Windows relative backslashes normalize to `/`.
Canonical targets remain inside both test cwd and full root. Directory inspection
uses the accepted bounded policy (10,000 entries per selected target); linked
descendants escaping the test cwd or unavailable/oversized trees fail closed.

`target-check` dry-validates the same ExecutionConfig, CommandRequest and
CommandPolicy used by `target-test`. `target-test` calls the existing
PytestRunner → CommandRunner once, with no retry and no second subprocess path.
The runner rechecks policy, uses argv with shell=False, controlled secret-free
environment, bounded capture, finite timeout, native process-tree cleanup and
built-in JUnit XML. It retains full-root rootdir/confcutdir and scratch ownership;
the canonical test cwd is added to pytest's controlled import paths after pytest
loads, supporting backend imports even with Python `-P`. Root-only configurations
retain their existing behavior. Target pytest.ini/addopts and ambient plugins
cannot add commands through this boundary. [Accepted policy](EXECUTION.md).

## Result, persistence and trust limits

The frozen ephemeral ProvingResult is **not a workflow TestRun**. It contains no
Task/job identity, source, absolute cwd, stdout/stderr, environment or provider
response. Successful stdout/stderr and errors are never printed or stored.
CLI reports are fixed fields, UUIDs, bounded numeric facts and allowlisted safe
codes. Parser errors also omit offending values and raw diagnostics (exit 2).
Check failure exits 1. Test exits 0 only for PASS with reliable counts; FAIL,
UNKNOWN, rejected execution and missing/malformed counts exit 1. A zero pytest
exit with unreliable counts can display PASS but is not a successful proving
check. Exit interpretation and bounded JUnit counts reuse Task 6; console prose
never supplies a conclusion. Unexpected execution failure reports UNKNOWN with
TARGET_EXECUTION_FAILED; unavailable duration is represented as zero, not a
measurement of successful execution.

SQLite is opened read-only only for accepted-schema/existing-Project lookup and
closed before testing. No Project/Task, AgentInvocation, TestRun, Artifact, Event,
state change or ExecutionJob is created. There is no proving history, crash
completion record, migration or new dependency. Workflow TestExecutionService
continues its existing reservation/completion persistence independently.

Proving invokes no MutationService or model and does not authorize source writes.
The accepted runner does create and remove bounded-output scratch files in the
workspace. Trusted tests can themselves write, call the network or execute Python;
this command policy is **not an OS sandbox** or a hostile/concurrent-writer
containment guarantee. Use exclusive trusted access and an independently verified
clean baseline; never treat proving as authorization to rerun uncertain workflow
effects. It does not resolve Task reconciliation or change reliability budgets.

Demo, preview-demo and hosted-demo reject real Project target configuration and
remain synthetic/fake-only. Proving has no HTTP endpoint or UI action; session,
CSRF, Basic access, workflow jobs and reconciliation semantics are unchanged.
Normal automated coverage uses temporary prepared repositories and mocked provider
boundaries, without StayFinder, live providers or external service network.
This walkthrough is not a claim that a manual StayFinder proving run was executed.
