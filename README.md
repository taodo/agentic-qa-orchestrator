# Agentic QA Orchestrator

**Agentic QA Orchestrator** is a QA platform for preparing requirements, test specifications, human review and coverage within Project-owned QA Campaigns.

The browser now starts with **Projects → Campaigns**. Open a Project, create a Campaign with a name and optional objective, then inspect Overview, Requirements, Test Specifications, Traceability and Readiness through direct links. These preparation views use saved backend records, explicit preparation commands and read-only readiness assessments. An empty Campaign stays empty; the browser does not invent demonstration requirements or tests.

The product journey is PRD / Existing Tests → Requirements → Test Specifications → Human Review → Traceability / Readiness → QA Run → Evidence / Analysis / Reporting.

Phase 2 preparation APIs are implemented. Task 3.2 adds explicit browser preparation actions: paste TEXT/Markdown specifications, ingest sources, extract Requirements, import strict CSV/Markdown test cases, generate Test Specifications from 1–20 selected Requirements, and record human approval. Ingestion never starts extraction; model work is explicit and requires trusted local configuration. PDF/XLSX are unsupported. Task 3.5 adds [explicit failed-extraction retry and grounded clarification recovery](docs/PREPARATION_RECOVERY.md), with preserved history, new Requirement identities and renewed review of replacement tests. Contextual Campaign submission/approval keeps preparation separate from readiness. Campaign preparation `APPROVED` and derived readiness `READY` are separate. Neither indicates that tests have executed or passed. Bounded lists disclose omitted records; summary totals come from readiness aggregates.

Legacy Task workflows remain available under **Legacy workflows** within a Project, with Operations in secondary navigation. Their runtime and evidence boundaries remain unchanged. Protected public demo modes are deterministic synthetic demonstrations; trusted real-local execution remains local operator infrastructure. Tasks 3.3–3.4 add [immutable QA Run snapshots and Campaign Runs UX](docs/QA_RUNS.md). READY preparation can be frozen into a Run, then explicitly started using a deterministic synthetic fixture. Assertion FAIL continues to later tests; execution status and QA outcome remain separate. No external target is tested in this mode. Synthetic execution validates lifecycle/orchestration UX, not target correctness. Real API execution is Phase 5; real browser/Playwright execution is Phase 6. QA reporting remains future work.

The project started as **QA Sentinel**. Source mutation and repair are historical infrastructure, not the product's primary journey.

> **Agents reason. Tools act. Evidence records reality. The orchestrator controls progression.**

## What this project demonstrates

This repository is designed to show more than a collection of AI prompts. It focuses on the engineering problems that appear when AI is allowed to participate in real QA and repair workflows:

- deterministic workflow/state-machine control
- typed contracts between agents
- bounded repository research
- explicit approval gates
- controlled whole-file mutation
- stale-write and workspace-boundary protection
- trusted pytest execution
- retries, escalation and reconciliation
- durable execution jobs
- audit-friendly evidence
- local real-project onboarding
- protected synthetic demo modes

The core idea is simple: an LLM may propose or reason about work, but it does **not** directly control the filesystem, shell, workflow state, or final approval.

Phase 2 preparation now includes [explicit human approval, Requirement/Test
traceability and derived Campaign readiness](docs/CAMPAIGN_REVIEW.md). Readiness
is separate from Campaign preparation status and does not execute tests.

## Legacy Task workflow

An existing legacy Task progresses through:

```text
CREATED
  ↓
RESEARCHING
  ↓
PLANNING
  ↓
IMPLEMENTING
  ↓
TESTING
  ↓
REVIEWING
  ↓
DONE
```

When tests fail, the workflow can move through structured analysis and investigation before a bounded repair/retest cycle.

```text
TESTING
  ↓
ANALYZING
  ↓
INVESTIGATING
  ↓
IMPLEMENTING
  ↓
TESTING
```

Progression is controlled by deterministic gates rather than by an agent simply saying that a task is complete.

## Architecture

