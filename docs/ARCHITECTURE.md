# Architecture

Agents reason. Tools act. Evidence records reality.
The Orchestrator controls progression.

The deterministic orchestration layer owns state, transitions, gates, retries,
escalation, permissions, and routing. Agents communicate through structured
contracts; they cannot approve their own work or mark a task DONE. The Test
Runner is deterministic and is not an LLM agent. Deterministic test evidence
takes precedence over model judgment.

Architectural invariants:

- INV-01: Only orchestration changes workflow state.
- INV-02: No agent approves its own work or marks a task DONE.
- INV-03: Deterministic evidence takes precedence over LLM judgment.
- INV-04: Agent communication uses structured contracts.
- INV-05: Agents follow least privilege.
- INV-06: Agent context is bounded to relevant information.
- INV-07: Retries are bounded.
- INV-08: Model escalation is evidence-driven.
- INV-09: Secrets never enter artifacts, events, errors, or audit logs.
- INV-10: Accepted artifacts and workflow history are immutable.
- INV-11: State transitions must eventually be atomic.
- INV-12: Persistent execution must eventually support safe resume/idempotency.
- INV-13: Runtime errors and product/test failures are distinct.
- INV-14: Material workflow decisions must eventually be traceable to evidence.

Task 1 defines structure only. Pydantic checks local constraints, not workflow
policy, permissions, secret detection, evidence quality, or cross-record gates.
No additional frameworks or infrastructure are introduced.
