"""Export structured tables for thesis paper.

Generates:
  - Table 1: Baseline vs Enhanced safety comparison
  - Table 2: Repair cost summary
  - Raw CSV for further analysis

Usage:
  python scripts/export_paper_tables.py --out results/
  python scripts/export_paper_tables.py --out results/ --run-id <id1> --run-id <id2>
"""

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


def _dsn() -> str:
    return os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN") or ""


def _fetch_run_metrics(conn: psycopg.Connection, run_id: str) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT key, value_json FROM metrics WHERE run_id = %s;", (run_id,))
        rows = cur.fetchall()
    return {str(r["key"]): r["value_json"] for r in rows}


def _fetch_run_info(conn: psycopg.Connection, run_id: str) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT run_id, repo_url, ref, task_description, status, created_at FROM agent_runs WHERE run_id = %s;",
            (run_id,),
        )
        return dict(cur.fetchone() or {})


def _fetch_all_runs(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT run_id, repo_url, ref, status, created_at FROM agent_runs ORDER BY created_at;",
        )
        return cur.fetchall()


@dataclass
class RunRow:
    """Flat row for export."""
    project: str
    run_id: str
    mode: str
    final_status: str
    final_stop_reason: str
    compile_ok: bool
    test_ok: bool
    unsafe_before: int
    unsafe_after: int
    raw_ptr_before: int
    raw_ptr_after: int
    unsafe_api_before: int
    unsafe_api_after: int
    manual_mem_before: int
    manual_mem_after: int
    iteration_count: int
    patch_rounds: int
    rollback_count: int
    total_ms: int
    retrieve_ms: int
    generate_ms: int
    build_ms: int
    test_ms: int
    primary_error_kind: str
    progress_score_history: str


def _build_row(run_info: dict, metrics: dict) -> RunRow:
    mode = str(metrics.get("mode") or "unknown").strip('"')
    final_status = str(metrics.get("final_status") or run_info.get("status") or "unknown").strip('"')
    final_stop = str(metrics.get("final_stop_reason") or "").strip('"')

    return RunRow(
        project=str(run_info.get("repo_url") or run_info.get("ref") or ""),
        run_id=str(run_info.get("run_id") or ""),
        mode=mode,
        final_status=final_status,
        final_stop_reason=final_stop,
        compile_ok=bool(metrics.get("compile_ok_after") or metrics.get("execute_ok") or (final_status == "OK")),
        test_ok=bool(metrics.get("test_ok_after") or (final_status == "OK")),
        unsafe_before=int(metrics.get("unsafe_block_count_before") or 0),
        unsafe_after=int(metrics.get("unsafe_block_count_after") or 0),
        raw_ptr_before=int(metrics.get("raw_ptr_count_before") or 0),
        raw_ptr_after=int(metrics.get("raw_ptr_count_after") or 0),
        unsafe_api_before=int(metrics.get("unsafe_api_count_before") or 0),
        unsafe_api_after=int(metrics.get("unsafe_api_count_after") or 0),
        manual_mem_before=int(metrics.get("manual_mem_call_count_before") or 0),
        manual_mem_after=int(metrics.get("manual_mem_call_count_after") or 0),
        iteration_count=int(metrics.get("iteration_count") or 0),
        patch_rounds=int(metrics.get("patch_rounds") or metrics.get("iteration_count") or 0),
        rollback_count=int(metrics.get("rollback_count") or 0),
        total_ms=int(metrics.get("total_ms") or 0),
        retrieve_ms=int(metrics.get("retrieve_ms") or 0),
        generate_ms=int(metrics.get("generate_ms") or 0),
        build_ms=int(metrics.get("build_ms") or 0),
        test_ms=int(metrics.get("test_ms") or 0),
        primary_error_kind=str(metrics.get("primary_error_kind") or "").strip('"'),
        progress_score_history=json.dumps(metrics.get("progress_score_history") or []),
    )


TABLE1_COLUMNS = [
    "project", "mode", "final_status",
    "compile_ok", "test_ok",
    "unsafe_before", "unsafe_after",
    "raw_ptr_before", "raw_ptr_after",
    "unsafe_api_before", "unsafe_api_after",
    "manual_mem_before", "manual_mem_after",
]

