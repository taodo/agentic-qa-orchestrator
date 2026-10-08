# Codex Context

> Compact architecture and development map for Codex. Read this file before task-specific repository exploration. This is a context selector, not a replacement for task acceptance criteria or concrete dependency inspection.

## Product identity

Agentic QA Orchestrator is a QA engineering platform. Its core job is to turn requirements and test specifications into controlled QA campaigns, execute eligible tests through deterministic tools, persist evidence, analyze failures, maintain traceability, and produce QA-facing results and reports.

The product is **not** a coding agent and self-repair is not a core roadmap capability.

Source repository access is optional. A useful QA campaign must be possible without source code when sufficient black-box inputs such as a PRD, target URL, API contract, credentials, or existing test cases are available.

Core principle:

> Agents reason. Tools act. Evidence records reality. The orchestrator controls progression.

## Current stable architecture

The existing platform already contains:
- durable Projects, Tasks, workflow state, gates, decisions, artifacts, invocations, test runs, and execution jobs;
- deterministic orchestration and explicit state transitions;
- Researcher, Planner, Implementer, Test Analyzer, Investigator, and Reviewer contracts from earlier phases;
- bounded read-only repository tools for Researcher/Planner;
- controlled mutation infrastructure from earlier proving work;
- deterministic pytest execution with command/workspace/environment policy;
- local-real project onboarding and target validation;
- isolated trusted target Python configuration;
- hosted synthetic/demo mode;
- reconciliation and operational observability;
- FastAPI application/API and React/TypeScript/Vite frontend.

Do not assume every historical capability is part of the future product direction. In particular, source mutation/self-repair is legacy/experimental infrastructure, not a feature to expand unless a future task explicitly reintroduces it.

## Phase 2 complete: accepted preparation boundary

Tasks 2.1–2.4 provide Project-owned Campaigns, immutable specification sources,
structured Requirements, imported/generated executor-neutral Test Specifications,
explicit human approval receipts and scoped derived traceability/readiness.
Campaign APPROVED remains independent of readiness READY. Task 3.3 adds QA Run
preparation snapshots; Task 3.4 adds a pure synthetic lifecycle shell. No real
Campaign executor exists. Migration head is 0010; see
[review contracts](CAMPAIGN_REVIEW.md) and [QA Run contracts](QA_RUNS.md).

## Current Phase 3 increment: Task 3.7

Task 3.1 established Project → Campaign navigation and bounded preparation views.
Task 3.2 adds explicit browser source ingestion (pasted TEXT/Markdown), extraction,
strict CSV/Markdown test import, generation from 1–20 explicitly selected
Requirements, and Requirement/Test approval with operator-asserted reviewer labels.
Review evidence loads only on request. PDF/XLSX remain unsupported. Task 3.5 adds bounded clarification recovery
without a generic Requirement editor. Ingestion never invokes extraction automatically; no write or
model action runs on mount, polls, or automatically retries. Shared same-origin
session/CSRF/error transport remains unchanged; route changes discard late action
completion. Contextual Campaign transitions preserve DRAFT → READY_FOR_REVIEW →
APPROVED independently of derived READY/NOT_READY. Scoped reads refresh after writes;
traceability and name decoration remain independent, bounded resources.