```text
                         ┌──────────────────────────┐
                         │      Requirement         │
                         └────────────┬─────────────┘
                                      │
                                      ▼
┌──────────────┐   evidence   ┌──────────────────────┐
│ Researcher   │─────────────▶│    Research Gate     │
└──────────────┘              └──────────┬───────────┘
                                         │
                                         ▼
┌──────────────┐              ┌──────────────────────┐
│ Planner      │─────────────▶│      Plan Gate       │
└──────────────┘              └──────────┬───────────┘
                                         │
                                         ▼
┌──────────────┐  proposal    ┌──────────────────────┐
│ Implementer  │─────────────▶│ Implementation Gate  │
└──────────────┘              └──────────┬───────────┘
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │ Controlled Mutation  │
                              └──────────┬───────────┘
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │ Deterministic Pytest │
                              └──────────┬───────────┘
                                         │
                          fail ┌──────────┴──────────┐ pass
                               ▼                     ▼
                        Analyzer /             Reviewer
                        Investigator               │
                               │                    ▼
                               └──────────────▶    DONE
```

The main architectural boundary is:

```text
Reasoning agents
      │
      ▼
Structured contracts
      │
      ▼
Deterministic policies / gates
      │
      ▼
Trusted tools
      │
      ▼
Persisted evidence
```

## Key engineering features

| Area | What is implemented |
| --- | --- |
| Workflow | Explicit state machine with guarded transitions and terminal protection |
| Agents | Researcher, Planner, Implementer, Test Analyzer, Investigator and Reviewer |
| Contracts | Strict Pydantic schemas for agent outputs and evidence |
| Repository access | Bounded read-only LIST / READ / SEARCH tools for research and planning |
| Mutation | CREATE / MODIFY only, whole-file proposals, SHA freshness and stale-write protection |
| Execution | Restricted pytest-only command policy, bounded output and process cleanup |
| Reliability | Retry budgets, escalation, circuit-breaking and safe blocking |
| Persistence | SQLite + SQLAlchemy + Alembic with durable task/evidence history |
| Jobs | Durable QUEUED / RUNNING / SUCCEEDED / STOPPED / FAILED execution jobs |
| Reconciliation | Read-only crash/recovery assessment before unsafe continuation |
| API | FastAPI application boundary over orchestration and persistence |
| UI | React/TypeScript project, task, evidence and operations views |
| Real projects | Explicit local workspace onboarding and real-target proving |
| Demo safety | Synthetic fake-only preview/hosted modes separated from real execution |

## Why the separation matters

The system deliberately keeps several concepts separate:

- **Task state** is not the same as an execution-job status.
- **Test evidence** is not the same as an Implementer claim.
- **Reviewer approval** does not directly set `DONE`.
- **Repository visibility** does not automatically grant write authority.
- **A model request** does not directly become a filesystem or shell action.
- **A failed or interrupted run** is preserved as evidence rather than silently retried into success.

This makes the workflow easier to inspect and safer to extend.

## Demo modes

### Synthetic demo

The repository includes a deterministic demo project that requires:

- no OpenAI API key
- no live model calls
- no source mutation
- no real pytest subprocess
- no external project

This is useful for exploring the state machine, UI, evidence model and operational views safely.

### Real local mode

Real local mode can bind a Project to an explicitly configured local workspace and enable:

- bounded repository research
- real model-backed reasoning
- controlled mutation proposals
- deterministic pytest execution
- persisted workflow evidence

Real local mode is intentionally loopback-only and operator-controlled.

## Daily local start — already configured workspace

After one-time Python/Node dependency setup, an existing Project, current database
and trusted local config, use this from the source/editable checkout:

```powershell
$env:OPENAI_API_KEY = "sk-..."
qa-sentinel local start --config .\qa-sentinel.local.json
```

Use your own key only in the current process environment; never save it in JSON,
source or chat. Startup checks its presence, not provider connectivity or validity.

- **Normal restart:** stop with Ctrl+C, then run the same command again:
  frontend build → authoritative local validation → foreground loopback server.
- **Frontend changed:** no extra step; start runs `npm run build` every time.
  Configure `frontend_dist` to this checkout's `frontend/dist`. Node/npm and
  already-installed frontend dependencies are required; start never runs `npm ci`.
