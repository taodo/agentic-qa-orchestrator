# Agent specification v0.1

LLM agents: RESEARCHER, PLANNER, IMPLEMENTER, TEST_ANALYZER, INVESTIGATOR,
REVIEWER. The deterministic Test Runner is separate.

Research reports findings with evidence/confidence, dependencies, constraints,
risks, explicit blocking unknowns, recommendations, and completion.

Planning reports READY_FOR_IMPLEMENTATION, NEEDS_RESEARCH, or BLOCKED.
Implementation steps contain stable id, description, files, and depends_on step
IDs. Acceptance criteria contain stable id, description, and nonblank verification.
Test strategy items reference acceptance criterion IDs. The output also includes
file changes, assumptions, risks, rollback considerations, and open questions.
Dependency existence and coverage completeness are deferred to later gates.

Implementation reports overall status and structured evidence:
- Step results: step_id and status (COMPLETED, BLOCKED, SKIPPED).
- Changed files: path, change_type (CREATED, MODIFIED, DELETED), and reason.
- Recorded commands: command and strictly integer exit_code.

It retains tests_added_or_modified, assumptions, known issues, and deviations
with an explicit requires_replan flag. Commands are records only; their exit
codes are not interpreted or executed by these contracts.

Analysis reports an overall result and classified failure groups with evidence,
confidence, and an investigation flag. It does not override deterministic results.

Investigation reports status, root cause, evidence/confidence, alternatives, and
evidence still needed. recommended_action contains a type (CODE_FIX, TEST_FIX,
MORE_RESEARCH, HUMAN_ACTION) and nonblank description. The type provides a
machine-routable contract; only later orchestration selects progression.

Review reports a decision, requirement coverage, issues with severity, test gaps,
risks, and unverified assumptions. Each coverage item contains acceptance_criterion_id,
status (COVERED, NOT_COVERED, UNVERIFIED), summary, and evidence_refs.
APPROVE remains a review recommendation, not DONE. No ReviewGate is implemented.

Schemas live in src/qa_sentinel/schemas. They are frozen and reject extra fields.
No prompts or agent implementations exist.
