
import pytest
from qa_sentinel.domain.enums import TaskState as S
from qa_sentinel.orchestration.state_machine import can_transition, validate_transition
from qa_sentinel.orchestration.errors import InvalidTransitionError, TerminalStateError, ResumeStateError


# Independent specification oracle, not a copy of the implementation constant.
ALLOWED={
    S.CREATED:{S.RESEARCHING,S.BLOCKED}, S.RESEARCHING:{S.PLANNING,S.BLOCKED},
    S.PLANNING:{S.IMPLEMENTING,S.RESEARCHING,S.BLOCKED},
    S.IMPLEMENTING:{S.TESTING,S.PLANNING,S.FAILED}, S.TESTING:{S.REVIEWING,S.ANALYZING},
    S.ANALYZING:{S.INVESTIGATING,S.TESTING},
    S.INVESTIGATING:{S.IMPLEMENTING,S.RESEARCHING,S.BLOCKED,S.FAILED},
    S.REVIEWING:{S.DONE,S.IMPLEMENTING,S.PLANNING,S.BLOCKED},
    S.BLOCKED:{S.RESEARCHING,S.FAILED}, S.FAILED:set(),S.DONE:set(),
}


def test_entire_canonical_graph_and_forbidden_edges():
    for source in S:
        for destination in S:
            resume=S.RESEARCHING if source==S.BLOCKED else source if destination==S.BLOCKED else None
            expected=destination in ALLOWED[source]
            assert can_transition(source,destination,resume_state=resume) is expected
            if expected:validate_transition(source,destination,resume_state=resume)
            else:
                with pytest.raises(InvalidTransitionError):validate_transition(source,destination,resume_state=resume)


def test_same_state_requires_explicit_flag_and_only_three_placeholders():
    placeholders={S.RESEARCHING,S.IMPLEMENTING,S.INVESTIGATING}
    for state in S:
        assert not can_transition(state,state)
        assert can_transition(state,state,allow_same_state=True) is (state in placeholders)


@pytest.mark.parametrize("terminal",[S.DONE,S.FAILED])
def test_terminal_states_are_protected(terminal):
    for destination in S:
        with pytest.raises(TerminalStateError):validate_transition(terminal,destination,allow_same_state=True)


def test_blocked_resume_is_exact_and_excludes_terminal_and_blocked():
    validate_transition(S.BLOCKED,S.PLANNING,resume_state=S.PLANNING)
    validate_transition(S.BLOCKED,S.FAILED)
    with pytest.raises(ResumeStateError):validate_transition(S.BLOCKED,S.RESEARCHING,resume_state=S.PLANNING)
    for resume in [None,S.DONE,S.FAILED,S.BLOCKED,"PLANNING"]:
        with pytest.raises(ResumeStateError):validate_transition(S.CREATED,S.BLOCKED,resume_state=resume)
    with pytest.raises(ResumeStateError):validate_transition(S.BLOCKED,S.PLANNING)


def test_string_states_are_not_a_dynamic_transition_api():
    with pytest.raises(InvalidTransitionError):validate_transition("CREATED",S.RESEARCHING)
