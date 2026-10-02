# Real model boundary — Bootstrap Tasks 7–10

Agents reason over supplied context. Model adapters do not receive persistence,
workflow state, commands, tools, or mutable Task objects. Deterministic gates and
WorkflowEngine remain authoritative. Researcher, Planner, Test Analyzer,
Investigator, Reviewer and Implementer are real reasoning roles. Implementer returns
a structured proposal; deterministic code alone reads and applies target files.

## Contracts and provider boundary

`models/base.py` defines frozen ModelSettings, ModelRequest, ModelResponse,
ModelMetadata, the ModelAdapter protocol, and sanitized ModelError categories.
OpenAI SDK objects remain inside `models/openai_adapter.py`. A response contains
only a revalidated Pydantic output and allowlisted scalar metadata; raw responses,
requests, exception messages, refusal text, and hidden reasoning are not persisted.

The official SDK's `client.responses.parse(text_format=...)` requests native strict
structured output. Both adapter and runtime revalidate the existing ResearchOutput
or PlannerOutput contract in Task 7, extended to TestAnalysisOutput,
InvestigationOutput and ReviewOutput in Task 8, and ImplementationProposal in
Task 9. AgentExecutor validates again before persistence.
No free-form prose extraction or hidden repair call is implemented. Refusals,
incomplete results, and schema errors cannot become accepted artifacts.

Interfaces were checked against SDK 2.54.0 and the official
[structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs).
The sole new direct dependency is `openai>=2.54,<3`; its SDK-required transitive
packages are installed normally. No agent, workflow, prompt, or retry framework is added.

## Role configuration and routing

RoleModelConfig contains six real roles and an explicit Investigator escalation setting:

| Role | Default model | Reasoning effort |
| --- | --- | --- |
| RESEARCHER | gpt-5.6-luna | medium |
| PLANNER | gpt-5.6-sol | high |
| IMPLEMENTER | gpt-5.6-luna | high |
| TEST_ANALYZER | gpt-5.6-luna | medium |
| INVESTIGATOR primary | gpt-5.6-luna | high |
| INVESTIGATOR escalated | gpt-5.6-sol | high |
| REVIEWER | gpt-5.6-sol | high |

These defaults were checked against official
[Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna) and
[Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol) model pages.
Model IDs and reasoning effort are immutable configuration values, not runner logic.
For another supported model, replace ModelSettings; use reasoning_effort=None to
omit the parameter for models that do not support it. Unsupported model/effort
combinations surface INVALID_REQUEST; there is no hidden model fallback.
Account access is not established by offline tests.

Default request timeout is 120 seconds (positive, finite, at most 600); the SDK
uses HTTP timeouts rather than a separate process-wide wall-clock watchdog.
Output is capped at 8192 tokens by default, configurable from 256 to 32768.
Reasoning can consume that allowance; an incomplete response fails safely.

RealAgentRuntime rejects unsupported roles. CompositeAgentRuntime explicitly maps
roles to runtimes without modifying WorkflowRunner's role routing:

```python
real = RealAgentRuntime(OpenAIModelAdapter(), RoleModelConfig())
runtime = CompositeAgentRuntime({
    role: real
    for role in AgentName
})
```

Pass a separately configured MutationService to WorkflowRunner for controlled real
implementation, alongside Task 6's independently configured pytest provider. Explicit
composite mappings may retain fake Implementer. Model calls never write files;
see MUTATION.md for authorization, application, rollback and reconciliation.
AgentRuntime.run retains fake typed outputs and also
accepts a provider-neutral ModelResponse envelope for real invocation metadata.

## Prompts and bounded context

`agents/prompts.py` owns version-controlled deterministic prompt builders.
Researcher instructions require FACT/INFERENCE/UNKNOWN distinctions, supplied
evidence, dependencies, constraints, risks, and blocking unknowns. Planner
instructions require stable step/AC IDs, explicit dependencies, test traceability,
and honest NEEDS_RESEARCH/BLOCKED results.

