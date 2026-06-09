"""Shared domain types used across packages."""

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Run & Patch
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RunRecord:
    run_id: str
    status: str


@dataclass(frozen=True)
class PatchResult:
    ok: bool
    status: str
    file_paths: list[str]
    backup_dir: str | None
    error_msg: str | None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationResult:
    """Structured result of a single validation phase (build/test/clippy/fmt)."""
    phase: str
    ok: bool
    exit_code: int
    duration_ms: int
    stdout: str = ""
    stderr: str = ""
    log_path: str = ""
    parsed_issues: list[dict[str, Any]] = field(default_factory=list)
    issue_count: int = 0


# ---------------------------------------------------------------------------
# Hotspot
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HotspotInfo:
    """A discovered high-risk location in the source."""
    file: str
    symbol: str | None
    line_start: int
    line_end: int
    hotspot_kind: str
    risk_score: int
    risk_tags: list[str]
    content: str = ""
    supporting_evidence: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Slice
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SliceInfo:
    """A minimal repair slice with interface boundary constraints."""
    file: str
    start_line: int
    end_line: int
    anchor_line: int
    symbol: str | None
    content: str = ""

    # Interface boundary
    signature_text: str | None = None
    signature_line: int | None = None

    # Constraints
    keep_signature: bool = True
    no_global_rename: bool = True
    min_patch: bool = True
    forbidden_regions: list[dict[str, Any]] = field(default_factory=list)

    # Related info
    related_vars: list[str] = field(default_factory=list)
    related_unsafe_ops: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RunCmdResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    log_path: str


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass
class SafetyMetrics:
    """Safety metrics for before/after comparison."""
    unsafe_block_count: int = 0
    raw_ptr_count: int = 0
    unsafe_api_count: int = 0
    manual_mem_call_count: int = 0
    unsafe_line_pct: float = 0.0
    total_lines: int = 0


@dataclass
class RunMetrics:
    """Engineering runtime metrics."""
    iteration_count: int = 0
    patch_rounds: int = 0
    rollback_count: int = 0
    total_ms: int = 0
    retrieve_ms: int = 0
    generate_ms: int = 0
    validate_ms: int = 0
    build_ms: int = 0
    test_ms: int = 0


@dataclass
class EvalMetrics:
    """Thesis evaluation metrics."""
    compile_ok_before: bool = False
    compile_ok_after: bool = False
    test_ok_before: bool = False
    test_ok_after: bool = False
    lint_ok_before: bool = False
    lint_ok_after: bool = False
    fmt_ok_before: bool = False
    fmt_ok_after: bool = False
    safety_before: SafetyMetrics = field(default_factory=SafetyMetrics)
    safety_after: SafetyMetrics = field(default_factory=SafetyMetrics)
    patch_size_lines: int = 0
    final_stop_reason: str = ""
    primary_error_kind: str = ""
    progress_score_history: list[float] = field(default_factory=list)