- **Database migration required:** startup stops, showing safe current/required
  schema identifiers when available. No migration runs automatically. Stop hosts,
  inspect the applicable migrations and explicitly upgrade the selected database
  before starting again. See [manual DB preparation](docs/HOSTING.md#local-one-command-start).

Startup runs no test suite or target proving action. Existing explicitly queued
execution requests retain the normal host worker semantics after serve starts.
Lower-level `qa-sentinel local validate --config ...` and
`qa-sentinel serve --config ...` remain available for troubleshooting. Unlike
`local start`, lower-level `serve` retains its existing migration/bootstrap behavior.
See [local onboarding and hosting](docs/HOSTING.md#local-one-command-start).

## Quick start — synthetic demo

Requirements:

- Python 3.12+
- Node.js 22.12+

From the repository root:

```shell
python -m pip install -e ".[test]"

cd frontend
npm ci
npm run build
cd ..

qa-sentinel serve --demo
```

Open:

```text
http://127.0.0.1:8000
```

Suggested demo flow:

1. Open **Demo Calculator**.
2. Create a task named **Division support**.
3. Use the requirement: **Add division support and reject division by zero.**
4. Click **Run**.
5. Inspect the timeline, artifacts, invocations, test runs, decisions and gates.
6. Open **Operations** to inspect durable execution status.

The demo is synthetic by design; changing the requirement does not turn it into arbitrary autonomous software execution.

## Real-project proving

Before allowing a real workflow to touch a target repository, the project provides explicit target checks.

Typical operator flow:

```text
Project
  ↓
target-check
  ↓
target-test
  ↓
real-local configuration
  ↓
Task Run / Resume
```

`target-check` validates workspace/configuration/policy without running tests or models.

`target-test` performs one explicitly approved pytest proving run without creating a QA workflow Task.

See [Real targets](docs/REAL_TARGETS.md) and [Hosting](docs/HOSTING.md) for the current operator model.

## Safety boundaries

The project intentionally does **not** provide unrestricted autonomy.

Current guardrails include:

- no arbitrary shell execution
- no arbitrary executable arguments from agents
- no DELETE mutations
- protected path rejection
- workspace escape and symlink/junction checks
- stale source detection with SHA-256
- bounded source/result sizes
- restricted environment propagation
- pytest-only trusted execution
- fake-only public/demo execution modes
- no hidden chain-of-thought persistence
- no raw provider-response persistence
- explicit reconciliation after uncertain runtime outcomes

Prepared tests are executable code, so these controls are policy boundaries rather than an OS sandbox.

## Project status

The repository now contains the full Phase 1 foundation rather than the original skeleton:

- agent/runtime contracts
- deterministic workflow and gates
- persistence and migrations
- controlled repository tools
- controlled source mutation
- deterministic pytest execution
- reliability and reconciliation
- FastAPI application/API
- React operator UI
- durable execution jobs
- operations visibility
- local real-target proving

The next product work focuses on making the experience easier to operate and extending the platform from repair-oriented workflows toward broader QA execution.

Planned direction:

```text
UX optimization
    ↓
Context / token efficiency & cost observability
    ↓
PRD / test-case ingestion → structured test specifications
    ↓
Controlled API testing
    ↓
Controlled Playwright/browser testing
    ↓
QA campaign dashboard and traceability
```

## Repository structure

```text
src/qa_sentinel/
├── agents/          reasoning roles and prompts
├── api/             FastAPI routes and API models
├── application/     application-service boundary
├── domain/          workflow/evidence domain models
├── execution/       deterministic command and pytest execution
├── host/            local/demo/hosted composition
├── models/          provider-neutral model abstraction
├── mutation/        controlled write policy/service
├── orchestration/   gates, workflow runner and reliability
├── persistence/     SQLAlchemy repositories and records
├── repository/      bounded read-only repository access
└── schemas/         structured agent/tool contracts

frontend/            React + TypeScript operator UI
alembic/             database migrations
docs/                architecture, product and operator documentation
tests/               unit and integration coverage
```

## Validation

Backend:

```shell
python -m pytest
```

Frontend:

```shell
cd frontend
npm ci
npm test -- --run
npm run build
```

Repository check:

```shell
git diff --check
```

Automated model tests use mocked provider boundaries and do not require a live API key.

## Documentation

Good starting points:

- [Product Guide](docs/PRODUCT_GUIDE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [PRD](docs/PRD.md)
- [State Machine](docs/STATE_MACHINE.md)
- [Runtime](docs/RUNTIME.md)
- [Repository Tools](docs/REPOSITORY_TOOLS.md)
- [Mutation Safety](docs/MUTATION.md)
- [Execution](docs/EXECUTION.md)
- [Reliability](docs/RELIABILITY.md)
- [Reconciliation](docs/RECONCILIATION.md)
- [Real Targets](docs/REAL_TARGETS.md)
- [Deployment](docs/DEPLOYMENT.md)

## Portfolio note

This project is intentionally built as an engineering portfolio rather than a thin AI demo. The focus is on orchestration, QA evidence, safe execution boundaries, recoverability, auditability and the practical constraints of letting reasoning models participate in software-quality workflows.

The repository name reflects the broader direction: **Agentic QA Orchestrator**.
