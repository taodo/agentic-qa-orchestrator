# Deterministic reliability — Bootstrap Task 4

`orchestration/reliability_policy.py` contains pure structured policies.
`orchestration/reliability.py` provides explicit UnitOfWork-backed audit operations.
Neither executes retries, agents, models, tools, commands, or workflow loops.
WorkflowEngine remains the state-transition entry point. Gates contain no escalation
thresholds. No schema migration or WorkflowEngine modification is needed.

## Dispositions and retry domains

| Disposition | Same-operation retry |
| --- | --- |
| TRANSIENT | Allowed within budget, including identical input. |
| CORRECTABLE | Allowed within budget only with changed_input=True. |
| STRUCTURAL | Denied; caller selects research/replan/block routing. |
| TERMINAL | FAIL recommendation stops automatic recovery for the operation. |

No payload comparison or prose classification occurs. The caller supplies whether
relevant input, implementation, or evidence changed. Every domain defaults to two
scheduled retries: SCHEMA_VALIDATION, RESEARCH, PLANNING, IMPLEMENTATION,
TEST_EXECUTION, INVESTIGATION, REVIEW.

Budgets exclude the initial operation. RetryRequest.current_attempt means retries
already consumed, starting at zero; max_attempts means the retry allowance.
Consumed=1 allows the second retry, consumed=2 denies it. Exhaustion recommends
BLOCK. Domains are independent per task. Denied retries consume no allowance.

The service derives consumption from committed RETRY_SCHEDULED events, surviving
service recreation/database reopening. Scheduling reserves budget without executing
anything. Task implementation_attempt/review_cycle describe future runtime operations
and are not changed by reservations. BLOCKED tasks must resume through WorkflowEngine
before scheduling retry; terminal tasks reject recovery.

## Configuration, error mapping, and defect cycles

ReliabilityConfig is frozen with a copied, read-only retry mapping. It lives in memory,
without a configuration framework or persisted settings. Configurable defaults:

| Setting | Default |
| --- | --- |
| Each retry domain | 2 |
| max_defect_cycles | 3 |
| identical_failure_threshold | 3 |
| investigator_escalation_limit | 1 |
| investigator_low_confidence | 0.65 |
| investigator_repeat_confidence | 0.80 |
| investigator_repeat_attempt | 2 |
| investigator_hypothesis_threshold | 3 |
| investigator_defect_cycle_threshold | 2 |
| investigator_primary_model | Luna Max |
| investigator_escalated_model | Sol High |

ErrorType defaults: AGENT_ERROR -> STRUCTURAL (explicit disposition context supported),
SCHEMA_ERROR -> CORRECTABLE, TOOL_ERROR -> CORRECTABLE (TRANSIENT subtype supported),
TEST_FAILURE -> CORRECTABLE (STRUCTURAL subtype supported; TRANSIENT rejected),
ENVIRONMENT_ERROR -> TRANSIENT, POLICY_VIOLATION -> TERMINAL, WORKFLOW_ERROR and
EXTERNAL_BLOCKER -> STRUCTURAL. ErrorRecord messages/retryable flags do not drive
classification. External blocking uses its separate structured blocker reason.

`can_start_another_defect_cycle(task)` allows task.defect_cycle < max_defect_cycles.
This pure check never increments a counter. Task 4 implements no defect loop or
cycle increment operation.

## Fingerprints and circuit breaker

FailureIdentity contains test_name, error_class, component, normalized_signature.
The caller supplies already-normalized fields; boundary whitespace is stripped.
Sorted, field-delimited canonical JSON is hashed with SHA-256. No raw logs or
stack-trace parsing are used.

Matching is scoped to task and digest. The first occurrence inserts the existing
FailureFingerprint record; later occurrences use repository.update_occurrence.
first_seen_at and identity stay unchanged; last_seen_at updates in UTC. The original
test_run_id identifies the first occurrence; later circuit events reference the
currently supplied run. Existing same-task test-run evidence is required. Ambiguous
duplicate stored digests are rejected rather than selecting an arbitrary record.