TABLE2_COLUMNS = [
    "project", "mode", "final_status", "final_stop_reason",
    "iteration_count", "patch_rounds", "rollback_count",
    "total_ms", "retrieve_ms", "generate_ms", "build_ms", "test_ms",
    "primary_error_kind",
]

ALL_COLUMNS = [
    "project", "run_id", "mode", "final_status", "final_stop_reason",
    "compile_ok", "test_ok",
    "unsafe_before", "unsafe_after",
    "raw_ptr_before", "raw_ptr_after",
    "unsafe_api_before", "unsafe_api_after",
    "manual_mem_before", "manual_mem_after",
    "iteration_count", "patch_rounds", "rollback_count",
    "total_ms", "retrieve_ms", "generate_ms", "build_ms", "test_ms",
    "primary_error_kind", "progress_score_history",
]


def _write_csv(path: Path, columns: list[str], rows: list[RunRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            d = {k: getattr(r, k) for k in columns if hasattr(r, k)}
            w.writerow(d)
    print(f"  Written: {path} ({len(rows)} rows)")


def _print_table(title: str, columns: list[str], rows: list[RunRow]) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")

    # Simple text table
    header = " | ".join(f"{c:>16}" for c in columns)
    print(header)
    print("-" * len(header))
    for r in rows:
        vals = [str(getattr(r, c, "")) for c in columns]
        print(" | ".join(f"{v:>16}" for v in vals))


def main() -> None:
    ap = argparse.ArgumentParser(description="Export paper tables from repair runs")
    ap.add_argument("--out", default="results", help="Output directory")
    ap.add_argument("--run-id", action="append", default=[], help="Specific run IDs (repeatable)")
    args = ap.parse_args()

    dsn = _dsn()
    if not dsn:
        raise SystemExit("DATABASE_URL not set")

    out_dir = Path(args.out).resolve()

    with psycopg.connect(dsn, connect_timeout=5) as conn:
        if args.run_id:
            run_ids = args.run_id
        else:
            runs = _fetch_all_runs(conn)
            run_ids = [str(r["run_id"]) for r in runs]

        rows: list[RunRow] = []
        for rid in run_ids:
            run_info = _fetch_run_info(conn, rid)
            if not run_info:
                print(f"  WARN: run {rid} not found, skipping")
                continue
            metrics = _fetch_run_metrics(conn, rid)
            rows.append(_build_row(run_info, metrics))

    if not rows:
        raise SystemExit("No runs found")

    # Print tables to console
    _print_table("Table 1: Safety Comparison (Baseline vs Enhanced)", TABLE1_COLUMNS, rows)
    _print_table("Table 2: Repair Cost", TABLE2_COLUMNS, rows)

    # Write CSV files
    _write_csv(out_dir / "table1_safety.csv", TABLE1_COLUMNS, rows)
    _write_csv(out_dir / "table2_cost.csv", TABLE2_COLUMNS, rows)
    _write_csv(out_dir / "all_metrics.csv", ALL_COLUMNS, rows)

    # Write JSON summary
    json_path = out_dir / "summary.json"
    summary = {
        "total_runs": len(rows),
        "baseline_runs": len([r for r in rows if r.mode == "baseline"]),
        "enhanced_runs": len([r for r in rows if r.mode == "enhanced"]),
        "successful": len([r for r in rows if r.final_status == "OK"]),
        "failed": len([r for r in rows if r.final_status != "OK"]),
        "runs": [
            {
                "run_id": r.run_id,
                "project": r.project,
                "mode": r.mode,
                "status": r.final_status,
                "unsafe_delta": r.unsafe_after - r.unsafe_before,
                "raw_ptr_delta": r.raw_ptr_after - r.raw_ptr_before,
                "iterations": r.iteration_count,
                "duration_ms": r.total_ms,
            }
            for r in rows
        ],
    }
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  Written: {json_path}")

    print(f"\nExport complete: {len(rows)} runs → {out_dir}/")


if __name__ == "__main__":
    main()
