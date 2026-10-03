# Crash recovery assessment — Task 22

Reconciliation assessment is **derived safety guidance**, not workflow state.
TaskState and durable QA evidence remain authoritative. The assessment never
guesses external side effects, proves exactly-once execution, clears STARTED,
fabricates completion or resolves a reservation. There is no acknowledgment,
repair, retry-anyway or automatic resolution command.

## Read contract

`assess_task_reconciliation(task_id, project_id=None)` returns a frozen,
detached ReconciliationAssessmentView: task_id, status, safe_to_run,
safe_to_resume, issues. Each issue contains stable kind/severity, a fixed bounded
summary/action and at most eight UUID evidence references. The response has at
most 100 issues; overflow adds a blocking EVIDENCE_INCONSISTENT issue rather
than declaring safety. No paths, source, provider payload, raw exception,
credential, stdout/stderr or hidden reasoning is projected.

| Status | Meaning |
| --- | --- |
| CLEAR | No unresolved crash evidence found in the checked durable snapshot |
| RECOVERABLE | Existing durable reuse/queue rules apply, with no blocking issue |
| MANUAL_ACTION_REQUIRED | External outcome or workspace safety cannot be proven |
| INCONSISTENT | Evidence linkage, lifecycle or bounded report is inconsistent |

INFO is guidance; BLOCKING prevents continuation. Both unsafe statuses have
false safety flags. A clean assessment permits existing Run semantics, including
the synchronous terminal check and BLOCKED no-op. safe_to_resume additionally
requires BLOCKED with an engine-valid stored nonterminal resume target. These
flags do not authorize workflow edges, gates, retries, queue creation, host
admission or provider access. Backend enforcement remains authoritative.

## Deterministic inspection

The application reads Task, all task-scoped Invocations, Artifacts, Events,
TestRuns and Errors in one short consistent database snapshot. Recent operational
jobs use the accepted newest-201-row query (limit 200 plus one); they contribute
informational interruption/queue guidance, never proof of core completion.
No timestamp or random UUID order proves causality. Provider turns are matched by
invocation UUID and explicit turn_index; tests by reserved TestRun UUID and
implementation linkage. Canonical outputs require the matching completed role,
producer identity, unique output and valid existing Pydantic contract.

The transaction closes before trusted local verification. ProjectWorkspaceGuard
shares its anchor/legacy verification with the assessment but the assessment
never uses its anchor-adoption write path. Real bundles revalidate binding and
service roots. Supplied-context/fake bundles check identity metadata without
physical filesystem inspection. Demo/preview have no reader or mutation service.

Mutation reservations need durable canonical completion/applied evidence or a
durable failed outcome with a safe rollback result. MUTATION_RECONCILIATION_REQUIRED
and failed rollback always block. Proposal text alone proves no applied effect.
MutationService.verify_applied checks explicit recorded files using the existing
path/type/link/UTF-8/size/SHA-256 boundary. The newest completed Implementer attempt
supersedes older facts for the same path; untouched recorded paths are still
verified. This avoids testing obsolete hashes from an accepted repair. No broad
scan, source snapshot, apply, restoration, model call, subprocess or Git operation
occurs. Bounded hash reads do not provide isolation against concurrent writers.

All unresolved STARTED invocations block, including historical/noncurrent ones.
A STARTED invocation with a canonical artifact is inconsistent rather than
silently completed. Completed canonical outputs awaiting routing may be
RECOVERABLE under existing runner reuse; the assessment executes no routing.
Reasoning-only real roles use STARTED as the call reservation when no more precise
durable turn/proposal evidence exists; an uncertain response may have been lost.
Reserved provider turns without a durable outcome block. Duplicate/missing turn
linkage is inconsistent. A durable TestRun with valid implementation/report
linkage satisfies its start reservation even if the completion Event is absent.
Unmatched starts cannot trigger pytest replay.

## Application, jobs and HTTP

Synchronous run_task, separate synchronous resume_task and request_task_execution
consult the same assessment before core work or queue insertion. Unsafe attempts
raise TASK_RECONCILIATION_REQUIRED (409) without changing Task/evidence or creating
a new job. Existing active-job/admission checks remain, so a duplicate active
request still recovers TASK_EXECUTION_ALREADY_ACTIVE. No database transaction
spans model/tool/test/mutation work or assessment filesystem verification.

