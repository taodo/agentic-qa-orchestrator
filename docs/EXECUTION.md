# Deterministic execution — Bootstrap Task 6

The execution layer validates approved commands, runs local pytest, and records facts.
It never transitions workflow state, classifies product defects, approves work, or
marks a task DONE. No new dependencies are introduced: subprocess, threads, native
process cleanup, temporary files, and XML parsing use the Python standard library;
counts come from pytest's built-in JUnit XML reporting.

## Architecture and trust boundary

- command_policy.py: immutable CommandRequest/ExecutionConfig and structured policy decisions.
- command_runner.py: policy-gated argv execution, bounded capture, and report counts.
- process_tree.py: POSIX process-group / Windows Job Object cleanup without shell wrappers.
- pytest_runner.py: centralized exit interpretation and existing TestRun conversion.
- service.py: start/completion persistence and PytestTestResultProvider.
- base.py: provider protocol shared by real and fake testing.

Trusted application configuration selects workspace root, Python executable, dependency
import paths, resource limits, and permitted custom environment names. These are not
agent-controlled CommandRequest fields. Requests can only select the logical executable
"python", args starting with ("-m", "pytest"), cwd, finite timeout, and approved environment
additions. Rejection returns CommandPolicyDecision and never reaches subprocess.

CommandPolicy restricts the command surface. It is **not an OS sandbox**: pytest tests
and in-workspace conftest.py execute Python and must come from the prepared approved
project. They can perform arbitrary Python operations. Hostile test-code isolation,
filesystem/network confinement, and protection against concurrent filesystem replacement
are outside Task 6; no sandbox framework or container is added.

## Executable, argument, and path policy

Only the configured Python executable running pytest is supported. No shells, -c code,
pip, arbitrary modules, generic scripts, network utilities, or package managers are
accepted. Approved public flags are -q, -s, --tb=short, --disable-warnings. -s is useful
for controlled direct-output testing and remains bounded by the same capture limits.
Targets may be existing directories, .py test files, or file::node IDs.

Options for plugins, external config, output paths, distributed execution, and arbitrary
pytest configuration are rejected. Argument count is bounded to 64, each token to 2048
characters. Shell-like chaining/metacharacters (including pipes, redirects, ampersands,
semicolons, backticks, command substitution, and control characters) are rejected. These
conservative restrictions also reject unusual legitimate node IDs containing such text.
Every process receives an argv list with shell=False and stdin=DEVNULL.

Cwd resolves canonically, must exist, be a directory, and remain within workspace_root.
Relative cwd resolves from that root; targets resolve from cwd. Absolute/relative escapes
and external symlink targets are rejected. Node-ID file portions use the same checks.
Directory targets receive bounded canonical inspection (default 10,000 entries), including
reachable linked directories, to detect external discovery paths. Uninspectable targets
or exhausted inspection bounds are rejected rather than silently weakening policy.
No explicit target defaults to cwd, subject to the same inspection.

The runner supplies an empty temporary pytest.ini, explicit rootdir/confcutdir, workspace
temporary basetemp, JUnit destination, and disabled cache provider. It disables inherited
addopts and automatic third-party plugin discovery. Python -P prevents cwd from shadowing
the pytest entry module; -s/PYTHONNOUSERSITE disable the user site. Configured dependency
paths are explicit. After pytest itself loads, the approved workspace is added through
pytest's controlled pythonpath option so ordinary sample-project imports work, including
paths with spaces. Quoting that ini value does not invoke a shell.