Occurrences 1 and 2 do not trip; 3 and above stop same-path retry. The recommendation
is BLOCK, or ESCALATE when caller context permits it, the task is INVESTIGATING,
and Investigator's durable escalation budget remains. A circuit recommendation
invokes no model and consumes no escalation reservation itself.

Supply the relevant FailureIdentity to `retry` to record occurrence, detect circuit
breaking, and deny the retry atomically. `record_failure` also supports occurrence/
circuit recording without retry evaluation. Every submitted call represents an
occurrence; this API does not deduplicate runtime delivery or hash arbitrary payloads.

## Investigator escalation

Provider-neutral labels default to **Luna Max -> Sol High**. At least one configured
rule triggers escalation while budget remains:

- confidence < 0.65;
- attempt >= 2 and confidence < 0.80;
- alternative hypotheses >= 3;
- evidence_conflict=True;
- defect_cycle >= 2.

Output includes all triggered reason codes, model labels, consumed/max escalations,
and evidence references. Service inputs use persisted Task.defect_cycle and committed
MODEL_ESCALATED events as authoritative counts, preventing caller budget reset.
By default one route reservation is allowed. Denied evaluations create decisions but
no MODEL_ESCALATED event. No other role has a model escalation policy.
InvestigationGate remains independent: sufficient evidence may PASS at low confidence.

## Blocking, decisions, and events

BlockerReason supports MISSING_CREDENTIAL, REQUIREMENT_AMBIGUITY, SECURITY_DECISION,
DESTRUCTIVE_CHANGE_APPROVAL, EXTERNAL_DEPENDENCY, ARCHITECTURE_APPROVAL,
RECOVERY_BUDGET_EXHAUSTED. Each recommends BLOCKED with a caller-supplied active,
nonterminal resume_state. Actual transition/resume uses WorkflowEngine's rules.

Material evaluations append DecisionRecord with existing RETRY, ESCALATE_MODEL,
BLOCK, FAIL types, stable reason_code, concise reason_details, and supplied evidence
refs. A denied retry may use RETRY with a denial reason; a denied escalation uses
ESCALATE_MODEL with a denial reason. Decision type identifies the evaluated choice,
rather than proving execution.

Events: RETRY_SCHEDULED, RETRY_EXHAUSTED, MODEL_ESCALATED,
CIRCUIT_BREAKER_TRIPPED, TASK_BLOCKED. ActorRef is ORCHESTRATOR/qa-sentinel.
Event payloads explicitly mark recommendation_only=True: TASK_BLOCKED records a
blocking recommendation, and MODEL_ESCALATED a model route reservation. Neither
proves a state change or model call. STATE_TRANSITIONED remains actual state evidence.
Events link the generated decision and available invocation/artifact/test-run IDs;
correlated entities must exist and belong to the task. Caller evidence references
must be bounded and sanitized; general secret detection is not implemented here.

Every service operation commits fingerprint changes and applicable audit records
together. Failures roll back records and event-derived budget reservations. Accepted
artifacts and historical records are never updated. The existing SQLite/UoW boundary
is retained; concurrent worker reservation and durable execution idempotency remain
future runtime work.

## Verification and unimplemented scope

Unit tests cover retry rules, immutable configuration, invalid inputs, fingerprints,
boundaries, defect budgets, error mapping, blockers, and gate independence. Tests on
Alembic-migrated SQLite cover transient retry, durable independent budgets, three
matching failures, Investigator escalation, WorkflowEngine blocked/resume, cross-task
rejection, and injected audit/commit failures with rollback of all intended writes.

Unimplemented: agents/model clients, fake-agent vertical slice (Task 5), commands,
test runner, autonomous loops, CLI/API/UI, background workers, runtime attempt/cycle
increments, and full execution idempotency.