Task 3.2 adds no Campaign Run, execution, PASS/FAIL, source mutation or auth redesign.
Legacy Tasks/Operations and trusted local interpreter boundaries remain unchanged.
Task 3.3 adds first-class Project/Campaign-owned QARun metadata and immutable
Requirement/Test snapshots through migration 0008. Create requires accepted READY
readiness and full approval-hash validation; it performs no model/tool/executor or
legacy Task/job action. New Run CREATED/NOT_EVALUATED and test
NOT_STARTED/NOT_EVALUATED are independent progress/outcome contracts. Snapshot
hashes are versioned audit identities; caller keys handle retries, distinct keys
allow intentional duplicate preparation. Accepted SQLite writer reservation protects
atomic snapshots and unique Campaign run numbering. Bounded stored snapshot reads
remain independent of later preparation changes. See [QA Runs](QA_RUNS.md).
Task 3.4 adds Campaign Runs list/create/detail and explicit synchronous synthetic
Start. Execution reads only persisted QARunTest.content; synthetic-position-v1
returns odd-position PASS / even-position FAIL, with no title semantics or target
execution. Short reserved transactions commit Run RUNNING, each test RUNNING and
COMPLETED/result, then aggregate persisted tests. Assertion FAIL continues; normal
Run COMPLETED may have QA FAIL. System failure gives FAILED + safe code, PARTIAL
if earlier tests completed, otherwise NOT_EVALUATED; earlier results survive.
Migration 0009 adds only the nullable safe Run execution_error_code. Immutable
content/approval/links/positions never update. Only CREATED starts; concurrent and
terminal starts reject. No models, network, browser, subprocess, target filesystem,
legacy Task/job evidence, retry/resume, Stop or crash replay. Frontend uses explicit
intent keys, bounded snapshot pages, shared CSRF and stale-completion guards, with
clear synthetic warnings. Phase 4 evidence/reporting remains future work.

Task 3.5 adds explicit extraction retry (three attempts/source), independent usage
and durable history, plus inert operator clarification sources and separate AI
revision into new Requirement identities (ten versions/chain). Superseded content
and approvals remain audit evidence; current-only filtering retires dependent
Tests from coverage/readiness/new Run selection until replacements are explicitly
reviewed. Initial Extract stays idempotent; reads never invoke providers. Migration
0010 preserves old attempts and refuses audit-destructive downgrade. No synthetic
executor change. See [preparation recovery](PREPARATION_RECOVERY.md).

Task 3.6 adds a restrained dark product UI foundation: contextual desktop sidebar,
shared headings/status badges, current preparation content before secondary audit
history, read-only next-step guidance from existing readiness codes, and explicit
synthetic Run presentation. Shell context reuses loaded data; no new API reads,
actions, lifecycle rules, provider/token behavior, dependencies or migrations.
See [workspace UI conventions and review checklist](WORKSPACE_UI.md).

Task 3.7 adds action-local AI summaries for extraction, revision and generation,
with independent provider token categories and configured/reported model labels.
A bounded read-only projection exposes existing immutable output counts, revised
identity and inherited clarification; no migration/accounting change. Distributions
are explicitly at creation, independent of later approval. Generation history uses
the existing lazy bounded read route. See [AI action results](AI_ACTION_RESULTS.md).

## Product direction

The next product model is QA-campaign oriented:

Project
→ QA Campaign
→ Requirements
→ Test Cases / Test Specifications
→ Human review/approval where required
→ QA Run
→ Test Results
→ Evidence
→ Failure Analysis
→ Defects / QA Report

Planned phases:
1. Context & Token Efficiency
2. QA Campaign + PRD/Test Case Ingestion
3. QA-oriented UX / Run Lifecycle
4. QA Campaign Dashboard + Evidence + Reporting
5. Deterministic API Testing
6. Deterministic Browser / Playwright Testing

Phase 4 is the intended showcase MVP milestone.

## Non-negotiable QA execution invariant

An individual test failure is **data**, not an execution-system failure.

For a campaign with multiple eligible tests:
- persist PASS/FAIL/SKIP and evidence per test;
- a normal product/assertion failure must not stop the remaining eligible tests;
- continue executing subsequent tests;
- after execution, aggregate and analyze all collected failures;
- distinguish execution status from QA outcome.

Example:

Execution status: COMPLETED
QA outcome: FAIL
Total: 100
Passed: 93
Failed: 5
Skipped: 2

Early termination is reserved for genuine execution-blocking conditions such as runner/environment failure, required unavailable credentials, safety/policy violation, or explicit operator stop.

