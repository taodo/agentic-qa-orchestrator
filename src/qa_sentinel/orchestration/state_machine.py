"""Pure explicit transition validation, independent of persistence and agents."""
from types import MappingProxyType
from qa_sentinel.domain.enums import TaskState as S
from .errors import InvalidTransitionError, TerminalStateError, ResumeStateError

TERMINAL_STATES = frozenset({S.DONE, S.FAILED})
SAME_STATE_PLACEHOLDERS = frozenset({S.RESEARCHING, S.IMPLEMENTING, S.INVESTIGATING})
TRANSITIONS = MappingProxyType({
    S.CREATED: frozenset({S.RESEARCHING, S.BLOCKED}),
    S.RESEARCHING: frozenset({S.PLANNING, S.BLOCKED}),
    S.PLANNING: frozenset({S.IMPLEMENTING, S.RESEARCHING, S.BLOCKED}),
    S.IMPLEMENTING: frozenset({S.TESTING, S.PLANNING, S.FAILED}),
    S.TESTING: frozenset({S.REVIEWING, S.ANALYZING}),
    S.ANALYZING: frozenset({S.INVESTIGATING, S.TESTING}),
    S.INVESTIGATING: frozenset({S.IMPLEMENTING, S.RESEARCHING, S.BLOCKED, S.FAILED}),
    S.REVIEWING: frozenset({S.DONE, S.IMPLEMENTING, S.PLANNING, S.BLOCKED}),
    S.BLOCKED: frozenset({S.FAILED}),
    S.FAILED: frozenset(),
    S.DONE: frozenset(),
})


def validate_transition(from_state: S, to_state: S, *, resume_state: S | None = None,
                        allow_same_state: bool = False) -> None:
    if not isinstance(from_state, S) or not isinstance(to_state, S):
        raise InvalidTransitionError("States must be TaskState values")
    if from_state in TERMINAL_STATES:
        raise TerminalStateError("Terminal tasks have no outgoing transitions")
    if from_state == to_state:
        if allow_same_state and from_state in SAME_STATE_PLACEHOLDERS:
            return
        raise InvalidTransitionError("Same-state transition is not explicitly allowed")
    if from_state == S.BLOCKED:
        if to_state == S.FAILED:
            return
        if not isinstance(resume_state, S) or resume_state in TERMINAL_STATES or resume_state == S.BLOCKED:
            raise ResumeStateError("BLOCKED requires a nonterminal resume state")
        if to_state != resume_state:
            raise ResumeStateError("Only the stored resume state may be resumed")
        return
    if to_state not in TRANSITIONS[from_state]:
        raise InvalidTransitionError("Transition is not in the canonical whitelist")
    if to_state == S.BLOCKED:
        if not isinstance(resume_state, S) or resume_state in TERMINAL_STATES or resume_state == S.BLOCKED:
            raise ResumeStateError("Entering BLOCKED requires a nonterminal, non-BLOCKED resume state")


def can_transition(from_state: S, to_state: S, *, resume_state: S | None = None,
                   allow_same_state: bool = False) -> bool:
    try:
        validate_transition(from_state, to_state, resume_state=resume_state,
                            allow_same_state=allow_same_state)
    except InvalidTransitionError:
        return False
    return True
