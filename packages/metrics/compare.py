"""Baseline vs Enhanced comparison aggregation for thesis evaluation."""

from dataclasses import dataclass
from typing import Any


@dataclass
class ComparisonResult:
    """Comparison between baseline and enhanced repair runs."""
    project: str
    snapshot_id: int

    # Baseline
    baseline_run_id: str | None = None
    baseline_compile_ok: bool = False
    baseline_test_ok: bool = False
    baseline_unsafe_blocks: int = 0
    baseline_raw_ptr_count: int = 0
    baseline_unsafe_api_count: int = 0
    baseline_total_ms: int = 0

    # Enhanced
    enhanced_run_id: str | None = None
    enhanced_compile_ok: bool = False
    enhanced_test_ok: bool = False
    enhanced_unsafe_blocks: int = 0
    enhanced_raw_ptr_count: int = 0
    enhanced_unsafe_api_count: int = 0
    enhanced_total_ms: int = 0
    enhanced_iterations: int = 0
    enhanced_rollbacks: int = 0
    enhanced_stop_reason: str = ""

    # Deltas
    @property
    def unsafe_blocks_delta(self) -> int:
        return self.enhanced_unsafe_blocks - self.baseline_unsafe_blocks

    @property
    def raw_ptr_delta(self) -> int:
        return self.enhanced_raw_ptr_count - self.baseline_raw_ptr_count

    @property
    def unsafe_api_delta(self) -> int:
        return self.enhanced_unsafe_api_count - self.baseline_unsafe_api_count


def build_comparison(
    *,
    project: str,
    snapshot_id: int,
    baseline_metrics: dict[str, Any],
    enhanced_metrics: dict[str, Any],
) -> ComparisonResult:
    """Build comparison from two metrics dictionaries (as stored in DB)."""
    return ComparisonResult(
        project=project,
        snapshot_id=snapshot_id,
        baseline_run_id=str(baseline_metrics.get("run_id") or ""),
        baseline_compile_ok=bool(baseline_metrics.get("compile_ok") or baseline_metrics.get("execute_ok")),
        baseline_test_ok=bool(baseline_metrics.get("test_ok") or (baseline_metrics.get("final_status") == "OK")),
        baseline_unsafe_blocks=int(baseline_metrics.get("unsafe_blocks") or baseline_metrics.get("unsafe_block_count_before") or 0),
        baseline_raw_ptr_count=int(baseline_metrics.get("raw_ptr_count") or baseline_metrics.get("raw_ptr_count_before") or 0),
        baseline_unsafe_api_count=int(baseline_metrics.get("unsafe_api_count") or baseline_metrics.get("unsafe_api_count_before") or 0),
        baseline_total_ms=int(baseline_metrics.get("total_ms") or 0),
        enhanced_run_id=str(enhanced_metrics.get("run_id") or ""),
        enhanced_compile_ok=bool(enhanced_metrics.get("compile_ok") or enhanced_metrics.get("execute_ok")),
        enhanced_test_ok=bool(enhanced_metrics.get("test_ok") or (enhanced_metrics.get("final_status") == "OK")),
        enhanced_unsafe_blocks=int(enhanced_metrics.get("unsafe_blocks") or enhanced_metrics.get("unsafe_block_count_after") or 0),
        enhanced_raw_ptr_count=int(enhanced_metrics.get("raw_ptr_count") or enhanced_metrics.get("raw_ptr_count_after") or 0),
        enhanced_unsafe_api_count=int(enhanced_metrics.get("unsafe_api_count") or enhanced_metrics.get("unsafe_api_count_after") or 0),
        enhanced_total_ms=int(enhanced_metrics.get("total_ms") or 0),
        enhanced_iterations=int(enhanced_metrics.get("iteration_count") or 0),
        enhanced_rollbacks=int(enhanced_metrics.get("rollback_count") or 0),
        enhanced_stop_reason=str(enhanced_metrics.get("final_stop_reason") or ""),
    )
