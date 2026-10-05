# QA Sentinel product guide

For technical Operators using implemented Tasks 1–24. Start with the
[demo walkthrough](#demo-mode); use the evidence sections as a reference.
[PRD](PRD.md) explains intent; [Features](FEATURES.md) summarizes ownership/limits.

## What is QA Sentinel?

QA Sentinel coordinates reasoning agents, deterministic tools, evidence and
workflow gates to execute and inspect software QA work. It connects a requirement
to research, a plan, implementation evidence, tests and independent review.
It records why work moved or stopped, rather than treating one model answer or
passing test as sufficient proof.

## Operations dashboard

Choose Operations to see global running/queued jobs, blocked Tasks, terminal
counts and recent failed/stopped requests. Filter by Project, Task state, Attention
only or Active only; the URL preserves the selection. Open Task links to inspect
the existing execution, reconciliation and evidence panels. Inspect runtime selects
one Project and shows this host's safe readiness separately.

Operational views summarize persisted truth and derived safety signals. They do
not control workflow progression. Job SUCCEEDED does not mean Task DONE. A DB-only
reconciliation signal can be active unfinished work; no signal does not prove CLEAR.
Use Task Detail for the full assessment before explicit continuation. Lists show
up to 50 rows and honest truncation; GET-only refresh runs every seven seconds while
visible, with manual Refresh and last-updated text. Public demo activity remains
deterministic synthetic evidence, never real AI/testing.
[Detailed meanings and limits](OBSERVABILITY.md).

## When should I use it?

Use the demo to learn evidence inspection. Use real local mode when you can
prepare a trusted workspace/test environment and inspect actual changes/results.
Use the console to investigate safe stops and compare requirement coverage with
tests. It coordinates testing rather than replacing CI, issue tracking or
production access control. It is not an unrestricted coding agent or chatbot.

## Mental model

**Agents reason. Tools act. Evidence records reality. Orchestrator controls progression.**

| Term | Meaning | Do not assume |
| --- | --- | --- |
| State | Current persisted truth: Task snapshot | A model recommendation already changed it |
| Event | Something happened or a recommendation/reservation was recorded | Every Event proves an action completed |
| Artifact | Structured evidence/output | Every stored output passed a Gate |
| Decision | Why routing/recovery was recorded | A reservation proves execution |
| Gate | Deterministic acceptance check | PASS always means passing tests or DONE |
| Invocation | Agent execution record | COMPLETED means Task success |
| Test Run | Deterministic test execution record; synthetic in demo | UNKNOWN is a product FAIL |
| Error | Classified failure evidence | Every HTTP error has a persisted Error |

Conceptual inspection chain: **Task → Invocation → Artifact → Test Run / Error /
Decision → Gate → State transition**. This is a navigation concept, not a mandatory
one-to-one sequence. References may be absent. Invocations link Artifacts/Errors
where recorded; Test Runs link implementation/report Artifacts; Decisions carry
evidence refs. Timeline Events expose persisted invocation/artifact/test-run/decision
correlation IDs. Gates link through Decisions/transitions, not a fabricated
gate-ID Event correlation field. There is no hidden reasoning transcript,
raw provider response or raw test-output viewer.
[Evidence boundary](APPLICATION.md#read-contracts-and-bounds).

## Projects

A Project is logical software identity: immutable key/ID, name, description and
timestamps. Open one from the Projects registry to inspect its owned Tasks.
Create Project stores identity, not a repository/workspace/runtime. UI creation
does not clone software or configure tests. Demo Calculator is the only
executable demo Project; other Projects remain runtime-unconfigured in all synthetic modes.
[Project isolation](PROJECTS.md).

## Tasks

A Task is one QA requirement owned by exactly one Project. On Project Detail,
enter title/requirement in Create Task and open the returned Task. Ownership cannot
move to another Project. Creation starts at CREATED without execution. Title is
a label; requirement is the work input. Neither selects roots or grants mutation
permission. Do not put credentials in either field.

## Run

Run sends one request to create a durable execution job. The backend resolves
runtime from persisted Project ownership. The execution panel shows queued/running
progress separately from Task state. You can leave or refresh the page and recover
the active request from persisted history. One host workflow runs at a time;
different Tasks may wait in the durable queue. Run/Resume are disabled while an
active job is known, while checking history or while submitting/refreshing.

Only active jobs are polled, every 1.5 seconds after the previous read settles.
Polling stops at terminal status or navigation. A completed request refreshes Task,
Timeline and already-opened evidence, without fetching unopened sections. There
is no automatic creation retry. Network interruption preserves the request and
shows recovery guidance; use **Refresh execution history** before considering
another Run. Missing jobs stop polling and prompt recovery. Recent executions
show at most ten requests, including fixed safe error codes and timestamps.

Run does not resume BLOCKED. For DONE/FAILED, **Run (terminal check)** returns
durable state under existing runtime/binding guards without new agent execution;
it is not rerun/reset. HTTP success alone is not proof of DONE.

## Resume

Resume appears for BLOCKED with stored resume_state. After resolving the blocker,
it records the transition back to that state and refreshes the view. Click Run
separately to execute. Resume does not call agents, reset budgets, reconcile
uncertain writes/calls or revive FAILED/DONE. There is no automatic reconciliation
UI/API that clears unresolved evidence.

## Workflow states

The Orchestrator owns all state changes. This table lists accepted next states,
not promises that every edge is selected by the runner. Forward progression
requires appropriate deterministic checks.

| Workflow state | Meaning / stage actor | Allowed next states | Terminal? | Expected evidence when available |
| --- | --- | --- | --- | --- |
| CREATED | Task exists; Orchestrator begins research | RESEARCHING, BLOCKED | No | Requirement/ownership, initial transition |
| RESEARCHING | Researcher gathers structured findings | PLANNING, BLOCKED | No | RESEARCH, Invocation, RESEARCH_GATE |
| PLANNING | Planner defines steps/files/criteria/strategy | IMPLEMENTING, RESEARCHING, BLOCKED | No | PLAN, Invocation, PLAN_GATE |
| IMPLEMENTING | Implementer proposes; controlled layer applies in real local mode | TESTING, PLANNING, FAILED | No | IMPLEMENTATION; real IMPLEMENTATION_PROPOSAL/applied facts; IMPLEMENTATION_GATE |
| TESTING | Deterministic Test Runner/provider supplies results | REVIEWING, ANALYZING | No | Test Run, TEST_GATE; real TEST_RESULT |
| ANALYZING | Test Analyzer classifies observed failing tests | INVESTIGATING, TESTING | No | TEST_ANALYSIS, Invocation, ANALYSIS_GATE |
| INVESTIGATING | Investigator identifies cause/action | IMPLEMENTING, RESEARCHING, BLOCKED, FAILED | No | INVESTIGATION, Invocation, INVESTIGATION_GATE; separate escalation records if reserved |
| REVIEWING | Reviewer evaluates requirement coverage independently | DONE, IMPLEMENTING, PLANNING, BLOCKED | No | REVIEW, Invocation, REVIEW_GATE |
| BLOCKED | Waits with stored resume_state | Stored nonterminal resume_state, or FAILED | No | Block/reason evidence and resume target |
| FAILED | Terminal workflow failure | None | Yes | State/terminal reason and preceding evidence |
| DONE | Terminal completion through acceptance checks | None | Yes | Accepted implementation, passing test/review evidence and transition |

Explicit same-state placeholders exist for RESEARCHING, IMPLEMENTING and
INVESTIGATING under `allow_same_state`; they are not a browser retry control.
IMPLEMENTING, TESTING and ANALYZING have **no direct BLOCKED edge**. A safe stop
there can preserve the active state. [Exact graph](STATE_MACHINE.md).

Normal completed path:

```text
CREATED → RESEARCHING → PLANNING → IMPLEMENTING → TESTING → REVIEWING → DONE
```

The product-failure repair path adds
`TESTING → ANALYZING → INVESTIGATING → IMPLEMENTING → TESTING`.
Infrastructure failure does not automatically enter product-defect analysis.

## Agent roles and deterministic actors

Real local mode uses OpenAIModelAdapter/RealAgentRuntime for six reasoning roles,
with validated structured output and no provider-native tools. Demo uses fixed
fake outputs. Test Runner and Orchestrator are deterministic actors, not LLM roles.

| Role / actor | Responsibility and permitted action | Must not do | Evidence / demo behavior |
| --- | --- | --- | --- |
| Researcher (RESEARCHER) | Findings, dependencies, risks/unknowns; request bounded read-only repository evidence through controlled application code | Write, execute commands, choose roots or approve progression | RESEARCH and optional REPOSITORY_EVIDENCE; synthetic findings in demo |
| Planner (PLANNER) | Steps, authorized files, criteria/test strategy; request bounded reads | Apply changes, run tests or grant unrestricted access | PLAN and optional REPOSITORY_EVIDENCE; synthetic plan in demo |
| Implementer (IMPLEMENTER) | Return plan-authorized structured CREATE/MODIFY proposal from supplied snapshots | Directly read/write, run shell/Git/tests, DELETE or bypass hashes | Real IMPLEMENTATION_PROPOSAL then canonical IMPLEMENTATION after apply; synthetic report without writes in demo |
| Test Runner | Execute policy-approved pytest in trusted real local mode | Investigate root cause, approve work or change state | Test Run and real TEST_RESULT; synthetic Test Run/environment fake in demo |
| Test Analyzer (TEST_ANALYZER) | Classify observed failing tests from supplied evidence | Override test facts, perform root-cause investigation or execute repair | TEST_ANALYSIS; fake scenario output if its stage is reached |
| Investigator (INVESTIGATOR) | Report cause/uncertainty and CODE_FIX, TEST_FIX, MORE_RESEARCH or HUMAN_ACTION | Execute fixes or choose hidden retries/fallbacks | INVESTIGATION; escalation gets a separate Invocation/Artifact; fake output if reached in demo |
| Reviewer (REVIEWER) | Independently evaluate criteria against supplied implementation/tests | Self-approve implementation, mutate or directly set DONE | REVIEW recommendation/coverage; synthetic review in demo |
| Orchestrator | Select routes, enforce gates/recovery limits, atomically record transitions | Accept unlisted edges or model-prose policy overrides | State transitions, Events, Decisions and Gates; deterministic in both modes |

The default hosted demo is the happy path, so not every failure branch is reached.
Real diagnosis needs sufficient supplied evidence; references/counts do not
automatically open logs. [Runtime](RUNTIME.md), [Models](MODELS.md),
[controlled reads](REPOSITORY_TOOLS.md).

## Overview

Overview shows requirement, current state, Project/Task IDs, timestamps, resume
target, current Invocation ID, attempt/cycle counters and terminal reason. Start
here for the snapshot. Counters measure different activities, not quality.
A retained active state can reflect a safe stop, not continuing background work.

## Timeline

Timeline shows persisted Events in API order with time, actor, compact details
and correlation refs. Locate starts/results and actual STATE_TRANSITIONED Events.
It is the Event ledger, not merged evidence from every table. Retry/escalation/block
recommendation Events do not prove calls/transitions completed. Timestamp ties
do not provide universal causal order. Respect truncation notices.

## Artifacts

Artifacts shows structured evidence/output with type, producer, schema version,
Invocation link and supersession metadata. Expand JSON for findings, criteria,
applied facts or coverage. Types: RESEARCH, PLAN, IMPLEMENTATION,
IMPLEMENTATION_PROPOSAL, REPOSITORY_EVIDENCE, TEST_RESULT, TEST_ANALYSIS,
INVESTIGATION and REVIEW. A proposal is not applied-change proof; valid stored
output is not automatically accepted. Supported history is append-only.

## Invocations

Invocations shows role, model/reasoning effort, attempt, status, times and linked
Error ID. STARTED, COMPLETED, BLOCKED and FAILED describe the Invocation, not
the Task. Effort is configuration metadata, not hidden reasoning content.
STARTED can be unresolved, not currently executing or safe to repeat. Real
Implementer completion additionally requires deterministic application success.

## Test Runs

Test Runs separates execution_status (COMPLETED, INCOMPLETE, FAILED) from outcome
(PASS, FAIL, UNKNOWN), with counts, environment and implementation/report refs.
COMPLETED + FAIL means tests ran and observed failures; FAILED/INCOMPLETE + UNKNOWN
does not conclude a product defect. Real counts use bounded built-in JUnit
reporting; unreliable counts are disclosed in structured report evidence. Demo
results/counts are synthetic. PASS alone is neither coverage nor DONE. There is
no raw stdout/stderr viewer.

## Errors

Errors shows persisted classified failures: type, severity, owner, fixed message,
flags, approved source fields and refs. Read them with Invocations, Test Runs and
Decisions. Retryable flags are not retry instructions. HTTP validation/configuration
feedback need not create a domain Error; an empty section does not prove success.

## Decisions

Decisions shows type, source, reason codes/details and evidence refs. Read why
routing/recovery was evaluated. RETRY or ESCALATE_MODEL may be denied or only
reserve work; verify subsequent lifecycle/transition evidence. Approved concise
reasons are not hidden reasoning.

## Gates

Gates shows deterministic result, individual checks/reasons and blocking reasons.
Names: RESEARCH_GATE, PLAN_GATE, IMPLEMENTATION_GATE, TEST_GATE, ANALYSIS_GATE,
INVESTIGATION_GATE and REVIEW_GATE. PASS means stage sufficiency: ANALYSIS_GATE
may PASS for sufficient analysis of failing tests. Forward research/plan/implementation/
test/review edges require their named PASS gate. Reviewer APPROVE with incomplete
coverage cannot become DONE. [Rules](STATE_MACHINE.md#gate-rules).

## Demo mode

Local `--demo` and protected preview use the same fixed deterministic synthetic
calculator scenario. Neither calls live models, writes source, runs real pytest,
requires an API key or needs external workflow network. Installation/build and
optional API-doc assets are separate. Preview rejects OPENAI_API_KEY, shows
**DEMO PREVIEW · Synthetic**, needs privately supplied Basic credentials and
may lose SQLite state on restart/redeploy. This gate is not product auth.
Use the current HTTPS URL from the owner; do not enter secrets.

### Canonical walkthrough

1. Authenticate to preview with privately supplied credentials. For local demo,
   follow [Hosting](HOSTING.md#first-run-offline-demo) and open http://127.0.0.1:8000.
2. Open **Demo Calculator** (key `demo-calculator`) from Projects. Another Project
   does not automatically receive a runnable demo.
3. Create Task titled **Division support** with requirement
   **Add division support and reject division by zero.** Open the Task.
4. Click Run once, wait for completion and refreshed **DONE**.
5. In Overview verify requirement, Project identity and completed state.
6. In Timeline follow normal state transitions and lifecycle Events.
7. In Artifacts inspect RESEARCH, PLAN criteria, IMPLEMENTATION and REVIEW;
   these report the synthetic scenario, not actual repository changes.
8. In Invocations inspect fake role/model provenance, attempts and completion.
9. In Test Runs inspect synthetic COMPLETED/PASS and fake environment.
10. In Decisions read transition reasons and refs.
11. In Gates inspect checks supporting progression to DONE.

A different requirement still runs this fixed scenario. The hosted demo has no
real implementation proposal, repository reads or real pytest report.
[Preview access/deployment](DEPLOYMENT.md).

## Real local mode

Real local mode is **trusted local workspace execution**, remaining loopback-only.
It uses OpenAIModelAdapter/RealAgentRuntime, controlled Researcher/Planner reads,
plan-authorized mutation and real pytest. A matching ProjectWorkspaceBinding
and local OPENAI_API_KEY are required. Never put keys in chat, requirements,
JSON or source.

Create logical Project identity first in the same persistent DB, prepare a separate
trusted target/tests, stop the previous host, and explicitly configure that
Project's key/root/test targets. [Hosting](HOSTING.md#real-local-mode) owns exact
setup; the UI does not provision workspaces. Deterministic code validates complete
full-file UTF-8 CREATE/MODIFY sets and exact hashes before applying. Ordinary
partial application failure rolls back; stale source or uncertain write/persistence
completion requires reconciliation. DELETE, arbitrary shell, Git rollback and
model-owned file tools are unsupported. [Mutation](MUTATION.md), [Execution](EXECUTION.md).

## Controlled repair demonstration

After clean target proving, an operator can prepare an intentionally defective
external scenario and use normal Project-owned Task Run. Planner implementation
steps must describe code work or source-based review; executable verification
belongs to test_strategy / TESTING. PlanGate rejects declared TEST_EXECUTION work
before Implementer, while ImplementationGate still requires every actual step
COMPLETED with no extra/duplicate results or requires_replan bypass. A typed kind
is not semantic proof of prose, and a blocked immutable Plan is not silently edited.
[Operator runbook and limitation](CONTROLLED_REPAIR_DEMO.md). No new public execution
or UI capability is introduced; a live StayFinder rerun is still required.

## Real Project onboarding

Before the first controlled repair on an external trusted target, use the local
CLI's target-check and explicit target-test proving commands. They require an
existing Project, support a backend test cwd under the full repository root,
and need no model key. Their ephemeral result does not appear in Task Test Runs,
does not run agents or change workflow state, and authorizes no mutation.
[Windows operator walkthrough and trust limits](REAL_TARGETS.md).

Creating a Project stores logical identity; it does not provision a workspace.
In a local demo session using your intended database, create/select the Project
and stop the host. Run `qa-sentinel local init` with its key, the database and
frontend build, explicit absolute workspace and prepared pytest targets. The
generated JSON holds only nonsecret host configuration, never workspace data in
Project persistence. [Canonical commands](HOSTING.md#real-project-onboarding).

Use `qa-sentinel local validate --config ...` before serving real mode. It checks
identity, boundaries, selected targets and existing database/build read-only;
no model/provider call, pytest/subprocess or source mutation occurs. Missing
OPENAI_API_KEY produces NOT READY. Supply it securely through the local shell
environment and revalidate; PRESENT checks only a nonblank value, not the provider.
Start `serve --config ...` and open the Project at http://127.0.0.1:8000.

**Runtime readiness** on Project Detail shows configured/unconfigured status,
presence-only model key and test configuration. Refresh runtime is explicit;
the status is a snapshot, not permission or a success guarantee. An unconfigured
Project needs host configuration and restart, not another Project row. Create a
Task and Run only after checking the intended trusted workspace. Run retains
backend checks and all existing gates/reconciliation rules.

Local demo and public preview mark configured Demo Calculator as **Synthetic demo**;
no live AI, source mutation or real pytest is introduced. Other Projects remain
unconfigured. Public preview is not a real-workspace onboarding host.

## Execution requests and workflow truth

Task 20 adds backend async requests; Task 21 uses them for browser Run, with
active-job recovery, bounded polling and recent history. Resume stays separate.
API callers and browser Run POST
`/api/v1/tasks/{task_id}/executions` for a 202 job record, then inspect that record
and the Task through GET. One active job per Task and one active workflow globally
are allowed in the single host process. Different Tasks can wait durably.

**TaskState describes QA truth. ExecutionJobStatus describes one request.** QUEUED
waits; RUNNING means a durable claim; SUCCEEDED means application Run returned
normally, not QA reached DONE. STOPPED/FAILED still need Task/evidence inspection.
Terminal Tasks reject async requests but retain the synchronous terminal check.
Resume restores BLOCKED state without execution or reconciliation.

Restart stops uncertain RUNNING jobs with EXECUTION_INTERRUPTED and never silently
reruns them. QUEUED jobs can recover in FIFO order, including real local work.
Do not assume exactly-once execution; reconcile unresolved core evidence and
workspace writes before explicitly continuing. Demo/preview stays synthetic only.
[Contract and recovery limits](EXECUTION_JOBS.md).

## Reading a completed Task

Confirm Overview is DONE, then trace PLAN criteria to canonical IMPLEMENTATION,
latest conclusive Test Run, REVIEW coverage and REVIEW_GATE. Confirm actual
progression in Timeline/Decisions. Newer unaccepted Artifacts do not replace
accepted output simply because they exist. A truncated collection omits records;
the UI has no automatic reference resolver. DONE reflects accepted supplied
evidence within current limits, not exhaustive software-correctness proof. Demo
completion reflects synthetic evidence only.

## Reading a failed/blocked Task

Read state/terminal reason/resume target, then Errors, Invocations, Test Runs and
Timeline. Use Decisions/Gates to distinguish product failure, insufficient
evidence, policy rejection, exhausted budgets and uncertain execution. FAILED is
terminal; BLOCKED resumes only to its stored state. A safe error may instead
preserve IMPLEMENTING, TESTING or ANALYZING.

Resolve the blocker with the trusted host owner before Resume, then Run separately.
For unresolved STARTED calls/tests/writes, inspect durable reservations and actual
workspace facts through the documented recovery process. Resume is not reconciliation;
repeated Run is not a safe repair mechanism. Recovery / Reconciliation now shows
derived safety guidance with an explicit Refresh; it offers no automatic resolution
or unsafe override. [Recovery playbooks](RECONCILIATION.md#operator-playbooks).

## Common mistakes

- Assuming Project creation provisions a workspace/runtime.
- Treating synthetic demo results as live verification of arbitrary input.
- Assuming Run on BLOCKED resumes, or Resume also executes.
- Equating Invocation COMPLETED, Gate PASS or Reviewer APPROVE with DONE.
- Treating UNKNOWN test outcome as product FAIL.
- Repeating Run after uncertain writes/calls instead of reconciling.
- Assuming a truncated evidence collection is the full history.
- Entering secrets into requirements/evidence/shared preview.

## Current limitations

SQLite, durable async browser Run, one host process/worker and one admitted workflow at a
time. Views are bounded prefixes, evidence loads on section open and Refresh is
explicit, apart from active job polling and refresh on completion. Async requests
use one durable local queue; there is no cancellation, job retry, search,
distributed execution or streaming. Preview
state is ephemeral and Basic is a temporary shared gate, not product users/RBAC.
Local execution trusts prepared source/tests and local access; it is not an OS
sandbox or cloud workspace. No remote clone, arbitrary shell, human approval UI,
source editor or hidden reasoning viewer. [PRD](PRD.md#risks-and-limitations).

## Crash recovery guidance

Task Detail's Recovery / Reconciliation panel is separate from Task state and
ExecutionJob status. Clear means no unresolved evidence was found; Recoverable
means existing durable reuse/queue rules apply. Manual action required and
Inconsistent stop Run/Resume. Refresh rereads facts and does not clear uncertainty.
For real local work, the owner can use `local reconcile --config ... --task <UUID>`
without an API key, model call, pytest process or source write.

An interrupted job alone does not prove safe continuation: inspect pending
Invocation/provider, mutation, TestRun and workspace evidence independently.
Do not replay lost provider responses, rerun uncertain tests, reapply/restore
uncertain mutations or fabricate completion. Inspection does not itself resolve
blocking evidence, and no exactly-once guarantee is provided. Preview remains
deterministic synthetic demo; real mode remains trusted local workspace execution.
[Detailed assessment and operator playbooks](RECONCILIATION.md).

## Persistent hosted demo

The owner may choose the separate paid hosted-demo profile. Open the privately
supplied HTTPS URL and sign in on the minimal login page. The console shows
**HOSTED DEMO · Synthetic** and a **Sign out** control. Follow the same Demo
Calculator walkthrough; requirement text still selects no real model, workspace
or tests. Arbitrary Projects can be inspected but have no configured runtime.

The persistent disk retains Projects, Tasks, evidence and execution jobs across
same-service restarts. It does not enable real execution, repair uncertain work
or turn SUCCEEDED into DONE. Keep using Task state, evidence and Recovery /
Reconciliation separately. There is one host workflow at a time and no
exactly-once or zero-downtime guarantee.

Access lasts at most eight hours. Sign out or expiry returns to login, without
canceling/changing jobs or Tasks. Sign in again, inspect refreshed execution
history and reconciliation, then choose any next action explicitly. Failed
actions are never replayed automatically. Credentials and session cookies are
not shown in the console or stored in browser localStorage. This is a
single-operator portfolio access boundary, not production multi-user identity/RBAC.

The existing free **DEMO PREVIEW · Synthetic** mode remains ephemeral with its
temporary Basic gate. Local demo still has no auth; real local remains trusted
loopback workspace execution. The owner must explicitly provision the hosted
profile; existing preview records are not automatically transferred.
[Deployment choices](DEPLOYMENT.md), [access/expiry limits](HOSTED_ACCESS.md).
