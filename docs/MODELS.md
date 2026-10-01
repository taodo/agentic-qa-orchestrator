# Real model boundary — Bootstrap Task 7

Agents reason over supplied context. Model adapters do not receive persistence,
workflow state, commands, tools, or mutable Task objects. Deterministic gates and
WorkflowEngine remain authoritative. Only Researcher and Planner become real.

## Contracts and provider boundary

`models/base.py` defines frozen ModelSettings, ModelRequest, ModelResponse,
ModelMetadata, the ModelAdapter protocol, and sanitized ModelError categories.
OpenAI SDK objects remain inside `models/openai_adapter.py`. A response contains
only a revalidated Pydantic output and allowlisted scalar metadata; raw responses,
requests, exception messages, refusal text, and hidden reasoning are not persisted.

The official SDK's `client.responses.parse(text_format=...)` requests native strict
structured output. Both adapter and runtime revalidate the existing ResearchOutput
or PlannerOutput contract, and AgentExecutor validates again before persistence.
No free-form prose extraction or hidden repair call is implemented. Refusals,
incomplete results, and schema errors cannot become accepted artifacts.

Interfaces were checked against SDK 2.54.0 and the official
[structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs).
The sole new direct dependency is `openai>=2.54,<3`; its SDK-required transitive
packages are installed normally. No agent, workflow, prompt, or retry framework is added.

## Role configuration and routing

RoleModelConfig contains only two roles:

| Role | Default model | Reasoning effort |
| --- | --- | --- |
| RESEARCHER | gpt-5.6-luna | medium |
| PLANNER | gpt-5.6-sol | high |

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
fake = FakeAgentRuntime(scenario)
runtime = CompositeAgentRuntime({
    role: real if role in {AgentName.RESEARCHER, AgentName.PLANNER} else fake
    for role in AgentName
})
```

Implementer, Test Analyzer, Investigator, and Reviewer remain fake. Model calls
never modify prepared workspace code; Task 6's deterministic pytest execution is
configured independently. AgentRuntime.run retains fake typed outputs and also
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

Serialized input is limited to 60000 characters and instructions to 8192. Oversize
input raises CONTEXT_LIMIT without a provider request. Data is not silently
truncated. Character bounds are deterministic rather than tokenizer estimates.

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

## Offline tests and optional smoke

Normal pytest strips OPENAI_API_KEY and forbids live synchronous HTTP transport.
Provider tests use the actual official SDK with httpx.MockTransport (already an
SDK dependency), deterministic responses, and synthetic credentials. Tests inspect
strict schemas, no-tools/stateless request options, typed errors, sanitized persistence,
retry budgets, schema correction, transaction rollback, and reopened provenance.
The hybrid integration executes prepared calculator tests through real local pytest
and reaches DONE using existing gates. No real API calls or API costs are involved.

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

Remaining scope: real later roles, tools, model fallback/escalation activation,
provider memory, workers, UI, rate-limit scheduling, and Task 8 are not implemented.