`GET /api/v1/tasks/{task_id}/reconciliation` returns the safe typed read model.
Unknown Tasks return the accepted TASK_NOT_FOUND (404); unconfigured/mismatched
trusted resolvers retain their existing safe errors. Ordinary evidence reads
remain available without an execution bundle. No HTTP resolution endpoint exists.

Startup still changes stale RUNNING jobs to STOPPED/EXECUTION_INTERRUPTED before
accepting work. That operational stop is informational and does not resolve
pending core evidence. QUEUED requests can be claimed deterministically; the
worker's application Run checks reconciliation again before any core effects.
If core evidence is unsafe, the existing worker records FAILED/EXECUTION_FAILED
for the rejected request, without retries or Task-state changes. Job SUCCEEDED
never means Task DONE. [Execution jobs](EXECUTION_JOBS.md).

## Local CLI

```shell
qa-sentinel local reconcile --config qa-sentinel.local.json --task <UUID>
```

Use an existing accepted-schema database (0003), existing Project identity and
explicit trusted local configuration. SQLite opens with mode=ro and explicit
read transactions. No migration, database creation, Project creation, model
adapter, API-key check, test runner, worker, target discovery, source snapshot
or source write is performed. Only existing binding metadata and recorded applied
files may be inspected. The config file remains host-owned, separate from Project.

Output contains fixed status, safety flags, guidance and UUID references.
Exit 0 requires CLEAR/RECOVERABLE and a safe continuation flag; unsafe/unavailable
assessment exits 1; argparse usage errors exit 2. Unexpected failures print only
HOST_RECONCILIATION_FAILED, never exception text. Stop the real host and use
exclusive trusted access for diagnosis; an assessment of active work can show
currently pending reservations without proving a crash occurred.

## Operator playbooks

| Case | Inspect privately | Safe next step |
| --- | --- | --- |
| AGENT_INVOCATION_PENDING / PROVIDER_CALL_UNCERTAIN | Referenced Invocation and durable turn/output linkage; provider-side outcome if a real call may have occurred | Preserve reservations. Stop automatic continuation. Do not replay, clear STARTED, or invent a response; request a separately reviewed resolution if proof is unavailable |
| IMPLEMENTATION_MUTATION_UNCERTAIN | Reserved proposal, source manifest, applied/rollback records and explicit authorized target files | Preserve database and workspace evidence. Do not reapply or restore from proposal text. Lost in-memory backups do not provide crash restoration |
| TEST_EXECUTION_PENDING | Reserved run UUID, implementation reference, trusted process/workspace outcome | Preserve reservation; do not rerun uncertain pytest or fabricate TestRun. A missing result requires private inspection |
| WORKSPACE_DRIFT | Host binding, service roots, durable identity anchor and explicit applied hashes | Check the intended trusted workspace/configuration. Do not repoint a Task to another workspace or automatically overwrite external edits |
| EXECUTION_JOB_INTERRUPTED | Terminal operational job plus independent core assessment and Task state | If CLEAR/RECOVERABLE, explicitly use existing Run/Resume semantics; otherwise follow blocking core guidance. Do not rerun the interrupted job itself |
| EVIDENCE_INCONSISTENT | Referenced immutable records, ownership, lifecycle and schema linkage | Stop continuation and obtain a separately reviewed repair plan. No client override or generic database editing procedure is provided |

Human inspection alone does not clear a blocking assessment. Refresh only rereads
evidence; this Task supplies no generic mechanism to repair uncertain workflow
truth. Keep the stop visible until safety can be established through accepted
evidence/configuration, or a separately reviewed resolution is available.

## Browser and hosting boundaries

Task Detail shows a compact Recovery / Reconciliation panel with the four statuses,
fixed kind-based guidance and **Refresh reconciliation**. Reads are no-store.
Unknown/failed assessment disables continuation until explicit successful refresh;
loaded safety flags guard Run/Resume, and the backend checks again. Stale responses
after navigation/unmount are discarded. Job terminal and synchronous-action refresh
also reread assessment; lazy evidence remains unopened until selected. No polling,
wizard, unsafe override, browser storage or resolution POST is added here.

Preview is deterministic synthetic fake-only, protected by the unchanged Basic
gate; only exact GET /health is public. Real local mode remains loopback-only
trusted workspace execution with exclusive access, existing gates/budgets and
controlled deterministic mutation/test policies. No dependency or migration is
added. Tests deny live provider/network calls and prove that assessment and blocked
continuation perform no provider, subprocess, source mutation or evidence writes.
