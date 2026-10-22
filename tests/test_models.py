from aidevops.models import ALLOWED_TRANSITIONS, JobState, can_transition


def test_forward_transitions_allowed():
    assert can_transition(JobState.PENDING, JobState.ANALYZING)
    assert can_transition(JobState.ANALYZING, JobState.PLANNED)
    assert can_transition(JobState.PLANNED, JobState.GENERATING)
    assert can_transition(JobState.GENERATING, JobState.VALIDATING)
    assert can_transition(JobState.VALIDATING, JobState.AWAITING_APPROVAL)
    assert can_transition(JobState.AWAITING_APPROVAL, JobState.EXECUTING)
    assert can_transition(JobState.EXECUTING, JobState.VERIFYING)
    assert can_transition(JobState.VERIFYING, JobState.SUCCEEDED)


def test_illegal_transitions_rejected():
    assert not can_transition(JobState.PENDING, JobState.EXECUTING)
    assert not can_transition(JobState.PENDING, JobState.SUCCEEDED)
    assert not can_transition(JobState.PLANNED, JobState.PENDING)


def test_terminal_states_have_no_outgoing_edges():
    for state in (JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED):
        assert ALLOWED_TRANSITIONS[state] == frozenset()
