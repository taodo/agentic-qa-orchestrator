# QA Sentinel product requirements — implemented Phase 1

This PRD describes implemented Tasks 1–17. Task 18 adds product documentation
and lightweight onboarding, not runtime capabilities. Read the [Product Guide](PRODUCT_GUIDE.md)
for operation and [Features](FEATURES.md) for the inventory. [Phase 1](PHASE_1.md)
records historical checkpoints.

## Problem

QA work crosses requirement interpretation, test strategy, source changes,
deterministic tests and review. Separate answers/logs make it difficult to tell
whether a change met the requirement, whether failing tests reveal a product
defect or an execution problem, and why work stopped.

QA Sentinel connects these activities to a Project-owned Task with structured
evidence and inspectable routing. A passing test is not requirement coverage;
an agent recommendation is not a deterministic Gate.

## Target users

| User | Need served by implemented behavior |
| --- | --- |
| QA Manager | Inspect QA state, requirement coverage and recorded Decisions |
| Senior QA / SDET | Execute/investigate a bounded QA workflow on a prepared trusted workspace |
| Engineering lead | Review source-change evidence, tests and recovery stops |
| Product/engineering team | Trace a requirement through planning, implementation, tests and review |

These are Operator personas, not product accounts or permission roles.

## Product goals

- Coordinate research, planning, implementation, testing, analysis, investigation
  and review through the accepted workflow.
- Preserve distinct evidence, provenance and material Decisions.
- Separate model reasoning from deterministic reads, writes, tests and progression.
- Make completion/safe stops inspectable through bounded API/UI views.
- Support plan-authorized mutation and Project/workspace isolation in trusted
  local execution.
- Teach the workflow through a protected deterministic preview without API keys,
  real source writes or real test processes.

QA Sentinel coordinates test automation rather than replacing it. It is neither
a chatbot, unrestricted coding agent, CI/CD replacement nor bug tracker; there
is no ticket synchronization or production user-management system.

## Non-goals

Phase 1 is not a generic autonomous software factory, unrestricted shell agent,
public multi-tenant SaaS, full CI/CD replacement, production auth/RBAC system or
distributed worker platform. It supplies no cloud workspace, remote repository
clone, background queue, streaming or automatic crash reconciliation. These
are exclusions, not roadmap promises.

## Principles and application boundary

**Agents reason. Tools act. Evidence records reality. Orchestrator controls progression.**

**External callers use Application Services, not orchestration internals or
persistence repositories directly.** The frontend consumes a thin API over
QASentinelApplication. Trusted host composition selects services; request/model
data cannot choose workspace roots or change state directly.
[Architecture](ARCHITECTURE.md), [Application](APPLICATION.md).

## User journeys

### Local demo user

