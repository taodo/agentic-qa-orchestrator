# Canonical workflow states

CREATED, RESEARCHING, PLANNING, IMPLEMENTING, TESTING, ANALYZING,
INVESTIGATING, REVIEWING, BLOCKED, FAILED, DONE.

Task records state and optional resume_state, timestamps, current invocation,
implementation attempt, defect cycle, review cycle, and terminal reason.
Only orchestration may change workflow state. The Task model is a data contract;
it provides no transition API and does not enforce authorization.

Transition records link from/to states, trigger, decision, and an optional gate
evaluation. No transition table, runtime engine, retry policy, or gates are
implemented in Task 1.
