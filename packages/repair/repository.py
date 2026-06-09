"""Repair repository: validation results and patch rollbacks.

All DB access uses packages.core.db.connect (canonical path).
"""

from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from packages.core.db import connect


# ---------------------------------------------------------------------------
# Validation Results
# ---------------------------------------------------------------------------

def create_validation_result(
    conn: Connection,
    *,
    run_id: str,
    patch_id: str | None = None,
    stage: str,
    status: str = "pending",
    exit_code: int | None = None,
    duration_ms: int | None = None,
    issue_count: int = 0,
    issue_kind: str | None = None,
    parsed_issues: list[dict] | None = None,
    stdout_path: str | None = None,
    stderr_path: str | None = None,
    compared_against: str | None = None,
    output: dict | None = None,
) -> int:
    """Insert a validation result and return its id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO validation_results
              (run_id, patch_id, stage, status, exit_code, duration_ms,
               issue_count, issue_kind, parsed_issues,
               stdout_path, stderr_path, compared_against, output)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (
                run_id, patch_id, stage, status, exit_code, duration_ms,
                issue_count, issue_kind, Jsonb(parsed_issues or []),
                stdout_path, stderr_path, compared_against, Jsonb(output or {}),
            ),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("create_validation_result_failed")
        return int(row[0])


def list_validation_results(
    conn: Connection,
    *,
    run_id: str | None = None,
    patch_id: str | None = None,
    stage: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List validation results with optional filters."""
    conditions: list[str] = []
    params: list[Any] = []

    if run_id is not None:
        conditions.append("run_id = %s")
        params.append(run_id)
    if patch_id is not None:
        conditions.append("patch_id = %s")
        params.append(patch_id)
    if stage is not None:
        conditions.append("stage = %s")
        params.append(stage)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    params.extend([limit, offset])

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id, run_id, patch_id, stage, status, exit_code,
                   duration_ms, issue_count, issue_kind,
                   parsed_issues, stdout_path, stderr_path,
                   compared_against, output, created_at
            FROM validation_results
            {where}
            ORDER BY created_at ASC, id ASC
            LIMIT %s OFFSET %s;
            """,
            params,
        )
        return cur.fetchall()


def get_validation_result(conn: Connection, *, result_id: int) -> dict[str, Any] | None:
    """Get a single validation result by id."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, run_id, patch_id, stage, status, exit_code,
                   duration_ms, issue_count, issue_kind,
                   parsed_issues, stdout_path, stderr_path,
                   compared_against, output, created_at
            FROM validation_results WHERE id = %s;
            """,
            (result_id,),
        )
        return cur.fetchone()


def get_validation_summary(
    conn: Connection,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Get a summary of all validation stages for a run.

    Returns a dict with keys: build, test, clippy, fmt
    Each value is the latest result for that stage or None.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (stage)
                   id, stage, status, exit_code, duration_ms,
                   issue_count, issue_kind, created_at
            FROM validation_results
            WHERE run_id = %s
            ORDER BY stage, created_at DESC;
            """,
            (run_id,),
        )
        rows = cur.fetchall()

    summary: dict[str, Any] = {"build": None, "test": None, "clippy": None, "fmt": None}
    for row in rows:
        stage = str(row.get("stage") or "")
        if stage in summary:
            summary[stage] = dict(row)
    return summary


# ---------------------------------------------------------------------------
# Patch Rollbacks
# ---------------------------------------------------------------------------

def create_rollback(
    conn: Connection,
    *,
    run_id: str,
    patch_id: str,
    rollback_reason: str = "",
    rollback_detail: dict | None = None,
    backup_path: str | None = None,
) -> int:
    """Record a patch rollback event and return its id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO patch_rollbacks
              (run_id, patch_id, rollback_reason, rollback_detail, backup_path)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (run_id, patch_id, rollback_reason, Jsonb(rollback_detail or {}), backup_path),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("create_rollback_failed")
        return int(row[0])


def list_rollbacks(
    conn: Connection,
    *,
    run_id: str | None = None,
    patch_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List rollback events with optional filters."""
    conditions: list[str] = []
    params: list[Any] = []

    if run_id is not None:
        conditions.append("run_id = %s")
        params.append(run_id)
    if patch_id is not None:
        conditions.append("patch_id = %s")
        params.append(patch_id)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    params.extend([limit, offset])

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id, run_id, patch_id, rollback_reason,
                   rollback_detail, backup_path, created_at
            FROM patch_rollbacks
            {where}
            ORDER BY created_at ASC, id ASC
            LIMIT %s OFFSET %s;
            """,
            params,
        )
        return cur.fetchall()
