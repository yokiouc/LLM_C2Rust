import argparse
import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class RunContext:
    run_id: str
    project: str | None
    snapshot_id: int | None
    commit_sha: str | None
    workspace_path: str | None


def _dsn() -> str:
    return os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN") or ""


def _safe_int(v: Any) -> int | None:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def _load_run_context(conn: psycopg.Connection, run_id: str) -> RunContext:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT input_json
            FROM agent_steps
            WHERE run_id = %s AND step_name = 'INIT'
            ORDER BY created_at ASC
            LIMIT 1;
            """,
            (run_id,),
        )
        row = cur.fetchone()
    inp = dict(row["input_json"] or {}) if row else {}
    snapshot_id = _safe_int(inp.get("snapshot_id"))
    workspace_path = str(inp.get("workspace_path") or "") or None

    project = None
    commit_sha = None
    if snapshot_id is not None:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT p.name AS project_name, s.commit_sha AS commit_sha
                FROM repo_snapshots s
                JOIN projects p ON p.project_id = s.project_id
                WHERE s.snapshot_id = %s;
                """,
                (snapshot_id,),
            )
            r2 = cur.fetchone()
        if r2:
            project = str(r2.get("project_name") or "") or None
            commit_sha = str(r2.get("commit_sha") or "") or None

    return RunContext(run_id=run_id, project=project, snapshot_id=snapshot_id, commit_sha=commit_sha, workspace_path=workspace_path)


def _load_metrics(conn: psycopg.Connection, run_id: str) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT key, value_json FROM metrics WHERE run_id = %s;", (run_id,))
        rows = cur.fetchall()
    out: dict[str, Any] = {}
    for r in rows or []:
        out[str(r["key"])] = r["value_json"]
    return out


def _count_patches(conn: psycopg.Connection, run_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM patches WHERE run_id = %s;", (run_id,))
        return int(cur.fetchone()[0])


def _read_text_safely(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _scan_safety(workspace_path: str | None) -> dict[str, int]:
    if not workspace_path:
        return {"unsafe_blocks": 0, "raw_ptr_count": 0, "unsafe_api_count": 0}
    root = Path(workspace_path)
    if not root.exists():
        return {"unsafe_blocks": 0, "raw_ptr_count": 0, "unsafe_api_count": 0}

    unsafe_blocks = 0
    raw_ptr_count = 0
    unsafe_api_count = 0

    for rs in root.rglob("*.rs"):
        text = _read_text_safely(rs)
        unsafe_blocks += text.count("unsafe")
        raw_ptr_count += text.count("*const") + text.count("*mut") + text.count("as *const") + text.count("as *mut")
        unsafe_api_count += text.count("malloc") + text.count("free") + text.count("memcpy") + text.count("memmove")

    return {"unsafe_blocks": unsafe_blocks, "raw_ptr_count": raw_ptr_count, "unsafe_api_count": unsafe_api_count}


def _derive_correctness(metrics: dict[str, Any]) -> tuple[int, int]:
    final_status = str(metrics.get("final_status") or "")
    primary_error_kind = str(metrics.get("primary_error_kind") or "")
    if final_status == "OK":
        return 1, 1
    if primary_error_kind == "test_fail":
        return 1, 0
    return 0, 0


def _list_run_ids(conn: psycopg.Connection, limit: int) -> list[str]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT run_id
            FROM agent_runs
            ORDER BY created_at DESC
            LIMIT %s;
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [str(r["run_id"]) for r in rows or []]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="experiments.csv")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--run-id", action="append", default=[])
    args = ap.parse_args()

    dsn = _dsn()
    if not dsn:
        raise SystemExit("DATABASE_URL_not_set")

    out_path = Path(args.out).resolve()
    run_ids = [str(x) for x in (args.run_id or []) if str(x)]

    with psycopg.connect(dsn, connect_timeout=5) as conn:
        if not run_ids:
            run_ids = _list_run_ids(conn, limit=min(max(int(args.limit), 1), 2000))

        rows: list[dict[str, Any]] = []
        for rid in run_ids:
            ctx = _load_run_context(conn, rid)
            metrics = _load_metrics(conn, rid)
            patch_rounds = _count_patches(conn, rid)

            mode = str(metrics.get("mode") or "")
            if mode not in {"baseline", "enhanced"}:
                mode = "enhanced" if patch_rounds > 0 else "baseline"

            compile_ok, test_ok = _derive_correctness(metrics)
            safety = _scan_safety(ctx.workspace_path)

            rows.append(
                {
                    "project": ctx.project,
                    "snapshot": ctx.snapshot_id,
                    "commit": ctx.commit_sha,
                    "run_id": rid,
                    "mode": mode,
                    "compile_ok": compile_ok,
                    "test_ok": test_ok,
                    "final_status": metrics.get("final_status"),
                    "diagnose_issue_count": metrics.get("diagnose_issue_count"),
                    "unsafe_blocks": safety["unsafe_blocks"],
                    "raw_ptr_count": safety["raw_ptr_count"],
                    "unsafe_api_count": safety["unsafe_api_count"],
                    "iteration_count": metrics.get("iteration_count"),
                    "patch_rounds": patch_rounds,
                    "rollback_count": metrics.get("rollback_count"),
                    "total_ms": metrics.get("total_ms"),
                    "retrieve_ms": metrics.get("retrieve_ms"),
                    "generate_ms": metrics.get("generate_ms"),
                    "execute_ms": metrics.get("execute_ms"),
                    "primary_error_kind": metrics.get("primary_error_kind"),
                    "final_stop_reason": metrics.get("final_stop_reason"),
                }
            )

    columns = [
        "project",
        "snapshot",
        "commit",
        "run_id",
        "mode",
        "compile_ok",
        "test_ok",
        "final_status",
        "diagnose_issue_count",
        "unsafe_blocks",
        "raw_ptr_count",
        "unsafe_api_count",
        "iteration_count",
        "patch_rounds",
        "rollback_count",
        "total_ms",
        "retrieve_ms",
        "generate_ms",
        "execute_ms",
        "primary_error_kind",
        "final_stop_reason",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in columns})


if __name__ == "__main__":
    main()

