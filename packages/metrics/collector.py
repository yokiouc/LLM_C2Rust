"""Metrics collection: separates engineering runtime metrics from thesis evaluation metrics."""

from typing import Any

from packages.core.types import RunMetrics, EvalMetrics, SafetyMetrics


def build_run_metrics(
    *,
    iteration_count: int = 0,
    patch_rounds: int = 0,
    rollback_count: int = 0,
    total_ms: int = 0,
    retrieve_ms: int = 0,
    generate_ms: int = 0,
    validate_ms: int = 0,
    build_ms: int = 0,
    test_ms: int = 0,
) -> RunMetrics:
    """Create engineering runtime metrics."""
    return RunMetrics(
        iteration_count=iteration_count,
        patch_rounds=patch_rounds,
        rollback_count=rollback_count,
        total_ms=total_ms,
        retrieve_ms=retrieve_ms,
        generate_ms=generate_ms,
        validate_ms=validate_ms,
        build_ms=build_ms,
        test_ms=test_ms,
    )


def build_eval_metrics(
    *,
    compile_ok_before: bool = False,
    compile_ok_after: bool = False,
    test_ok_before: bool = False,
    test_ok_after: bool = False,
    lint_ok_before: bool = False,
    lint_ok_after: bool = False,
    fmt_ok_before: bool = False,
    fmt_ok_after: bool = False,
    safety_before: SafetyMetrics | None = None,
    safety_after: SafetyMetrics | None = None,
    patch_size_lines: int = 0,
    final_stop_reason: str = "",
    primary_error_kind: str = "",
    progress_score_history: list[float] | None = None,
) -> EvalMetrics:
    """Create thesis evaluation metrics."""
    return EvalMetrics(
        compile_ok_before=compile_ok_before,
        compile_ok_after=compile_ok_after,
        test_ok_before=test_ok_before,
        test_ok_after=test_ok_after,
        lint_ok_before=lint_ok_before,
        lint_ok_after=lint_ok_after,
        fmt_ok_before=fmt_ok_before,
        fmt_ok_after=fmt_ok_after,
        safety_before=safety_before or SafetyMetrics(),
        safety_after=safety_after or SafetyMetrics(),
        patch_size_lines=patch_size_lines,
        final_stop_reason=final_stop_reason,
        primary_error_kind=primary_error_kind,
        progress_score_history=progress_score_history or [],
    )


def metrics_to_db_pairs(run_metrics: RunMetrics, eval_metrics: EvalMetrics) -> list[tuple[str, Any]]:
    """Convert metrics to (key, value) pairs for DB upsert."""
    pairs: list[tuple[str, Any]] = []

    # Engineering metrics
    pairs.append(("iteration_count", run_metrics.iteration_count))
    pairs.append(("patch_rounds", run_metrics.patch_rounds))
    pairs.append(("rollback_count", run_metrics.rollback_count))
    pairs.append(("total_ms", run_metrics.total_ms))
    pairs.append(("retrieve_ms", run_metrics.retrieve_ms))
    pairs.append(("generate_ms", run_metrics.generate_ms))
    pairs.append(("validate_ms", run_metrics.validate_ms))
    pairs.append(("build_ms", run_metrics.build_ms))
    pairs.append(("test_ms", run_metrics.test_ms))

    # Evaluation metrics
    pairs.append(("compile_ok_before", eval_metrics.compile_ok_before))
    pairs.append(("compile_ok_after", eval_metrics.compile_ok_after))
    pairs.append(("test_ok_before", eval_metrics.test_ok_before))
    pairs.append(("test_ok_after", eval_metrics.test_ok_after))
    pairs.append(("lint_ok_before", eval_metrics.lint_ok_before))
    pairs.append(("lint_ok_after", eval_metrics.lint_ok_after))
    pairs.append(("fmt_ok_before", eval_metrics.fmt_ok_before))
    pairs.append(("fmt_ok_after", eval_metrics.fmt_ok_after))

    # Safety before/after
    sb = eval_metrics.safety_before
    sa = eval_metrics.safety_after
    pairs.append(("unsafe_block_count_before", sb.unsafe_block_count))
    pairs.append(("unsafe_block_count_after", sa.unsafe_block_count))
    pairs.append(("raw_ptr_count_before", sb.raw_ptr_count))
    pairs.append(("raw_ptr_count_after", sa.raw_ptr_count))
    pairs.append(("unsafe_api_count_before", sb.unsafe_api_count))
    pairs.append(("unsafe_api_count_after", sa.unsafe_api_count))
    pairs.append(("manual_mem_call_count_before", sb.manual_mem_call_count))
    pairs.append(("manual_mem_call_count_after", sa.manual_mem_call_count))

    pairs.append(("patch_size_lines", eval_metrics.patch_size_lines))
    pairs.append(("final_stop_reason", eval_metrics.final_stop_reason))
    pairs.append(("primary_error_kind", eval_metrics.primary_error_kind))
    pairs.append(("progress_score_history", eval_metrics.progress_score_history))

    return pairs