Do not introduce fail-fast campaign semantics for ordinary test failures.

## Architecture boundaries

### Orchestrator
Owns workflow progression, state transitions, gates, retries/recovery policy, and durable coordination. Agents do not directly change workflow state.

### Agents
Reason over explicitly supplied bounded context and return structured contracts. They must not silently gain shell, arbitrary filesystem, network, mutation, or execution authority.

### Deterministic tools/executors
Perform real actions under explicit host policy. Execution evidence is authoritative over agent claims.

### Evidence
Persist durable, auditable evidence. Prefer structured accepted artifacts over replaying large raw histories. Claims by an agent are not equivalent to independent evidence.

### Source repository
Optional diagnostic context. Read access may improve analysis when available. Write access, commits, pushes, and self-repair are not core product requirements.

### Test execution
Keep execution status separate from QA outcome. Preserve deterministic policy boundaries and target isolation.

## Repository navigation guidance

Before broad exploration:
1. inspect Git branch/status and task diff using Git metadata;
2. read this file;
3. inspect only task-relevant areas;
4. follow concrete dependencies only when necessary;
5. avoid rediscovering the entire repository architecture.

Use task-specific paths from the prompt. If scope must expand, explain the concrete dependency in the FINAL REPORT.

Likely areas by concern:
- domain/workflow/state/gates: search under the Python package for domain, orchestration, workflow, gates, and policies;
- agents/model prompts/contracts: agent, model, prompt, and schema modules;
- deterministic execution: execution/test runner/command policy services and related schemas;
- repository reads: repository policy/service plus repository schemas and agent repository-session integration;
- persistence: SQLAlchemy models/repositories, database services, and Alembic migrations;
- application/API: app/service/facade and FastAPI routes/schemas;
- frontend: frontend/src and colocated/relevant frontend tests;
- docs: docs/ plus root README where public behavior changes.

Prefer exact symbol/path discovery from Git/search over reading whole directories.

## Context and token efficiency rules

For development work:
- use Git metadata/diffs before source reads;
- read only relevant files and concrete dependencies;
- reuse accepted architecture from this document;
- avoid repeatedly loading large unchanged artifacts or repository content;
- prefer structured summaries/IDs over raw historical transcripts where semantics allow;
- do not optimize by weakening evidence, auditability, safety bounds, or correctness.

For product/runtime optimization, preserve semantic completeness: token reduction must not cause an agent to claim it considered evidence that was actually omitted.

## Validation strategy for Codex tasks

Use progressive validation:

inspect relevant code
→ implement bounded change
→ run focused tests
→ fix failures
→ rerun focused tests
→ run ONE appropriate full suite at final validation

Do not repeatedly run the full suite during implementation unless a failure cannot be isolated with focused tests.

Choose the final full validation by affected scope:
- backend/Python-only: full Python suite once;
- frontend-only: full frontend test suite/build once as required;
- cross-stack: both once at final validation;
- run additional suites only when a concrete integration dependency requires them.

Record unrelated pre-existing failures instead of repeatedly rerunning the full suite.

Always run git diff --check and report dependency/migration changes.

## Development workflow

Stable/showcase branch: main.
Accepted integration branch: feature/develop.
Task work uses a dedicated feature/task-* branch based on the accepted integration branch unless the task explicitly states otherwise.

Codex:
- implements/tests/commits/pushes only the task branch;
- does not merge;
- posts a complete FINAL REPORT to the task issue.

ChatGPT:
- owns architecture/spec/review;
- reviews the task diff/report;
- merge happens only after explicit human approval.

## Phase 1 reminder

Phase 1 Context & Token Efficiency is accepted infrastructure. Optimize runtime context selection and token/cost observability without changing product semantics. Keep the work bounded and measurable; do not turn it into a general architecture rewrite.

The later QA Campaign phases must preserve the execution invariant above and must not depend on source code or self-repair.
