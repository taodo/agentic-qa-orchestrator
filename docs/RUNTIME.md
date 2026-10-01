# Fake-agent vertical slice — Bootstrap Task 5

QA Sentinel coordinates one persisted task end to end with scenario-configured fake
outputs. Agents receive no database/session handle or mutable Task. WorkflowRunner
selects routes; WorkflowEngine validates and atomically records every state change
with gate, decision, transition, and event evidence.

## Runtime boundary and actors

`agents/base.py` defines AgentRuntime.run(agent_name, context), six small frozen
agent context models, the existing output union, and explicit mappings. `agents/fake.py`
implements the deterministic runtime. `execution/fake.py` supplies test evidence
separately; it is neither an LLM agent nor a command runner.

| State | Actor | Output |
| --- | --- | --- |
| CREATED | WorkflowEngine | Transition to RESEARCHING |
| RESEARCHING | Researcher | ResearchOutput / RESEARCH artifact |
| PLANNING | Planner | PlannerOutput / PLAN artifact |
| IMPLEMENTING | Implementer | ImplementationOutput / IMPLEMENTATION artifact |
| TESTING | Fake test-result provider | TestRun |
| ANALYZING | Test Analyzer | TestAnalysisOutput / TEST_ANALYSIS artifact |
| INVESTIGATING | Investigator | InvestigationOutput / INVESTIGATION artifact |
| REVIEWING | Reviewer | ReviewOutput / REVIEW artifact |
| BLOCKED, DONE, FAILED | None | Return without execution |

Outputs are revalidated at the runtime boundary. Raw dictionaries cannot escape as
successful agent outputs. There are no additional agent roles.

## Scenarios, sequencing, and contexts

FakeScenario supplies a tuple of FakeResponse entries per role: typed output,
simulated failure disposition, or raw data for schema-invalid simulation. Position
is the persisted role's one-based invocation attempt, without a mutable global cursor.
Scenario exhaustion becomes a terminal simulated agent failure. Explicit
repeat_last=True supports bounded-loop scenarios. Sharing a scenario across tasks
does not share invocation counters. Concurrent runners are unsupported.

ResearchContext holds requirement and at most one prior research reference.
PlanContext holds requirement and accepted research. ImplementationContext holds
approved plan, prior implementation reference, and investigation if relevant.
AnalysisContext holds TestRun and implementation; InvestigationContext adds failure
analysis. ReviewContext holds requirement, plan, implementation, and test evidence.
Only relevant evidence references are supplied, with no unrestricted history or state.

Context selection uses artifacts from COMPLETED invocations whose outputs received
a PASS gate on an actual WorkflowEngine transition/event. The highest persisted
invocation attempt selects the latest accepted output for that role, independent of
UUID repository ordering. A newer unapproved plan cannot replace the approved plan.
JSON outputs are revalidated. Task 6 allows multiple infrastructure attempts per
implementation artifact, selecting the latest by durable execution events. Missing
or ambiguously ordered evidence stops explicitly.

## Invocation and artifact lifecycle

AgentExecutor commits STARTED invocation, AGENT_STARTED event, and Task's
current_invocation_id before the fake call. Role, typed context, and attempt must
match durable task/history. An active invocation cannot be overwritten. Starting
an Implementer increments implementation_attempt; starting a Reviewer increments
review_cycle. These count actual fake calls, separately from retry reservations.

On success a new Artifact uses schema_version="0.1",
content=output.model_dump(mode="json"), producer_agent, producer_model="fake", and
invocation_id. Artifact insertion, invocation COMPLETED/finished_at, and
AGENT_COMPLETED event commit together. Failure rolls back completion/artifact,
leaving the durable STARTED record. Artifacts are never updated. Invocation completion
means valid output was produced; gates still control approval.

Simulated failures atomically append ErrorRecord, set invocation FAILED or BLOCKED,
set finished_at/error_id, and record the lifecycle event. Required model/reasoning
fields use "fake" / "none". No tokens, costs, or provider calls are implemented.
Errors use fixed concise messages. Raw malformed payloads, exception text, and
input-bearing Pydantic validation details are not persisted.

If completion committed but its transition did not, the runner reuses the pending
output without a second agent call. STARTED invocations, or failed invocations with
no committed retry reservation, require explicit reconciliation and record
WORKFLOW_ERROR. This is bounded prototype recovery, not full exactly-once execution.

## Fake TestRun provider and routing

FakeTestResultProvider uses the task's persisted TestRun count plus one to select
a result. It returns TestRun with matching task/implementation IDs, UTC timestamps,
and environment="fake". The runner validates linkage and commits TestRun with
TEST_RESULT_RECORDED. It performs no failure classification or command execution.

COMPLETED + PASS passes TestGate and routes to REVIEWING. COMPLETED + FAIL routes
to ANALYZING with a FAIL TestGate. Sufficient FAIL analysis passes AnalysisGate and
routes to INVESTIGATING. A PASS/no-groups analysis cannot override failed test evidence.
Inconclusive test execution uses the Task 6 provider's structured reliability disposition.
Eligible transient failures retry within TEST_EXECUTION budget; denied recovery stops
with workflow/block evidence. It is never treated as a product defect. Exhausted fake
test scenarios still stop explicitly.