Selected context is serialized as sorted compact JSON in a user-role message;
policy instructions are separate. Researcher receives requirement, intentionally
supplied repository_evidence, and optional prior research reference. The runner
does not automatically read repository files or expand referenced artifacts for
Researcher. Callers can explicitly construct ResearchContext with bounded evidence.
Planner receives requirement, selected accepted ResearchOutput fields, and its
artifact reference. No task snapshot, database history, full logs, environment,
or configuration credentials are included. References are not model tools.

Task 8 adds selected typed serializers. Test Analyzer receives conclusive failing
TestRun counts/status/outcome/report reference, accepted implementation fields,
and relevant evidence references. It classifies related failures using the existing
taxonomy; its prompt forbids RCA and code-change recommendations. Investigator
receives that evidence plus accepted analysis, artifact references, defect cycle,
and a structured evidence-conflict signal. It performs RCA and reports uncertainty,
alternatives, and one action enum; it does not execute repair. Reviewer receives
requirement, accepted plan including required ACs, accepted implementation, and
latest conclusive deterministic test evidence. It evaluates coverage independently;
APPROVE remains a recommendation to ReviewGate, never DONE.

Implementation command records, test environment labels, timestamps, provider
metadata, and stdout/stderr are excluded from these prompts. Counts and references
do not automatically expose underlying logs or source. Models must report insufficient
evidence when supplied context cannot justify a diagnosis. Review context uses its
core typed evidence; optional analysis/investigation is not needed in this slice.

Serialized input is limited to 60000 characters and instructions to 8192. Oversize
input raises CONTEXT_LIMIT without a provider request. Data is not silently
truncated. Character bounds are deterministic rather than tokenizer estimates.

Task 9 Implementer context contains accepted plan, explicitly authorized path sets,
fresh typed source snapshots with exact UTF-8/SHA-256/byte size, previous implementation
reference, selected investigation and relevant refs. Source is untrusted user-role
data, never system instructions. MutationConfig adds explicit byte/file/write bounds;
the existing model character/token ceilings can reject earlier. The prompt forbids
DELETE, diffs, unrelated rewrites and claims of applied changes/test/command execution.
Caller-selected source must exclude secrets; arbitrary source is not secretly scanned.

Requirement/research text is untrusted data, not policy authority. Instructions
forbid invented tool use, source modification, approvals, and workflow decisions.
Instruction separation does not guarantee output quality; typed contracts and
deterministic gates constrain acceptance. There is no regex injection filter.

## Stateless calls, tools, and secrets

Every call has `tools=[]`, `tool_choice="none"`, and `store=False`. No conversation,
previous_response_id, provider thread, remote prompt, or model memory is used.
There is no MCP, function calling, search, browser, filesystem, shell, or database
access for the models. QA Sentinel persistence remains the workflow source of truth.

Credentials are read lazily from local OPENAI_API_KEY only when a real client is
needed. Missing/blank credentials raise CONFIGURATION; fake mode is never chosen
silently. Credentials are never fields of requests, configuration, contexts,
artifacts, events, or errors. The official endpoint is pinned; OPENAI_BASE_URL
cannot redirect credentials. SDK exception text and request/authorization objects
are discarded. The SDK necessarily holds the credential in its live client memory.
Caller-supplied requirement/evidence/configuration must be secret-free; arbitrary
user text is not a credential-detection system. Production does not log prompts or
provider objects. There is no SDK debug logging enabled by QA Sentinel.

## Error taxonomy and retry ownership

| Category | ErrorType | Disposition / action |
| --- | --- | --- |
| CONFIGURATION, AUTHENTICATION | EXTERNAL_BLOCKER | STRUCTURAL; MISSING_CREDENTIAL blocker |
| RATE_LIMIT, TIMEOUT, CONNECTION, SERVER_ERROR | AGENT_ERROR | TRANSIENT; role budget |
| INVALID_REQUEST | AGENT_ERROR | STRUCTURAL; stop |
| CONTENT_REFUSAL | AGENT_ERROR | STRUCTURAL; SECURITY_DECISION blocker |
| MALFORMED_RESPONSE | SCHEMA_ERROR | CORRECTABLE; explicit changed input required |
| INCOMPLETE_RESPONSE | AGENT_ERROR | STRUCTURAL; explicit configuration resolution |
| CONTEXT_LIMIT, UNSUPPORTED_ROLE, UNKNOWN_PROVIDER_ERROR | AGENT_ERROR | STRUCTURAL; stop |

