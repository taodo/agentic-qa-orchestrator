# QA Sentinel feature reference

Implemented Tasks 1–17; Task 18 adds static product onboarding, and Task 19 adds
explicit trusted local setup and safe host readiness.
[Product Guide](PRODUCT_GUIDE.md) provides interpretation/walkthrough;
[PRD](PRD.md) explains boundaries. Backend ownership below identifies existing
layers, not new endpoints or services.

| Feature | Purpose | Where | Backend ownership | Operator action | Expected evidence | Current limitations |
| --- | --- | --- | --- | --- | --- | --- |
| Project | Logical software identity/Task owner | Projects / Project Detail | Application Project commands/queries; persistence | Create/open | ID, immutable key, metadata, scoped Tasks | No workspace/runtime provisioning or delete UI/API |
| Task | One Project-owned requirement | Project Detail / Task console | Application Task command/query; core Task | Create/open | Requirement, state, counters/times | Creation does not execute; owner immutable |
| Run | Execute configured workflow | Task Execution | Application run_task → WorkflowRunner/WorkflowEngine; host admission | Run once, wait | Durable state/evidence before completion/stop | Synchronous; no queue/implicit resume; terminal check not rerun |
| Resume | Restore BLOCKED to stored state | Task Execution when target exists | Application resume_task → WorkflowEngine | Resolve blocker; Resume, then Run | Transition, Decision, Event | No execution, budget reset, reconciliation or terminal restart |
| State badge | Show current workflow state | Project Tasks / Task header | Backend Task snapshot | Read exact label | Canonical TaskState | Not Invocation status or quality score |
| Overview | Inspect Task snapshot | Default Task section | Application TaskDetail query | Read / Refresh | Requirement, ownership, times, counters, resume/current Invocation, terminal reason | Snapshot alone does not explain every stop |
| Timeline | Follow persisted Events | Timeline | Application Event-ledger projection | Open / Refresh | API-ordered actors/times/details/correlation refs | Bounded prefix/timestamp ties; no merged cross-table chronology |
| Artifacts | Inspect structured evidence/output | Artifacts | Application Artifact query; core producers | Open, Expand/Collapse JSON, Refresh | Type, producer, schema, Invocation/supersession refs, approved content | Stored need not mean accepted; no raw provider/hidden reasoning |
| Invocations | Inspect attempts/provenance | Invocations | Application query; AgentExecutor | Open / Refresh | Role, model, effort, attempt, status, times, Error ID | STARTED may be unresolved; COMPLETED not Task success |
| Test Runs | Separate execution from conclusion | Test Runs | Application query; deterministic provider/TestExecutionService | Read status/outcome/counts/refs | COMPLETED/INCOMPLETE/FAILED; PASS/FAIL/UNKNOWN; environment | Synthetic demo; no raw stdout/stderr; counts may be unreliable |
| Errors | Inspect classified failure evidence | Errors | Application query; runtime/reliability producers | Read with related records | Type, owner, severity, fixed message, flags/refs | HTTP feedback need not produce a stored Error; flags not retry instructions |
| Decisions | Explain routing/recovery | Decisions | Application query; orchestration/reliability | Read reason/refs; verify action | Type, source, reason codes/details, evidence refs | Evaluations/reservations can be denied or unexecuted |
| Gates | Inspect deterministic checks | Gates | Application query; evaluators/WorkflowEngine | Inspect results/checks/reasons | Seven named gates, PASS/FAIL/BLOCKED | PASS gate-specific; model APPROVE cannot set DONE |
| Demo runtime | Learn fixed calculator workflow | Demo Calculator; local demo/preview | Host demo_bundle; FakeAgentRuntime/FakeTestResultProvider | Create Division support, Run | Synthetic RESEARCH/PLAN/IMPLEMENTATION/REVIEW and Test Run | Fixed; no live AI/writes/real pytest; other Projects unconfigured |
| Real local runtime | Execute bounded QA on prepared trusted target | Same local UI | Explicit resolver/bundle/binding; real roles/deterministic services | Configure existing Project locally, Run | Repository evidence, proposals/applied facts, real Test Runs/review | Loopback-only, local key, trusted tests, exclusive access/reconciliation |
| Preview access gate | Protect public synthetic demo | Browser Basic challenge; UI/API | Host PreviewAccess | Authenticate with privately supplied credentials | Generic 401 until authorized | Temporary shared gate, no users/RBAC; credentials never stored/logged/returned |
| Host /health | Minimal provider health check | Exact GET /health | API process-health handler; preview exemption | Owner checks endpoint | {"status":"ok"} | Not DB/workspace/model readiness or workflow success |
| Local full-stack host | Serve built SPA/API on one origin | qa-sentinel serve | Host → API → Application → core | Build, select demo/trusted real config | Seeded/configured Project; persisted evidence | Local loopback/no auth, one process/worker; no dev-server startup |
| Protected Render preview | Expose synthetic UI behind gate | Owner-provided HTTPS URL | Existing image/Blueprint/preview host | Open; owner manages deployment/access | Synthetic evidence and frontend notice | Ephemeral SQLite; no public real runtime or production auth |
| Product onboarding | Explain Project/Task/Run/inspection | Projects intro/inline help | Static frontend only | Expand/collapse How QA Sentinel works | Product explanation/canonical demo input | No framework, analytics, storage or extra network |

## Evidence vocabulary

State = current truth; Event = something happened; Artifact = evidence/output;
Decision = why routing happened; Gate = deterministic acceptance check;
Invocation = agent execution record; Test Run = deterministic test execution
record (synthetic in demo); Error = classified failure evidence. These are
separate types. [Interpretation/refs](PRODUCT_GUIDE.md#mental-model).

## Real Project onboarding

| Feature | Purpose | Ownership | Operator action | Limits |
| --- | --- | --- | --- | --- |
| local init | Generate one nonsecret host JSON binding | Trusted host CLI; existing Project identity read | Supply explicit paths/key/targets/output | No Project creation, discovery, key storage or execution; explicit overwrite replaces entire valid config |
| local validate | Report prerequisites safely | Shared HostConfig/service/CommandPolicy checks; read-only existing DB | Validate selected config; set environment key and revalidate | Zero provider/test/mutation actions; key presence only; no migrations; snapshot not Run guarantee |
| Runtime readiness | Explain configured vs unconfigured | Host-only /host/runtime-status/{project_id}, outside API v1 | Inspect Project Detail / Refresh runtime | No paths/secrets; no polling or frontend Run gate; demo/preview synthetic only |

Project identity remains persisted; workspace/runtime remains host-owned. Local
mode requires a prepared trusted workspace, loopback bind and existing Project
in the selected database. [Exact flow](HOSTING.md#real-project-onboarding),
[operator interpretation](PRODUCT_GUIDE.md#real-project-onboarding). Public preview
only configures Demo Calculator's fake runtime; arbitrary Projects stay unconfigured.

## Implementation references

- [States/roles](PRODUCT_GUIDE.md#workflow-states), [exact graph/gates](STATE_MACHINE.md).
- [Application](APPLICATION.md), [API](API.md), [Projects](PROJECTS.md).
- [Frontend](FRONTEND.md), [Hosting](HOSTING.md), [Deployment](DEPLOYMENT.md).
- [Runtime](RUNTIME.md), [Models](MODELS.md), [Reliability](RELIABILITY.md).
- [Repository reads](REPOSITORY_TOOLS.md), [Mutation](MUTATION.md), [Execution](EXECUTION.md).

Collections are bounded prefixes with honest truncation. No load-all, search,
generated OpenAPI client, background queue or product auth is implied.
