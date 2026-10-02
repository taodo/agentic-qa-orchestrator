# Architecture

## Implemented product boundary (Tasks 1–17)

The operator frontend uses the API, which delegates to QASentinelApplication
above the core. **External callers use Application Services, not orchestration
internals or persistence repositories directly.** Trusted hosts explicitly
compose Project-owned runtimes; request/model data cannot select workspace roots.
The loopback real host executes against trusted local workspaces. The protected
Render preview uses only deterministic synthetic demo evidence. See
[PRD](PRD.md), [Product Guide](PRODUCT_GUIDE.md), [Hosting](HOSTING.md) and
[Deployment](DEPLOYMENT.md) for current scope and limits.

The original invariant list below expresses the architectural intent. Task 1's
schema-only scope is historical; later tasks implement the accepted boundaries
described in [Phase 1](PHASE_1.md). It is not a claim of full distributed
idempotency, hostile-workspace sandboxing or general content secret detection.

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