Classification uses typed SDK exceptions and HTTP status, never message substrings.
Errors contain fixed `MODEL_*` reason codes. Failed calls produce FAILED/BLOCKED
invocations and concise ErrorRecord values without malformed payloads/refusal text.
No cost estimates or speculative billing schema is introduced.

SDK retries are disabled (`max_retries=0`), including for injected official SDK
clients. Narrow injected non-SDK clients are trusted deterministic test doubles.
The adapter never sleeps, schedules retries, or calls a repair prompt. Application
retries are separate invocations reserved by ReliabilityService. Rate limits use
the existing role budget, default two retries beyond the initial call.

For schema failures, RealAgentRuntime offers **one deterministic correction per
role/task**. The failure records schema_correction_planned=True. If ReliabilityService
reserves a SCHEMA_VALIDATION retry, WorkflowRunner reconstructs schema_correction=True
from correlated committed events on the next context, including after reopening.
The prompt gains explicit required-field/type/enum/nonblank/range instructions;
original context data is preserved and malformed content is never fed back.
This planned instruction change is the evidence for changed_input=True. Repeated
malformation with that correction already present supplies changed_input=False
and stops under the unchanged Task 4 rule. Fake scenarios retain their existing
explicit changed-input semantics. Merely receiving another response is never
claimed as changed input.

## Explicit Investigator escalation — Task 8

The routed runtime exposes configured primary/escalated Investigator model IDs
through a provider-neutral capability. WorkflowRunner aligns ReliabilityConfig's
model labels with those IDs while preserving all configured thresholds and budgets.
All-fake runtimes retain their behavior without activating model escalation.

After a primary Investigator completes, WorkflowRunner supplies confidence,
persisted role attempt, alternative-hypothesis count, authoritative defect cycle,
and an explicitly supplied evidence-conflict boolean to the existing
ReliabilityService.investigator_escalation operation. No threshold is duplicated.
The model's ESCALATION_RECOMMENDED status alone is not an escalation trigger.

If permitted, the service commits its existing decision and MODEL_ESCALATED event,
correlated with the primary invocation/artifact and failing TestRun. The next runner
step reconstructs an escalated context from that reservation: original bounded
evidence, primary InvestigationOutput/reference, decision/reference, and reason codes.
Evidence conflict is reconstructed from durable reason codes. A separate
AgentExecutor invocation uses the configured escalated model, with its own attempt,
timestamps, usage, and immutable Investigation artifact. Started/completed lifecycle
events link escalation_decision_id. No adapter retry, hidden fallback, recursive
prompt, or hidden repair call occurs.

The **selected routing candidate** is the primary result when no escalation is
reserved, otherwise the successful escalated result. Only this candidate passes
through InvestigationGate and enum routing. Both artifacts remain queryable;
neither is overwritten. Selected CODE_FIX/TEST_FIX routes to the configured Implementer
with the unchanged gate and defect-cycle checks. MORE_RESEARCH routes to RESEARCHING;
HUMAN_ACTION blocks with resume_state=INVESTIGATING.

Reservations survive runner recreation/database reopening and consume the Task 4
budget. A completed escalated candidate is not recursively escalated. Later primary
investigations with an active trigger and exhausted budget stop/block; no-trigger
results may still route under the existing gate. Transient/schema failure on an
escalated call uses existing retry domains and stays on the escalated route. It never
falls back to primary. Unresolved STARTED calls require explicit reconciliation.

Configuration is trusted and must remain consistent across resume; changing the
target model against a committed reservation is rejected explicitly. The optional
WorkflowRunner.investigation_evidence_conflict is a boolean supplied by trusted
context selection for the single-task run, never inferred from model prose.
Primary no-escalation decisions are reused after interrupted routing without
reserving another escalation. All retry, circuit, defect-cycle, and step bounds remain.

## Persistence and provenance

