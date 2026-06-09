"""Enumerations, constants, and shared definitions."""

from enum import Enum


# ---------------------------------------------------------------------------
# FSM States
# ---------------------------------------------------------------------------

class AgentState(str, Enum):
    """All possible states for the Repair Agent FSM."""
    INIT = "INIT"
    PRECHECK = "PRECHECK"
    HOTSPOT_DISCOVERY = "HOTSPOT_DISCOVERY"
    SLICE_SELECT = "SLICE_SELECT"
    RETRIEVE_EVIDENCE = "RETRIEVE_EVIDENCE"
    BUILD_PROMPT = "BUILD_PROMPT"
    GENERATE_PATCH = "GENERATE_PATCH"
    VALIDATE_PATCH = "VALIDATE_PATCH"
    APPLY_PATCH = "APPLY_PATCH"
    RUN_BUILD = "RUN_BUILD"
    RUN_TEST = "RUN_TEST"
    RUN_LINT = "RUN_LINT"
    DIAGNOSE = "DIAGNOSE"
    SCORE_PROGRESS = "SCORE_PROGRESS"
    ROLLBACK = "ROLLBACK"
    SUCCESS = "SUCCESS"
    STOP_NO_PROGRESS = "STOP_NO_PROGRESS"
    STOP_MAX_ITERS = "STOP_MAX_ITERS"
    STOP_HARD_ERROR = "STOP_HARD_ERROR"

    # Legacy states kept for DB compatibility with existing runs
    RETRIEVE = "RETRIEVE"
    GENERATE = "GENERATE"
    APPLY = "APPLY"
    EXECUTE = "EXECUTE"
    STOP = "STOP"
    FAILED = "FAILED"


# All valid status values for agent_runs table constraint
AGENT_RUN_STATUSES = {s.value for s in AgentState}

# Terminal states
TERMINAL_STATES = {
    AgentState.SUCCESS,
    AgentState.STOP_NO_PROGRESS,
    AgentState.STOP_MAX_ITERS,
    AgentState.STOP_HARD_ERROR,
    AgentState.STOP,
    AgentState.FAILED,
}


# ---------------------------------------------------------------------------
# Evidence Types
# ---------------------------------------------------------------------------

class EvidenceType(str, Enum):
    RUST_FUNCTION_SLICE = "rust_function_slice"
    RUST_UNSAFE_BLOCK = "rust_unsafe_block"
    RUST_IDIOM_TEMPLATE = "rust_idiom_template"
    REPLACEMENT_STRATEGY = "replacement_strategy"
    INTERFACE_CONSTRAINT = "interface_constraint"
    BEHAVIOR_CONSTRAINT = "behavior_constraint"
    COMPILE_FIX_HINT = "compile_fix_hint"
    C_SYMBOL_SUMMARY = "c_symbol_summary"
    C_RESOURCE_FLOW_SUMMARY = "c_resource_flow_summary"


ALL_EVIDENCE_TYPES = {e.value for e in EvidenceType}


# ---------------------------------------------------------------------------
# Hotspot Kinds
# ---------------------------------------------------------------------------

class HotspotKind(str, Enum):
    UNSAFE_BLOCK = "unsafe_block"
    RAW_PTR_DEREF = "raw_ptr_deref"
    PTR_ARITHMETIC = "ptr_arithmetic"
    MANUAL_MEM_API = "manual_mem_api"
    MEMCPY_MEMMOVE = "memcpy_memmove"
    CROSS_FUNC_RESOURCE = "cross_func_resource"
    UNSAFE_FN_DECL = "unsafe_fn_decl"
    EXTERN_CALL = "extern_call"


# ---------------------------------------------------------------------------
# Risk Weights
# ---------------------------------------------------------------------------

RISK_WEIGHTS: dict[str, int] = {
    "unsafe": 3,
    "raw_ptr": 3,
    "ptr_arith": 2,
    "manual_mem": 2,
    "memcpy_memmove": 2,
    "extern_call": 1,
    "unsafe_fn": 2,
    "cross_func_resource": 2,
}


# ---------------------------------------------------------------------------
# Validation Phases
# ---------------------------------------------------------------------------

class ValidationPhase(str, Enum):
    BUILD = "cargo_build"
    TEST = "cargo_test"
    CLIPPY = "cargo_clippy"
    FMT_CHECK = "cargo_fmt_check"


# ---------------------------------------------------------------------------
# Patch Constraints
# ---------------------------------------------------------------------------

DEFAULT_PATCH_CONSTRAINTS = [
    "single_file_only",
    "target_file_must_match",
    "no_signature_change",
    "no_full_rewrite",
    "limit_changed_lines",
    "prefer_hotspot_neighborhood",
]

DEFAULT_FORBIDDEN_ACTIONS = [
    "multi_file_patch",
    "signature_change",
    "full_file_rewrite",
]
