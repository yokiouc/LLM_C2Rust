"""Evidence repository: hotspots, repair slices, evidence links.

All DB access uses packages.core.db.connect (canonical path).
"""

from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from packages.core.db import connect


# ---------------------------------------------------------------------------
# Hotspots
# ---------------------------------------------------------------------------

def create_hotspot(
    conn: Connection,
    *,
    run_id: str | None,
    snapshot_id: int | None,
    file_path: str,
    symbol: str | None = None,
    start_line: int,
    end_line: int,
    hotspot_kind: str,
    risk_score: float = 0.0,
    risk_level: str = "low",
    risk_tags: list[str] | None = None,
    unsafe_count: int = 0,
    raw_ptr_count: int = 0,
    content: str = "",
) -> int:
    """Insert a hotspot and return its id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO hotspots
              (run_id, snapshot_id, file_path, symbol, start_line, end_line,
               hotspot_kind, risk_score, risk_level, risk_tags,
               unsafe_count, raw_ptr_count, content)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (
                run_id, snapshot_id, file_path, symbol,
                start_line, end_line, hotspot_kind,
                risk_score, risk_level, Jsonb(risk_tags or []),
                unsafe_count, raw_ptr_count, content,
            ),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("create_hotspot_failed")
        return int(row[0])


def list_hotspots(
    conn: Connection,
    *,
    run_id: str | None = None,
    snapshot_id: int | None = None,
    file_path: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List hotspots with optional filters."""
    conditions: list[str] = []
    params: list[Any] = []

    if run_id is not None:
        conditions.append("run_id = %s")
        params.append(run_id)
    if snapshot_id is not None:
        conditions.append("snapshot_id = %s")
        params.append(snapshot_id)
    if file_path is not None:
        conditions.append("file_path = %s")
        params.append(file_path)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    params.extend([limit, offset])

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id, run_id, snapshot_id, file_path, symbol,
                   start_line, end_line, hotspot_kind,
                   risk_score, risk_level, risk_tags,
                   unsafe_count, raw_ptr_count, content, created_at
            FROM hotspots
            {where}
            ORDER BY risk_score DESC, id ASC
            LIMIT %s OFFSET %s;
            """,
            params,
        )
        return cur.fetchall()


def get_hotspot(conn: Connection, *, hotspot_id: int) -> dict[str, Any] | None:
    """Get a single hotspot by id."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, run_id, snapshot_id, file_path, symbol,
                   start_line, end_line, hotspot_kind,
                   risk_score, risk_level, risk_tags,
                   unsafe_count, raw_ptr_count, content, created_at
            FROM hotspots WHERE id = %s;
            """,
            (hotspot_id,),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Repair Slices
# ---------------------------------------------------------------------------

def create_slice(
    conn: Connection,
    *,
    hotspot_id: int,
    run_id: str | None = None,
    file_path: str,
    symbol: str | None = None,
    slice_start: int,
    slice_end: int,
    anchor_line: int | None = None,
    signature_text: str | None = None,
    signature_line: int | None = None,
    content: str = "",
    keep_signature: bool = True,
    no_global_rename: bool = True,
    min_patch: bool = True,
    forbidden_regions: list[dict] | None = None,
    related_vars: list[str] | None = None,
    related_unsafe_ops: list[str] | None = None,
) -> int:
    """Insert a repair slice and return its id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO repair_slices
              (hotspot_id, run_id, file_path, symbol,
               slice_start, slice_end, anchor_line,
               signature_text, signature_line, content,
               keep_signature, no_global_rename, min_patch,
               forbidden_regions, related_vars, related_unsafe_ops)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (
                hotspot_id, run_id, file_path, symbol,
                slice_start, slice_end, anchor_line,
                signature_text, signature_line, content,
                keep_signature, no_global_rename, min_patch,
                Jsonb(forbidden_regions or []),
                Jsonb(related_vars or []),
                Jsonb(related_unsafe_ops or []),
            ),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("create_slice_failed")
        return int(row[0])


def list_slices(
    conn: Connection,
    *,
    run_id: str | None = None,
    hotspot_id: int | None = None,
    file_path: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List repair slices with optional filters."""
    conditions: list[str] = []
    params: list[Any] = []

    if run_id is not None:
        conditions.append("run_id = %s")
        params.append(run_id)
    if hotspot_id is not None:
        conditions.append("hotspot_id = %s")
        params.append(hotspot_id)
    if file_path is not None:
        conditions.append("file_path = %s")
        params.append(file_path)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    params.extend([limit, offset])

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id, hotspot_id, run_id, file_path, symbol,
                   slice_start, slice_end, anchor_line,
                   signature_text, signature_line, content,
                   keep_signature, no_global_rename, min_patch,
                   forbidden_regions, related_vars, related_unsafe_ops,
                   created_at
            FROM repair_slices
            {where}
            ORDER BY id ASC
            LIMIT %s OFFSET %s;
            """,
            params,
        )
        return cur.fetchall()


def get_slice(conn: Connection, *, slice_id: int) -> dict[str, Any] | None:
    """Get a single repair slice by id."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, hotspot_id, run_id, file_path, symbol,
                   slice_start, slice_end, anchor_line,
                   signature_text, signature_line, content,
                   keep_signature, no_global_rename, min_patch,
                   forbidden_regions, related_vars, related_unsafe_ops,
                   created_at
            FROM repair_slices WHERE id = %s;
            """,
            (slice_id,),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Evidence Links
# ---------------------------------------------------------------------------

def link_evidence(
    conn: Connection,
    *,
    slice_id: int,
    chunk_id: int,
    score: float = 0.0,
    rank: int = 0,
    link_type: str = "retrieval",
) -> int:
    """Link a repair slice to an evidence chunk. Returns link id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evidence_links (slice_id, chunk_id, score, rank, link_type)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (slice_id, chunk_id) DO UPDATE
              SET score = EXCLUDED.score, rank = EXCLUDED.rank, link_type = EXCLUDED.link_type
            RETURNING id;
            """,
            (slice_id, chunk_id, score, rank, link_type),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("link_evidence_failed")
        return int(row[0])


def list_evidence_links(
    conn: Connection,
    *,
    slice_id: int,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List evidence links for a given slice."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT el.id, el.slice_id, el.chunk_id, el.score, el.rank, el.link_type,
                   cc.kind, cc.lang, left(cc.content, 200) AS excerpt, cc.meta
            FROM evidence_links el
            JOIN code_chunks cc ON cc.chunk_id = el.chunk_id
            WHERE el.slice_id = %s
            ORDER BY el.rank ASC, el.score DESC
            LIMIT %s;
            """,
            (slice_id, limit),
        )
        return cur.fetchall()