Planner: READY_FOR_IMPLEMENTATION requires PlanGate PASS; NEEDS_RESEARCH routes
to RESEARCHING; BLOCKED stops. Investigator: CODE_FIX/TEST_FIX require identified
root cause and InvestigationGate PASS before IMPLEMENTING; MORE_RESEARCH routes
to RESEARCHING with sufficient gate evidence; HUMAN_ACTION blocks with
resume_state=INVESTIGATING. Reviewer: APPROVE requires ReviewGate PASS and passing
TestRun; REQUEST_CHANGES routes to IMPLEMENTING and requires another test run;
NEEDS_EVIDENCE/BLOCKED stop. Descriptions never choose routes.

Insufficient successful outputs recommend blocking rather than blind retry. Rejected
gates persist when the graph permits the corresponding stop transition. Explicit
NEEDS_RESEARCH and REQUEST_CHANGES take existing backward routes even when
readiness/approval gates fail. No agent can self-approve or mark DONE.

## Reliability integration

AgentError supplies structured FailureDisposition and changed_input metadata.
ReliabilityService records retries in the role's domain. Test Analyzer uses
TEST_EXECUTION because the approved taxonomy has no analysis domain. SCHEMA_ERROR
uses SCHEMA_VALIDATION. CORRECTABLE/schema retry requires scenario metadata
changed_input=True confirming changed relevant input/evidence before the next call;
a different response alone is not inferred to satisfy the rule. TRANSIENT permits
identical input. Denial stops automatic recovery. Schema exhaustion in PLANNING
blocks with resume_state=PLANNING after the initial call and at most two retries.

Committed retry/escalation budgets are never reset. Automatic stronger-model route
reservation is not part of this slice; explicit Task 4 escalation APIs remain available.

Configured FailureIdentity accompanies failed fake tests and is recorded through
ReliabilityService. Three identical occurrences trip the existing circuit breaker.
Evidence follows TESTING -> ANALYZING -> INVESTIGATING; the runner then blocks
before another Investigator/fix call. Missing identity metadata is not inferred from
prose; defect and step budgets still bound those scenarios.

Before repair, can_start_another_defect_cycle checks Task and configured budget.
WorkflowEngine's narrow increment_defect_cycle flag only accepts INVESTIGATING ->
IMPLEMENTING. Counter, transition, and resulting counter event payload commit or
roll back together. No state-machine edge is changed.

## Run loop, limits, and safe stops

WorkflowRunner.run(task_id) loads persisted state and executes one stage per step.
Default max_steps=50 is configurable and must be a positive integer. Completion
at exactly the bound succeeds. Otherwise the bound records WORKFLOW_ERROR with
RUNTIME_STEP_LIMIT and a reliability block recommendation. This bound complements
the separate retry and defect budgets. No queue, scheduler, or next task is started.

Actual BLOCKED/resume always uses WorkflowEngine. The existing graph permits
direct BLOCKED from CREATED, RESEARCHING, PLANNING, INVESTIGATING, REVIEWING,
but not IMPLEMENTING, TESTING, ANALYZING. Terminal operations can use existing
FAILED edges from IMPLEMENTING/INVESTIGATING. If the stop edge is unavailable,
the runner records block/error evidence and raises RunnerStoppedError, preserving
the active snapshot for explicit caller resolution. It never invents an edge or
fabricates intermediate stage success. These unsupported-stop cases are tested.

Invocation completion, test recording, reliability reservations, and state transitions
use separate explicit transactions; none is held across an agent call. Full crash
reconciliation, delivery deduplication, concurrent scheduling, and durable execution
idempotency remain outside Task 5.

## Division example, verification, and remaining scope

`agents/scenarios.py` provides division_scenario() for "Add division support and
reject division by zero", with two acceptance criteria and synthetic research,
implementation, PASS test result, and APPROVE review. repair=True starts with FAIL,
LIKELY_PRODUCT_DEFECT analysis, and CODE_FIX investigation before implementation
and retest.

Happy path: CREATED -> RESEARCHING -> PLANNING -> IMPLEMENTING -> TESTING ->
REVIEWING -> DONE. Repair adds TESTING -> ANALYZING -> INVESTIGATING ->
IMPLEMENTING -> TESTING before REVIEWING -> DONE.

Migrated SQLite tests verify both paths, durable history after reopening, invocation
and artifact linkage, bounded contexts, gate enforcement, retries, schema exhaustion,
blocked stops, circuit breaking, and defect budgets. Injected failures verify atomic
completion and counter rollback; pending outputs are reused after transition failure.

Agent reports remain fake. Task 6 adds PytestTestResultProvider and TestExecutionService
for controlled real pytest on prepared workspace files, while retaining the fake provider.
Both satisfy execution/base.py's TestResultProvider boundary. Real results are already
persisted by the service and verified by the runner; fake results are persisted by the
runner. No provider-type branching or duplicate TestRun insertion is needed.

See EXECUTION.md for argv/path/environment policy, timeout cleanup, durable attempt
selection, start/completion transactions, and the unchanged TESTING stop limitation.
No agent modifies calculator source. Real LLMs, model adapters, prompts, Playwright,
API, CLI, UI, workers, and Task 7 remain unimplemented.
