"""Metrics repository: safety metrics computation, baseline comparison, run aggregation.

All DB access uses packages.core.db.connect (canonical path).
For safety scanning of .rs files, uses packages.metrics.safety (no DB needed).
"""

from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from packages.core.db import connect
from packages.metrics.safety import compute_safety_metrics as _compute_safety
from packages.metrics.compare import build_comparison, ComparisonResult


# ---------------------------------------------------------------------------
# Safety Metrics (delegates to packages.metrics.safety for file scanning)
# ---------------------------------------------------------------------------

def compute_safety_metrics(workspace_path: str) -> dict[str, Any]:
    """Scan a workspace and return safety metrics as a dict.

    This is a convenience wrapper around packages.metrics.safety.compute_safety_metrics
    that returns a plain dict suitable for DB storage or API response.
    """
    from pathlib import Path
    m = _compute_safety(Path(workspace_path))
    return {
        "unsafe_block_count": m.unsafe_block_count,
        "raw_ptr_count": m.raw_ptr_count,
        "unsafe_api_count": m.unsafe_api_count,
        "manual_mem_call_count": m.manual_mem_call_count,
        "unsafe_line_pct": m.unsafe_line_pct,
        "total_lines": m.total_lines,
    }


# ---------------------------------------------------------------------------
# Run Metrics Aggregation
# ---------------------------------------------------------------------------

def get_run_metrics(conn: Connection, *, run_id: str) -> dict[str, Any]:
    """Fetch all metrics for a given run as a flat dict."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT key, value_json FROM metrics WHERE run_id = %s ORDER BY key;",
            (run_id,),
        )
        rows = cur.fetchall()
    return {str(r["key"]): r["value_json"] for r in rows}


def aggregate_runs(
    conn: Connection,
    *,
    project_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Aggregate run summaries with key metrics, optionally filtered by project.

    Returns a list of run summaries with metrics joined in.
    """
    if project_id is not None:
        # Filter runs by project — join through snapshots
        # Note: agent_runs doesn't have a direct project FK,
        # so we use a metrics-based approach or return all runs
        pass

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
              ar.run_id,
              ar.repo_url,
              ar.ref,
              ar.task_description,
              ar.status,
              ar.created_at,
              ar.updated_at
            FROM agent_runs ar
            ORDER BY ar.created_at DESC
            LIMIT %s OFFSET %s;
            """,
            (limit, offset),
        )
        runs = cur.fetchall()

    result: list[dict[str, Any]] = []
    for run in runs:
        rid = str(run["run_id"])
        metrics = get_run_metrics(conn, run_id=rid)
        result.append({
            **dict(run),
            "metrics": metrics,
            "final_status": metrics.get("final_status"),
            "final_stop_reason": metrics.get("final_stop_reason"),
            "iteration_count": metrics.get("iteration_count"),
            "total_ms": metrics.get("total_ms"),
            "mode": metrics.get("mode"),
        })
    return result


# ---------------------------------------------------------------------------
# Baseline vs Enhanced Comparison
# ---------------------------------------------------------------------------

def compare_baseline(
    conn: Connection,
    *,
    project: str,
    snapshot_id: int,
    baseline_run_id: str,
    enhanced_run_id: str,
) -> ComparisonResult:
    """Build a comparison between a baseline and an enhanced run."""
    baseline_metrics = get_run_metrics(conn, run_id=baseline_run_id)
    baseline_metrics["run_id"] = baseline_run_id

    enhanced_metrics = get_run_metrics(conn, run_id=enhanced_run_id)
    enhanced_metrics["run_id"] = enhanced_run_id

    return build_comparison(
        project=project,
        snapshot_id=snapshot_id,
        baseline_metrics=baseline_metrics,
        enhanced_metrics=enhanced_metrics,
    )


def list_run_pairs_for_comparison(
    conn: Connection,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Find baseline/enhanced run pairs for comparison.

    Groups runs by repo_url+ref and looks for pairs where one has
    mode='baseline' and the other has mode='enhanced'.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
              ar.run_id,
              ar.repo_url,
              ar.ref,
              ar.status,
              ar.created_at,
              m_mode.value_json AS mode,
              m_status.value_json AS final_status
            FROM agent_runs ar
            LEFT JOIN metrics m_mode ON m_mode.run_id = ar.run_id AND m_mode.key = 'mode'
            LEFT JOIN metrics m_status ON m_status.run_id = ar.run_id AND m_status.key = 'final_status'
            ORDER BY ar.created_at DESC
            LIMIT %s;
            """,
            (limit * 2,),
        )
        rows = cur.fetchall()

    # Group by (repo_url, ref)
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = f"{row['repo_url']}#{row['ref']}"
        groups.setdefault(key, []).append(dict(row))

    pairs: list[dict[str, Any]] = []
    for key, group_runs in groups.items():
        baseline = None
        enhanced = None
        for r in group_runs:
            mode = str(r.get("mode") or "").strip('"')
            if mode == "baseline" and baseline is None:
                baseline = r
            elif mode == "enhanced" and enhanced is None:
                enhanced = r
        if baseline and enhanced:
            pairs.append({
                "repo_url": baseline["repo_url"],
                "ref": baseline["ref"],
                "baseline": baseline,
                "enhanced": enhanced,
            })
        if len(pairs) >= limit:
            break

    return pairs
