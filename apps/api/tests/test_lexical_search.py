import os
import time
from pathlib import Path

import psycopg
import pytest


def _dsn() -> str:
    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        pytest.skip("DATABASE_URL/POSTGRES_DSN not set")
    return dsn


def test_lexical_search_topn_and_latency():
    dsn = _dsn()
    root_dir = Path(__file__).resolve().parents[1]
    sql_path = root_dir / "retrieval" / "sql" / "lexical_search.sql"

    with open(sql_path, "r", encoding="utf-8") as f:
        fn_sql = f.read()

    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(fn_sql)
                cur.execute("INSERT INTO projects (name) VALUES ('lex') RETURNING project_id;")
                project_id = cur.fetchone()[0]
                cur.execute("INSERT INTO repo_snapshots (project_id, commit_sha) VALUES (%s, 'lex') RETURNING snapshot_id;", (project_id,))
                snapshot_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO code_chunks (snapshot_id, kind, lang, content, content_tsv, meta, content_hash)
                    VALUES
                      (%s,'rust_baseline','rust','borrow checker error unsafe',to_tsvector('simple','borrow checker error unsafe'),'{"file":"a"}','ha'),
                      (%s,'rust_baseline','rust','borrow checker',to_tsvector('simple','borrow checker'),'{"file":"b"}','hb'),
                      (%s,'rust_baseline','rust','something else',to_tsvector('simple','something else'),'{"file":"c"}','hc')
                    RETURNING chunk_id;
                    """,
                    (snapshot_id, snapshot_id, snapshot_id),
                )
                chunk_ids = [r[0] for r in cur.fetchall()]

        with conn.cursor() as cur:
            t0 = time.perf_counter()
            cur.execute("SELECT chunk_id, rank FROM lexical_search(%s, %s, %s, %s);", (snapshot_id, "borrow checker", ["rust_baseline"], 2))
            rows = cur.fetchall()
            ms = (time.perf_counter() - t0) * 1000

    assert ms < 100.0
    assert [r[0] for r in rows] == [chunk_ids[0], chunk_ids[1]]
