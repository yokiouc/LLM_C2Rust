"""FSM state definitions and transition table.

Defines all valid states and transitions for the Repair Agent.
The actual FSM engine and handlers will be implemented in phase 5.
"""

from packages.core.constants import AgentState

# State transition table: state -> set of valid next states
TRANSITIONS: dict[AgentState, set[AgentState]] = {
    AgentState.INIT: {AgentState.PRECHECK, AgentState.HOTSPOT_DISCOVERY, AgentState.RETRIEVE},
    AgentState.PRECHECK: {AgentState.HOTSPOT_DISCOVERY, AgentState.STOP_HARD_ERROR},
    AgentState.HOTSPOT_DISCOVERY: {AgentState.SLICE_SELECT, AgentState.STOP_HARD_ERROR},
    AgentState.SLICE_SELECT: {AgentState.RETRIEVE_EVIDENCE, AgentState.RETRIEVE, AgentState.STOP_HARD_ERROR},
    AgentState.RETRIEVE_EVIDENCE: {AgentState.BUILD_PROMPT, AgentState.STOP_HARD_ERROR},
    AgentState.BUILD_PROMPT: {AgentState.GENERATE_PATCH, AgentState.STOP_HARD_ERROR},
    AgentState.GENERATE_PATCH: {AgentState.VALIDATE_PATCH, AgentState.DIAGNOSE, AgentState.STOP_HARD_ERROR},
    AgentState.VALIDATE_PATCH: {AgentState.APPLY_PATCH, AgentState.DIAGNOSE, AgentState.STOP_HARD_ERROR},
    AgentState.APPLY_PATCH: {AgentState.RUN_BUILD, AgentState.DIAGNOSE, AgentState.ROLLBACK},
    AgentState.RUN_BUILD: {AgentState.RUN_TEST, AgentState.DIAGNOSE, AgentState.ROLLBACK},
    AgentState.RUN_TEST: {AgentState.RUN_LINT, AgentState.SCORE_PROGRESS, AgentState.DIAGNOSE, AgentState.ROLLBACK},
    AgentState.RUN_LINT: {AgentState.SCORE_PROGRESS, AgentState.DIAGNOSE},
    AgentState.DIAGNOSE: {AgentState.ROLLBACK, AgentState.SCORE_PROGRESS, AgentState.STOP_HARD_ERROR},
    AgentState.SCORE_PROGRESS: {
        AgentState.SUCCESS,
        AgentState.RETRIEVE_EVIDENCE,
        AgentState.HOTSPOT_DISCOVERY,
        AgentState.STOP_NO_PROGRESS,
        AgentState.STOP_MAX_ITERS,
    },
    AgentState.ROLLBACK: {AgentState.SCORE_PROGRESS, AgentState.DIAGNOSE, AgentState.STOP_HARD_ERROR},
    # Terminal states have no transitions
    AgentState.SUCCESS: set(),
    AgentState.STOP_NO_PROGRESS: set(),
    AgentState.STOP_MAX_ITERS: set(),
    AgentState.STOP_HARD_ERROR: set(),

    # Legacy states (for existing runs)
    AgentState.RETRIEVE: {AgentState.GENERATE, AgentState.STOP, AgentState.FAILED},
    AgentState.GENERATE: {AgentState.APPLY, AgentState.STOP, AgentState.FAILED},
    AgentState.APPLY: {AgentState.EXECUTE, AgentState.STOP, AgentState.FAILED},
    AgentState.EXECUTE: {AgentState.DIAGNOSE, AgentState.STOP, AgentState.FAILED},
    AgentState.STOP: set(),
    AgentState.FAILED: set(),
}


def is_terminal(state: AgentState) -> bool:
    """Check if a state is terminal (no further transitions)."""
    return len(TRANSITIONS.get(state, set())) == 0


def validate_transition(from_state: AgentState, to_state: AgentState) -> bool:
    """Check if a state transition is valid."""
    allowed = TRANSITIONS.get(from_state, set())
    return to_state in allowed
