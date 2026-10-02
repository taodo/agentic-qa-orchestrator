# QA Sentinel — Agentic QA Orchestrator

QA Sentinel coordinates reasoning agents, deterministic tools, evidence and
workflow gates to execute and inspect software QA work. A technical Operator can
follow a requirement from research and planning through implementation, testing
and independent review.

## Why it exists

A passing test, a proposed fix and an approval answer different questions.
QA Sentinel keeps those records separate, connects them to a Project-owned Task,
and makes the reasons for progression or a safe stop inspectable.

It coordinates test automation rather than replacing a CI runner or bug tracker.
Its structured agents are not a chatbot or an unrestricted autonomous coding
agent: models cannot directly write files, run shell commands or declare DONE.

## How it works

**Agents reason. Tools act. Evidence records reality. Orchestrator controls progression.**

The normal completed path is:

```text
CREATED → RESEARCHING → PLANNING → IMPLEMENTING → TESTING → REVIEWING → DONE
```

Failed product tests can enter ANALYZING and INVESTIGATING before a controlled
repair/retest. Gates and the accepted state machine own progression; Reviewer
APPROVE alone cannot set DONE. [State and role guide](docs/PRODUCT_GUIDE.md#workflow-states).

**External callers use Application Services, not orchestration internals or
persistence repositories directly.** The browser uses the API, which delegates
to the application boundary above the core. [Architecture](docs/ARCHITECTURE.md).

## Quick demo

In the protected Render preview, use the URL and access credentials supplied
privately by the owner. For local demo, start the host below. Then:

1. Open **Demo Calculator** (key `demo-calculator`).
2. Create a Task titled **Division support** with requirement
   **Add division support and reject division by zero.**
3. Open the Task and click **Run**. The fixed synthetic scenario reaches DONE.
4. Inspect Overview, Timeline, Artifacts, Invocations, Test Runs, Decisions and Gates.

**Demo evidence is deterministic and synthetic.** No live AI, source writes,
real pytest process, API key or external workflow network is involved. A different
requirement does not make the demo verify arbitrary software.
[Full walkthrough](docs/PRODUCT_GUIDE.md#demo-mode).

The UI has a Projects registry, Project Detail with owned Tasks, and a Task
console. Run/Resume sit above eight evidence sections, with expandable Artifact
JSON, status labels and explicit Refresh controls. This textual walkthrough
requires no screenshot assets.

## Core concepts

| Concept | Meaning |
| --- | --- |
| Project | Logical software identity; creation does not configure a workspace/runtime |
| Task | One QA requirement owned by exactly one Project |
| Run | Synchronous execution request until completion or a safe stop |
| Resume | Restores a BLOCKED Task's stored state; Run is separate |
| Evidence | Distinct Artifacts, Invocations, Test Runs, Errors, Decisions, Gates and Events |
| Workflow state | Persisted current Task snapshot, not an agent opinion |

## Local demo

From the repository root with Python 3.12+ and Node.js 22.12+:

```shell
python -m pip install -e ".[test]"
cd frontend
npm ci
npm run build
cd ..
qa-sentinel serve --demo
```

Open http://127.0.0.1:8000. Installation/build may download dependencies; demo
startup/execution need no external network. Local demo is loopback-only, has no
authentication, and keeps state in `~/.qa-sentinel/demo/state.sqlite3`. Installing
the package alone starts no server. [Hosting](docs/HOSTING.md).

## Public preview

The Render preview is a protected **deterministic synthetic demo only**, marked
**DEMO PREVIEW · Synthetic**. A temporary HTTP Basic gate protects UI/API; exact
GET /health is public. It has no product users/RBAC and cannot run real models,
repository reads, source mutation or real pytest. Other Projects remain
runtime-unconfigured. Preview SQLite may reset on restart/redeploy; do not enter
secrets or rely on durable records. The owner supplies the current generated
HTTPS URL privately; none is hard-coded here. [Deployment](docs/DEPLOYMENT.md).

## Real local mode

Real local mode executes against an explicitly configured **trusted local
workspace**, with an existing Project, matching ProjectWorkspaceBinding,
OpenAIModelAdapter/RealAgentRuntime, bounded repository reads, controlled
CREATE/MODIFY proposals and real pytest. OPENAI_API_KEY stays in the local
environment. This mode remains loopback-only. Prepared tests are trusted
executable code; policies are not an OS sandbox. Read the
[operator guide](docs/PRODUCT_GUIDE.md#real-local-mode) and
[configuration instructions](docs/HOSTING.md#real-local-mode) before running.

## Real Project onboarding

Create/select a logical Project in the same database through the UI/API, then stop
the host. Use `qa-sentinel local init` with explicit absolute database, frontend,
workspace paths, Project key and repeatable pytest targets to generate nonsecret
host configuration. `qa-sentinel local validate --config ...` checks existing
identity and accepted policies read-only, with no model calls, test execution or
source mutation. OPENAI_API_KEY stays in the local environment and is only
presence-checked. Start `serve --config ...`, inspect **Runtime readiness** on
Project Detail, then create a Task and Run. Project persistence never gains a
workspace path. [Exact commands and safe write semantics](docs/HOSTING.md#real-project-onboarding).

Preview remains deterministic synthetic demo only; only Demo Calculator has a
fake runtime. Readiness is a manual snapshot, and backend execution checks remain
authoritative. No automatic repository/test discovery or Project creation occurs.

## Documentation index

| Start here | Implementation reference |
| --- | --- |
| [PRD](docs/PRD.md) — purpose, journeys and boundaries | [Architecture](docs/ARCHITECTURE.md) |
| [Product Guide](docs/PRODUCT_GUIDE.md) — workflow and evidence walkthrough | [Runtime](docs/RUNTIME.md), [State machine](docs/STATE_MACHINE.md) |
| [Feature Reference](docs/FEATURES.md) — screens, ownership and limits | [Application](docs/APPLICATION.md), [API](docs/API.md) |
| [Frontend](docs/FRONTEND.md) — UI and development | [Projects](docs/PROJECTS.md), [Database](docs/DATABASE.md) |
| [Hosting](docs/HOSTING.md) — local configuration | [Models](docs/MODELS.md), [Execution](docs/EXECUTION.md) |
| [Deployment](docs/DEPLOYMENT.md) — protected Render demo | [Mutation](docs/MUTATION.md), [Repository evidence](docs/REPOSITORY_TOOLS.md) |
| [Phase 1](docs/PHASE_1.md) — status and historical checkpoints | [Reliability](docs/RELIABILITY.md), [Agent contracts](docs/AGENT_SPEC_v0.1.md) |

## Current limitations

Phase 1 uses SQLite, synchronous Run and a single-process host admitting one
Run/Resume at a time. There is no background queue, distributed worker system,
public multi-tenant SaaS, production auth/RBAC, remote clone or autonomous shell.
Evidence views are bounded prefixes with explicit truncation and manual freshness.
Unresolved calls, tests or writes need explicit reconciliation; Resume is not
automatic recovery. Hidden reasoning/raw provider responses are not stored or
displayed. [PRD limitations](docs/PRD.md#risks-and-limitations).

## Contributor onboarding and checks

Before changing workflow semantics, read PRD, Phase 1, Application, Runtime and
Projects. Before changing frontend, read Product Guide, Features and Frontend.
Before changing hosting/deployment, read Hosting and Deployment. The index above
links all of them. Historical task sections describe their checkpoint, not
additional current capabilities.

Run `python -m pytest`. In `frontend/`, run `npm ci`, `npm test -- --run` and
`npm run build`; then run `git diff --check` at the root. Tests use temporary
workspaces and mocked providers with no real API keys/costs. For frontend
development use `npm run dev`; Vite's local API proxy stays separate from the
full-stack host. See [Frontend](docs/FRONTEND.md).
