# Agent runtime — Bootstrap Tasks 5–11

QA Sentinel coordinates one persisted task using fake or reasoning-only real
roles. Agents receive no database/session handle or mutable Task. WorkflowRunner
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
| TESTING | Deterministic real or fake test-result provider | TestRun |
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
fields use "fake" / "none" for fake roles. Task 7 records configured model/reasoning
for real Researcher/Planner, with usage and bounded provider response metadata in
correlated lifecycle events; no cost fields or schema migration is added.
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

Task 5 agent reports are synthetic. Task 6 adds PytestTestResultProvider and TestExecutionService
for controlled real pytest on prepared workspace files, while retaining the fake provider.
Both satisfy execution/base.py's TestResultProvider boundary. Real results are already
persisted by the service and verified by the runner; fake results are persisted by the
runner. No provider-type branching or duplicate TestRun insertion is needed.

See EXECUTION.md for argv/path/environment policy, timeout cleanup, durable attempt
selection, start/completion transactions, and the unchanged TESTING stop limitation.
Task 7 adds a provider-neutral Responses API
adapter, bounded repository-owned prompts, real Researcher/Planner, and explicit
CompositeAgentRuntime routing. Task 8 extends real reasoning to later roles. See MODELS.md for no-tools
requests, provenance, sanitized errors, stateless context, deterministic schema
correction, disabled SDK retries, and offline tests. Task 9 adds reasoning-only real
Implementer proposals and deterministic MutationService. Playwright, API, CLI, UI,
workers remain unimplemented.

## Task 8 failure reasoning and explicit escalation

Test Analyzer classifies observed failures and requests investigation; its prompt
does not perform RCA or recommend edits. Investigator performs structured RCA
and recommends one enum action without executing repair. Reviewer evaluates every
required criterion against supplied evidence; only ReviewGate/WorkflowEngine can
approve progression to DONE. Model requests stay tool-free and bounded.

The routed Investigator runtime exposes primary/escalated model configuration.
WorkflowRunner feeds primary results into Task 4 ReliabilityService, preserving
thresholds and durable budget. A MODEL_ESCALATED reservation correlates primary
invocation/artifact and failing TestRun. The next step builds an explicit escalated
context and invokes AgentExecutor again, with independent lifecycle and artifact.
The primary artifact remains history; the successful escalated result is the sole
routing candidate. Gate failure or provider failure never selects primary as fallback.
Retries use existing domains and remain on the reserved route. STARTED reconciliation,
transaction rollback, circuit checks, defect bounds, and max_steps remain unchanged.

No-trigger primary results use normal InvestigationGate routing. A later primary
with required escalation and exhausted budget blocks. A completed escalated result
is never recursively escalated. Reconstruction uses committed events and attempts,
not mutable provider memory; a reopened runner uses the same reservation.

Integration tests prove real pytest FAIL -> real classification -> real RCA -> fake
Implementer -> real pytest PASS -> real Reviewer -> DONE through existing gates.
The fixture harness independently switches prepared workspace state before retest;
fake Implementer only returns synthetic structured evidence. Request-changes creates
new implementation/test/review attempts. HUMAN_ACTION blocks at INVESTIGATING.
Reviewer APPROVE with incomplete coverage fails ReviewGate. Analyzer refusal or
exhausted recovery still cannot take an ANALYZING -> BLOCKED edge; it records errors
and raises RunnerStoppedError while preserving ANALYZING.

## Task 9 controlled implementation

RealAgentRuntime advertises proposal capability; composite routing delegates this
to its Implementer runtime. AgentExecutor uses ControlledImplementationExecution
with an explicitly configured MutationService, while fake Implementer remains
unchanged. The real path commits STARTED, captures current accepted-plan-authorized
source, calls the model, validates and reserves the proposal, applies files, then
commits canonical ImplementationOutput and COMPLETED with actual applied evidence.
No DB transaction spans the model call or project writes. Source snapshots use fresh
SHA-256 preconditions on every attempt, including repair.

IMPLEMENTATION_PROPOSAL is separate immutable evidence. Canonical pending-output
selection filters by output ArtifactType because a real Implementer invocation has
two artifacts. On restart, completed canonical output is hash-verified and reused
without another call/apply; it is verified again before TESTING. Failed application
does not publish success. Successful writes followed by persistence failure or
failed rollback remain unresolved STARTED and require explicit reconciliation.
The graph, gates, retries, escalation, defect and circuit budgets remain unchanged.

Task 9 tests apply actual calculator mutations in temporary targets: first proposal
omits the guard, real pytest fails, Analyzer/Investigator diagnose, second Implementer
proposal fixes current code, real pytest passes, Reviewer and ReviewGate reach DONE.
No fixture switches source state. See MUTATION.md for configuration, protected paths,
size/encoding limits, rollback, reconciliation and trusted-workspace/TOCTOU limits.

## Task 10 controlled repository reasoning

WorkflowRunner/AgentExecutor optionally receive RepositoryReadService. Only enabled
Researcher/Planner runtimes use ControlledRepositoryExecution, which handles typed
TOOL_REQUEST/FINAL_OUTPUT turns. It commits provider reservations before calls and
validated completion metadata afterward; deterministic reads occur outside database
transactions. Each result becomes immutable REPOSITORY_EVIDENCE linked to its
request and explicit call index. Overall STARTED persists until final role output;
final canonical artifacts and existing gates retain their original semantics.

The loop permits at most the configured read count plus one final model turn. A
further request records exhaustion without executing a read. Denials and read
failures stop through existing error/reliability handling. No generic tools, hidden
retries, parallel calls or changes to state-machine edges/gates/budgets are added.

Restart reconstructs completed model turns and ordered durable results under the
same context/model/root configuration. It reuses results and durable final outputs.
An unresolved provider reservation or inconsistent history stops for reconciliation.
A read whose result commit failed can be repeated from its durable request because
it is read-only; exactly-once reads and snapshot isolation are not promised. Task 9
write/persistence reconciliation remains unchanged. See REPOSITORY_TOOLS.md.

## Task 11 Project composition

Every Task now requires a persisted Project UUID. Workspace-backed runners and
executors require an explicit frozen ProjectWorkspaceBinding; real TestExecutionService
independently requires the same binding before process reservation/start. Reader,
mutation and real provider roots must match it. Pure supplied-context/fake workflows
may omit physical binding while retaining explicit Project ownership.

ProjectRuntimeRegistry resolves trusted bindings with no model access or progression
logic. PROJECT_WORKSPACE_BOUND stores a root/Project identity digest before first
bound work. Wrong ownership/composition or restart drift records WORKFLOW_ERROR and
raises RunnerStoppedError while preserving state; no product test FAIL or recovery
framework is introduced. Accepted artifact selection remains strictly task-scoped.
Task 9/10 reconciliation and gate/state/reliability policies remain authoritative.
See PROJECTS.md for composition examples, legacy-evidence adoption and limitations.
