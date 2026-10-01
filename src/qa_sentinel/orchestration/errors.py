"""Deterministic workflow failures; recording runtime errors is separate policy."""

class WorkflowError(Exception):
    pass


class InvalidTransitionError(WorkflowError):
    pass


class TerminalStateError(InvalidTransitionError):
    pass


class ResumeStateError(InvalidTransitionError):
    pass


class MissingGateError(WorkflowError):
    pass


class GateRejectedError(WorkflowError):
    pass