AgentExecutor's existing lifecycle is retained: commit STARTED, run without a DB
transaction, validate output, then atomically commit Artifact, COMPLETED invocation,
and AGENT_COMPLETED event. Failure atomically stores ErrorRecord, terminal invocation
status, and lifecycle event. Persistence failures propagate with STARTED durable,
requiring explicit reconciliation before another provider call.

Invocation fields store configured model, reasoning effort, attempt, start/finish,
status, and error linkage. Artifacts use actual configured producer_agent,
producer_model, and invocation_id. Provider-reported model, bounded response ID,
input/output/total tokens where available, status, and latency are stored in the
correlated AGENT_COMPLETED event's model_metadata. Missing usage remains null.
There is no schema migration: existing event JSON represents this metadata.
No raw provider response or reasoning text is stored. Gate PASS still determines
artifact acceptance and progression; COMPLETED only means contract-valid output.
For real Implementer, COMPLETED additionally requires policy validation and successful
deterministic application. Proposal and source manifest are reserved before writes;
completion stores canonical applied facts separately. Unresolved successful writes
require explicit reconciliation, not another model call. See MUTATION.md.

## Offline tests and optional smoke

Normal pytest strips OPENAI_API_KEY and forbids live synchronous HTTP transport.
Provider tests use the actual official SDK with httpx.MockTransport (already an
SDK dependency), deterministic responses, and synthetic credentials. Tests inspect
strict schemas, no-tools/stateless request options, typed errors, sanitized persistence,
retry budgets, schema correction, transaction rollback, and reopened provenance.
The hybrid integration executes prepared calculator tests through real local pytest
and reaches DONE using existing gates. Task 8 also verifies FAIL -> real classification
-> real RCA -> fake Implementer -> real pytest PASS -> real Reviewer -> gate-controlled
DONE. A dedicated test harness switches the prepared calculator from failing integer
division to passing division before retest. This is synthetic fixture control outside
all agents; fake Implementer does not write source. Tests cover separate escalation
invocations, durable budgets, immutable artifacts, insufficient review coverage,
request-changes retesting, human action, refusals, malformed output, retry exhaustion,
and reservation/completion rollback. No real API calls or API costs are involved.

Install the project and test dependencies, then run `python -m pytest` as usual.
The optional script is outside pytest discovery:

```shell
python scripts/smoke_openai_researcher.py --run
```

Run it explicitly with OPENAI_API_KEY supplied through the developer's local
environment; never paste it into chat. `--model` overrides the default. Without
`--run` or credentials it makes no request. It performs one small Researcher call
with low effort, 2048 output tokens, and a 60-second HTTP timeout, prints only
high-level success/usage or a sanitized failure code, and persists nothing.
This optional paid smoke is not part of CI and was not run during Task 7.

Task 9 adds actual proposal-driven mutation and real fail/repair/retest integration,
with fresh hashes, rollback, immutable proposal/canonical evidence and restart stops.
No fixture changes source to perform repair. Normal tests remain zero-network; no
paid smoke was run and no Task 9 dependency was added. Provider-side tools, provider
memory, workers, UI and rate-limit scheduling remain outside this implementation.

## Task 10 repository turns

Researcher and Planner optionally return ResearchTurn/PlannerTurn through native
structured output. TOOL_REQUEST contains a typed read-only repository request;
FINAL_OUTPUT contains the unchanged ResearchOutput/PlannerOutput. RealAgentRuntime
enables this explicitly with repository_tools=True. Composite routing delegates
capability by role. Implementer still uses Task 9 source snapshots, while Reviewer,
Analyzer and Investigator retain supplied context without repository tools.

The unchanged Responses adapter still sends tools=[], tool_choice="none" and
store=False with SDK retries disabled. ControlledRepositoryExecution owns each
explicit call, bounded deterministic reads, ordered evidence and durable model-turn
metadata. Existing schema correction and ReliabilityService retain retry ownership.
Repository text stays in bounded user context, never system policy. There is no
provider function calling, filesystem capability or hidden provider memory.
See REPOSITORY_TOOLS.md for limits, evidence accounting and reconciliation rules.