Build the frontend, start `qa-sentinel serve --demo`, open Demo Calculator and
create **Division support** with **Add division support and reject division by
zero.** Run and inspect DONE/evidence. Learn the console without mistaking
synthetic tests for verification of local source. [Walkthrough](PRODUCT_GUIDE.md#demo-mode).

### Real local Project user

Create logical Project identity, prepare a trusted target/tests, and explicitly
configure that existing Project's key, workspace and test targets. Supply
OPENAI_API_KEY through the local environment. Run through bounded reads,
structured proposals, controlled mutation, actual pytest and independent review.
Keep exclusive workspace access and the host loopback-only. Creation alone does
not enable execution. [Hosting](HOSTING.md#real-local-mode).

### Operator investigating failed execution

Refresh Overview and inspect Timeline, Errors, Invocations and Test Runs.
Distinguish completed FAIL tests from FAILED/INCOMPLETE execution with UNKNOWN
outcome. Inspect Decisions/Gates and refs. A safe stop may leave an active state
unchanged rather than becoming BLOCKED/FAILED. Resolve configuration or uncertain
execution with the trusted host owner instead of repeatedly clicking Run.
Resume restores a stored state, not reconciles uncertain work.

### Reviewer validating evidence before DONE

The human Operator inspects PLAN criteria, canonical IMPLEMENTATION, the latest
conclusive Test Run, REVIEW coverage, Gates and the actual DONE transition.
The model-based Reviewer recommends; deterministic ReviewGate/WorkflowEngine
control completion. There is no human approval button or reviewer permission role.

## Core workflow

Canonical states: CREATED, RESEARCHING, PLANNING, IMPLEMENTING, TESTING, ANALYZING,
INVESTIGATING, REVIEWING, BLOCKED, FAILED and DONE. DONE/FAILED are terminal;
BLOCKED stores an explicit resume_state. Only the Orchestrator changes state.
[State/role guide](PRODUCT_GUIDE.md#workflow-states), [exact graph](STATE_MACHINE.md).

The normal completed path passes research, plan, implementation, test and review
checks. Completed failing tests may enter analysis/investigation and an authorized
repair/retest. Gate rejection, insufficient evidence, policy violations or bounded
recovery can stop execution. Model prose cannot select an unlisted edge;
recommendations/reservations are not proof of completed actions.

## Success criteria

- A new Operator can explain Project, Task, Run and Resume and complete the
  synthetic walkthrough without understanding runtime setup internals.
- An Operator can inspect requirement, current state, evidence, deterministic
  checks and recorded reasons without hidden reasoning.
- Product FAIL and inconclusive test execution are distinguishable.
- Real local writes are accepted-plan-authorized CREATE/MODIFY with exact hash
  preconditions; stale or uncertain writes stop for reconciliation.
- Persisted Project identity determines ownership and trusted runtime resolution.
- Public preview access exposes no real model/read/mutation/pytest service.

These are qualitative product acceptance criteria, not invented usage metrics,
customer outcomes or reliability guarantees.

## Why these boundaries exist

| Decision | Purpose and practical limit |
| --- | --- |
| Deterministic state machine instead of LLM-owned transitions | Makes progression testable and rejects unlisted edges |
| Evidence before progression | Separates output validity, tests and acceptance; PASS remains gate-specific |
| ProjectWorkspaceBinding outside persistence | Keeps trusted roots outside logical Project/request/model data; drift stops existing Tasks |
| Controlled mutation instead of direct agent writes | Validates complete authorized sets/hashes/bounds; filesystem and DB are not a distributed transaction |
| Bounded repository reads | Limits roles, paths, content and work; arbitrary source must still be secret-free |
| Synchronous Run | Preserves explicit execution/safe stops without adding a queue |
| Single-process host | Serializes admitted Run/Resume without claiming distributed coordination |
| Demo-only public preview | Teaches evidence inspection without exposing trusted local execution |

## Risks and limitations

Run occupies a synchronous request. One process/worker admits one Run/Resume;
overlap receives a safe conflict. There is no frontend polling or hidden retry.
SQLite is the Phase 1 database; bounded views are not full history when truncated.
Timestamps/refs do not guarantee universal cross-table causal order or exactly-once
execution.

Prepared source/tests and local access are trusted. Policies/hashes/rollback are
not an OS sandbox, arbitrary-content secret detector or protection from hostile
concurrent writers. Successful writes followed by failed persistence, unresolved
calls or test reservations require deliberate reconciliation.

The preview scenario is fixed/synthetic even for a different requirement.
Preview state may reset on restart/redeploy. Basic access is a temporary shared
gate, not product users/RBAC. Local hosts have no authentication and stay
loopback-only. Do not put secrets into requirements, source evidence or preview.

## Current phase

Tasks 1–17 implement contracts, persistence, deterministic orchestration,
bounded reliability, real local reasoning/actions, Project isolation, application
and API boundaries, operator UI, local hosting and a protected Render demo path.
The public preview is **deterministic synthetic demo only**. The owner supplies
its current generated HTTPS URL/access privately; neither is embedded here.
This PRD adds no deployment or architecture/runtime capability.
