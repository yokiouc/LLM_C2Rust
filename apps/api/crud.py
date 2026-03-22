import hashlib
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def create_project(conn: Connection, *, name: str, description: str | None) -> int:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO projects (name, description) VALUES (%s, %s) RETURNING project_id;",
                (name, description),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("create_project_failed")
            project_id = row[0]
    return int(project_id)


def delete_project(conn: Connection, *, project_id: int) -> bool:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE project_id = %s RETURNING project_id;", (project_id,))
            row = cur.fetchone()
    return row is not None


def get_project(conn: Connection, *, project_id: int) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT project_id, name, description, created_at FROM projects WHERE project_id = %s;",
            (project_id,),
        )
        row = cur.fetchone()
    return row


def list_projects(conn: Connection, *, limit: int, offset: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT project_id, name, description, created_at FROM projects ORDER BY project_id LIMIT %s OFFSET %s;",
            (limit, offset),
        )
        rows = cur.fetchall()
    return rows


def create_snapshot(
    conn: Connection,
    *,
    project_id: int,
    commit_sha: str | None,
    branch: str | None,
) -> int:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO repo_snapshots (project_id, commit_sha, branch) VALUES (%s, %s, %s) RETURNING snapshot_id;",
                (project_id, commit_sha or "mock", branch),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("create_snapshot_failed")
            snapshot_id = row[0]
    return int(snapshot_id)


def delete_snapshot(conn: Connection, *, snapshot_id: int) -> bool:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM repo_snapshots WHERE snapshot_id = %s RETURNING snapshot_id;",
                (snapshot_id,),
            )
            row = cur.fetchone()
    return row is not None


def list_snapshots(conn: Connection, *, project_id: int, limit: int, offset: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT snapshot_id, project_id, commit_sha, branch, created_at
            FROM repo_snapshots
            WHERE project_id = %s
            ORDER BY snapshot_id
            LIMIT %s OFFSET %s;
            """,
            (project_id, limit, offset),
        )
        rows = cur.fetchall()
    return rows


def insert_chunk(
    conn: Connection,
    *,
    snapshot_id: int,
    kind: str,
    lang: str,
    content: str,
    meta: dict[str, Any],
) -> int:
    h = content_hash(content)
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO code_chunks (snapshot_id, kind, lang, content, content_tsv, meta, content_hash)
                VALUES (%s, %s, %s, %s, to_tsvector('simple', %s), %s, %s)
                RETURNING chunk_id;
                """,
                (snapshot_id, kind, lang, content, content, Jsonb(meta), h),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("insert_chunk_failed")
            chunk_id = row[0]
    return int(chunk_id)


def list_chunks(conn: Connection, *, snapshot_id: int, limit: int, offset: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT chunk_id, kind, lang, meta, created_at
            FROM code_chunks
            WHERE snapshot_id = %s
            ORDER BY chunk_id
            LIMIT %s OFFSET %s;
            """,
            (snapshot_id, limit, offset),
        )
        rows = cur.fetchall()
    return rows


def delete_chunk(conn: Connection, *, chunk_id: int) -> bool:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("DELETE FROM code_chunks WHERE chunk_id = %s RETURNING chunk_id;", (chunk_id,))
            row = cur.fetchone()
    return row is not None