Task 25 also adds the validated in-root cwd to those controlled import paths for
backend layouts. ExecutionConfig's optional pytest_target_root tightens target
containment to that subdirectory; its default remains the full workspace. It does
not change rootdir/confcutdir, root ownership or workflow TestExecutionService.
CLI target-check dry-validates this policy; target-test uses the same runner once
and projects an ephemeral result, without TestRun conversion/persistence or any
workflow routing. [Proving semantics](REAL_TARGETS.md#result-persistence-and-trust-limits).

## Environment and limits

The full parent environment is never inherited. Child environment contains a baseline
PATH, Windows SYSTEMROOT/WINDIR when present, workspace-local TMP/TEMP/TMPDIR,
PYTHONNOUSERSITE, PYTHONDONTWRITEBYTECODE, PYTHONIOENCODING=utf-8, and
PYTEST_DISABLE_PLUGIN_AUTOLOAD. PYTHONPATH exists only for explicitly configured
dependency directories. No parent tokens, API keys, SSH/cloud variables, pytest options,
or unrelated application environment are automatically forwarded.

Custom environment names require an explicit configuration allowlist. Names containing
KEY, TOKEN, SECRET, PASSWORD, PASSWD, CREDENTIAL are rejected, as are reserved Python,
pytest, loader, SSH/Git, path, home, and temporary-directory overrides. Values are bounded
and cannot contain NUL. This defensive name filter is intentionally conservative, not
perfect secret detection. Values are never persisted in execution audit evidence.

Every request has a finite positive timeout, default/max 120 seconds. The configured
maximum may be changed; a request exceeding it is rejected. Timeout applies to process
waiting. Python/OS process creation itself is not a general hard-real-time operation.

Stdout and stderr are drained concurrently into fixed prefix buffers, default 256 KiB
per stream; remaining bytes are discarded while the process runs. This prevents both
pipe deadlocks and unbounded in-memory communicate() output. Captures decode UTF-8
without partial invalid byte sequences; truncation flags identify discarded output.
No interactive stdin or os.system is used.

On timeout the process tree is terminated and the parent reaped. Cleanup also stops
descendants left after normal parent exit. POSIX uses a new session/process group;
Windows immediately assigns the process to a kill-on-close Job Object via ctypes.
Windows job assignment failure fails execution rather than continuing without cleanup.
Native groups/jobs handle ordinary descendants and are tested with a real child process.
They are not hostile-code containment: intentional process-group escape or the brief
Windows launch-to-job-assignment race cannot be eliminated by this small stdlib layer.

## Pytest interpretation and counts

| Command / exit | TestRun execution_status | outcome | Infrastructure error |
| --- | --- | --- | --- |
| Completed / 0 | COMPLETED | PASS | None |
| Completed / 1 | COMPLETED | FAIL | None |
| Completed / 2 | FAILED | UNKNOWN | ENVIRONMENT_ERROR / PYTEST_INTERRUPTED |
| Completed / 3 | FAILED | UNKNOWN | TOOL_ERROR / PYTEST_INTERNAL_ERROR |
| Completed / 4 | FAILED | UNKNOWN | TOOL_ERROR / PYTEST_USAGE_ERROR |
| Completed / 5 | FAILED | UNKNOWN | TOOL_ERROR / NO_TESTS_COLLECTED |
| Other exit | FAILED | UNKNOWN | TOOL_ERROR / PYTEST_UNEXPECTED_EXIT |
| Timeout | INCOMPLETE | UNKNOWN | ENVIRONMENT_ERROR / EXECUTION_TIMEOUT |
| Start/capture failure | FAILED | UNKNOWN | ENVIRONMENT_ERROR / PROCESS_START_FAILED or OUTPUT_CAPTURE_FAILED |
| Policy rejection | FAILED | UNKNOWN | POLICY_VIOLATION / structured rejection code |

Exit code alone supplies the normal PASS/FAIL conclusion, never stdout prose. Exit 1
does not create an infrastructure ErrorRecord or schedule a testing retry. Classification
of failing product/test behavior remains the Test Analyzer's responsibility.

Pytest's built-in JUnit XML supplies pass/fail/skip counts via standard-library parsing.
The runner disables JUnit console logging and reads at most 1 MiB by default, rejects
DTD/entities, non-UTF-8/malformed reports, and redirected report paths. Absent, invalid,
or oversized reports yield conservative zero counts with counts.reliable=False; no
console parsing guesses values. Timeout/abnormal-exit TestRun counts remain zero.
The temporary XML file itself is not a disk-quota sandbox; oversized reports are not
parsed/persisted and normal temporary files are removed before returning execution.

## Persistence, attempts, and evidence

TestExecutionService checks task/implementation ownership and TESTING state. It reserves
a run UUID and commits TEST_EXECUTION_STARTED before calling subprocess. This event
marks a logical attempt, not proof of OS process creation (a policy rejection can follow).
Attempt numbering comes from durable execution events/TestRun history, including legacy
or fake runs, and survives service recreation.

After subprocess returns, one transaction inserts a bounded TEST_RESULT Artifact,
TestRun, optional ErrorRecord, and one TEST_EXECUTION_COMPLETED, TEST_EXECUTION_FAILED,
or TEST_EXECUTION_TIMED_OUT event. TestRun.environment="local-pytest"; task and implementation
links are preserved and report_artifact_id identifies the evidence. Events correlate to
the task/run and record exit, duration, statuses, outcome, attempt, and truncation flags.
Artifacts preserve structured counts and reason/disposition metadata. No new ArtifactType
or database schema is needed.

Raw stdout/stderr, XML, environment values, exception messages, and arbitrary request
strings are not stored in the database. Bounded stdout/stderr are returned transiently
to the execution caller. This reduces intentional secret persistence without claiming
to identify every secret that trusted test code might print.

No transaction stays open during subprocess execution. Completion failure rolls back
report, TestRun, error, and completion event together, leaving the start reservation.
A new service refuses unresolved starts with TestExecutionPendingError; it does not
silently execute again or claim persisted success. Full crash reconciliation/exactly-once
execution and concurrent reservations remain deferred.

## Workflow integration and Task 7 boundary

WorkflowRunner accepts either fake or real providers through the same protocol. Already
persisted real TestRuns are verified, not inserted twice. Latest attempts are selected
from durable events rather than UUID order. Multiple infrastructure attempts may precede
a conclusive TestRun for one implementation artifact; analysis/review receive that latest
evidence.

COMPLETED/PASS routes through TestGate to REVIEWING; COMPLETED/FAIL routes to ANALYZING.
Timeout is explicitly TRANSIENT and can consume TEST_EXECUTION retries while staying
TESTING. Startup/internal/interrupted/no-tests failures are STRUCTURAL; usage errors
are CORRECTABLE with no implicit changed input; policy violations are TERMINAL. Durable
retry budgets never reset, and product failure never triggers blind execution retry.

The graph still has no TESTING -> BLOCKED edge. Exhausted/denied infrastructure recovery
records error and block decision/event evidence, raises RunnerStoppedError, and preserves
TESTING. No illegal edge or product-analysis route is invented. Pending execution likewise
requires caller reconciliation. Other fake-agent and workflow behavior remains available.

Real integration tests prepare temporary calculator source/tests independently of agents:
add, divide, and zero-divisor rejection, with passing/failing/slow/noisy variants. Tests
verify real subprocess outcomes, JUnit counts, environment isolation, timeout parent/child
cleanup, durable retries, database reopen, rollback, and real provider workflow routes.
Symlink testing skips only when the OS does not grant the required creation privilege.

No LLM/provider calls, real agent source edits, arbitrary commands, shell wrappers,
reporting plugins, new dependencies, remote runners, containers, queues, API/CLI/UI,
or Task 7 features are introduced. Task 7 is Real Model Adapter & First LLM Agents.

## Task 22 reservation assessment

TEST_EXECUTION_STARTED is a logical reservation, not proof of process start or
completion. The shared application assessment matches its UUID to a same-task
TestRun and implementation reference; a valid durable run need not have a
completion Event to satisfy the reservation. Missing or inconsistent evidence
blocks new Run/Resume/enqueue before pytest. Assessment executes no subprocess,
pytest discovery or source mutation and never fabricates TestRun or clears a start.
[Private inspection playbook](RECONCILIATION.md#operator-playbooks).
