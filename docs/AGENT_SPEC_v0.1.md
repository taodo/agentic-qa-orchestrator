# Agent specification v0.1

LLM agents: RESEARCHER, PLANNER, IMPLEMENTER, TEST_ANALYZER, INVESTIGATOR,
REVIEWER. The deterministic Test Runner is separate.

Research reports findings with evidence/confidence, dependencies, constraints,
risks, explicit blocking unknowns, recommendations, and completion.
Planning reports READY_FOR_IMPLEMENTATION, NEEDS_RESEARCH, or BLOCKED;
steps, file changes, stable acceptance IDs, test strategy references, assumptions,
risks, rollback considerations, and open questions.
Implementation reports status, plan steps, file/test changes, recorded commands,
assumptions, issues, and deviations with an explicit requires_replan flag.
Analysis reports an overall result and classified failure groups with evidence,
confidence, and an investigation flag. It does not override deterministic results.
Investigation reports status, root cause, evidence/confidence, recommended action,
alternatives, and evidence still needed.
Review reports a decision, requirement coverage, issues with severity, test gaps,
risks, and unverified assumptions. APPROVE is a review recommendation, not DONE.

Schemas live in src/qa_sentinel/schemas. No prompts or agent implementations exist.
