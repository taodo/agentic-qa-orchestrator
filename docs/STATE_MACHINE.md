# State machine and gates — Bootstrap Task 3

The pure state machine validates explicit TaskState values. WorkflowEngine owns
requested progression and its persistence. Gate evaluators inspect typed evidence
without changing state, persisting records, calling models, or executing commands.

## Canonical graph

| Current state | Allowed next states |
| --- | --- |
| CREATED | RESEARCHING, BLOCKED |
| RESEARCHING | PLANNING, BLOCKED; explicit same-state placeholder |
| PLANNING | IMPLEMENTING, RESEARCHING, BLOCKED |
| IMPLEMENTING | TESTING, PLANNING, FAILED; explicit same-state placeholder |
| TESTING | REVIEWING, ANALYZING |
| ANALYZING | INVESTIGATING, TESTING |
| INVESTIGATING | IMPLEMENTING, RESEARCHING, BLOCKED, FAILED; explicit same-state placeholder |
| REVIEWING | DONE, IMPLEMENTING, PLANNING, BLOCKED |
| BLOCKED | stored resume_state, FAILED |
| FAILED | none |
| DONE | none |

DONE and FAILED have no outgoing transitions, including same-state requests.
Same-state requests require allow_same_state=True and only work in RESEARCHING,
IMPLEMENTING, or INVESTIGATING. They record a transition but do not implement
retry budgets, change attempt/cycle counters, or escalate models.

Entering BLOCKED requires an explicit nonterminal resume_state other than BLOCKED.
The caller selects the state to return to; no prose is interpreted. Normal resume
must target exactly the stored resume_state, which is then cleared. BLOCKED can
also enter FAILED; this clears the obsolete resume target. Supplying a new resume
state on other transitions is rejected. Invalid requests write nothing.

## Gate rules

Every evaluator returns GateEvaluation with stable gate_name, structured checks,
PASS/FAIL/BLOCKED, and reasons for failed/blocked checks. There is no confidence
threshold in gates. Explicit BLOCKED statuses take precedence over failed checks.

| Gate | Deterministic rules |
| --- | --- |
| RESEARCH_GATE | PASS: research_complete and no blocking unknown; BLOCKED: blocking unknown; otherwise FAIL. |
| PLAN_GATE | READY plus steps/criteria present, unique IDs, valid dependencies, no self-dependency, and valid test strategy AC refs; NEEDS_RESEARCH is FAIL for implementation readiness; BLOCKED is BLOCKED. |
| IMPLEMENTATION_GATE | COMPLETED, all required step IDs completed, no missing/extra/duplicate results, no requires_replan deviation; BLOCKED is BLOCKED; otherwise FAIL. |
| TEST_GATE | COMPLETED + PASS is PASS; COMPLETED + FAIL/UNKNOWN or FAILED is FAIL; INCOMPLETE is BLOCKED. Run task identity must match. |
| ANALYSIS_GATE | PASS/no groups and FAIL/at least one group are sufficient (gate PASS); contradictions FAIL; explicit BLOCKED is BLOCKED. |
| INVESTIGATION_GATE | Identified root cause needs root_cause, evidence, action; insufficient evidence with a structured additional-evidence request is sufficient (PASS), otherwise BLOCKED; escalation recommended is FAIL for this attempt only. |
| REVIEW_GATE | APPROVE, every required AC present and COVERED with evidence, no HIGH/BLOCKER issues or test gaps; duplicate coverage fails; BLOCKED/NEEDS_EVIDENCE is BLOCKED; otherwise FAIL. |

Implementation and review evaluators take a caller-supplied approved plan; plan
approval/routing is not inferred from prose. The current implementation-step
result contract has no per-step justification or approval reference. Required
SKIPPED steps therefore fail: a free-form deviation cannot be deterministically
associated with a skipped step. No domain contract is expanded in Task 3.

PlanGate validates dependency references and direct self-dependencies; general
multi-step dependency cycle detection is deferred. Open questions, known issues,
commands, and investigation confidence do not drive hidden prose/threshold rules.
Gate PASS means sufficiency for that gate, not test success, review approval, or DONE.

## Gate/transition coupling

These forward edges require the named gate with PASS; omission cannot bypass it:

| Edge | Required gate |
| --- | --- |
| RESEARCHING -> PLANNING | RESEARCH_GATE |
| PLANNING -> IMPLEMENTING | PLAN_GATE |
| IMPLEMENTING -> TESTING | IMPLEMENTATION_GATE |
| TESTING -> REVIEWING | TEST_GATE |
| REVIEWING -> DONE | REVIEW_GATE |

Other whitelisted routes and same-state placeholders do not mandate a PASS gate.
If supplied, a gate must match the current stage and task, have structured checks,
and have only PASS checks when its aggregate is PASS. Relevant non-PASS gates
are persisted too, e.g. PlanGate FAIL for NEEDS_RESEARCH or TestGate FAIL for
TESTING -> ANALYZING. A supplied PASS TestGate cannot route to failure analysis.
The caller requests the route; no automatic route selection/retry policy is added.

GateEvaluation is accepted from trusted deterministic orchestration code. This
is not an authorization or provenance-signing boundary. Supplied invocation,
artifact, and test-run references must exist and belong to the task. If a persisted
TestRun is supplied, REVIEWING/DONE require completed execution with PASS; passing
test evidence also rejects failure-analysis routing. No model assessment overrides
that evidence. Gate computation is never placed in repositories.

## Atomic persistence and time

WorkflowEngine.transition loads the task in a fresh UnitOfWork, validates the
request, then inserts an optional gate, DecisionRecord (TRANSITION, source
ORCHESTRATOR), Transition, updated Task snapshot, and STATE_TRANSITIONED Event
before one explicit commit. Any exception, flush failure, or commit failure rolls
back the whole operation. No automatic ErrorRecord policy is implemented.

The transition links decision_id and optional gate_evaluation_id. Decision
reason_code/trigger are explicit nonblank machine-readable strings supplied by
the caller; reason_details is concise caller-provided explanation. Decision
evidence_refs include supplied refs and gate/entity IDs. Event actor is
ORCHESTRATOR/qa-sentinel; correlation includes decision_id and supplied invocation,
artifact, and test-run IDs. Existing CorrelationRef has no gate-ID field; the gate
is linked through the decision/transition. Event payload contains from_state,
to_state, and reason_code. Artifacts are never updated by the engine.

Generated timestamps are timezone-aware UTC. updated_at changes on success;
entering DONE/FAILED sets completed_at. created_at is preserved. Clock timestamps
may tie and are not a sequence number; repository lists retain their existing
ID-based ordering. Full durable ordering/idempotent runtime is outside Task 3.

State is the current mutable snapshot. An event records what happened. A decision
records the explicit material choice and evidence refs. A gate records deterministic
checks. An artifact records structured work/evidence. A transition links a state
change to its decision and gate. These records remain distinct; reviewer APPROVE
alone cannot set DONE.

## Verification

Tests exercise the entire graph, gates, blocked/resume, terminal protection,
forward-gate rejection, and rollback after all writes including a commit-time FK
failure. Real Alembic-migrated SQLite integration tests persist the complete path
CREATED -> RESEARCHING -> PLANNING -> IMPLEMENTING -> TESTING -> REVIEWING -> DONE
and the repair loop IMPLEMENTING -> TESTING -> ANALYZING -> INVESTIGATING -> IMPLEMENTING.
The complete path is verified after reopening the database.

No retry/escalation policy, agent/model runtime, permission engine, execution
service, CLI, API, UI, or Task 4 functionality is implemented.
