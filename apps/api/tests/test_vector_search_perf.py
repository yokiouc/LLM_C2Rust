import os
import time

import psycopg
import pytest


@pytest.mark.skipif(os.getenv("RUN_VECTOR_PERF_TEST") != "1", reason="set RUN_VECTOR_PERF_TEST=1 to run")
def test_vector_search_perf_placeholder():
    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        pytest.skip("DATABASE_URL/POSTGRES_DSN not set")

    n = int(os.getenv("VECTOR_PERF_N", "10000"))
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("INSERT INTO projects (name) VALUES ('perf') ON CONFLICT DO NOTHING RETURNING project_id;")
                row = cur.fetchone()
                if row:
                    project_id = row[0]
                else:
                    cur.execute("SELECT project_id FROM projects WHERE name = 'perf';")
                    project_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO repo_snapshots (project_id, commit_sha) VALUES (%s, 'perf') ON CONFLICT DO NOTHING RETURNING snapshot_id;",
                    (project_id,),
                )
                row = cur.fetchone()
                if row:
                    snapshot_id = row[0]
                else:
                    cur.execute("SELECT snapshot_id FROM repo_snapshots WHERE project_id = %s AND commit_sha = 'perf';", (project_id,))
                    snapshot_id = cur.fetchone()[0]

                cur.execute("DELETE FROM chunk_embeddings WHERE snapshot_id = %s;", (snapshot_id,))
                cur.execute("DELETE FROM code_chunks WHERE snapshot_id = %s;", (snapshot_id,))

                cur.execute(
                    """
                    INSERT INTO code_chunks (snapshot_id, kind, lang, content, content_tsv, meta, content_hash)
                    SELECT
                      %s, 'k', 'rust', 'x' || gs::text, to_tsvector('simple', 'x'), '{"file":"f"}', md5(gs::text)
                    FROM generate_series(1, %s) AS gs
                    RETURNING chunk_id;
                    """,
                    (snapshot_id, n),
                )
                chunk_ids = [r[0] for r in cur.fetchall()]

                vec = "[" + ",".join(["0"] * 1536) + "]"
                cur.execute(
                    "INSERT INTO chunk_embeddings (chunk_id, model_id, snapshot_id, embedding) SELECT unnest(%s::bigint[]), 'stub-1536', %s, %s::vector ON CONFLICT (chunk_id, model_id) DO UPDATE SET embedding = EXCLUDED.embedding, updated_at = now();",
                    (chunk_ids, snapshot_id, vec),
                )

        with conn.cursor() as cur:
            t0 = time.perf_counter()
            cur.execute(
                "SELECT chunk_id, embedding <=> %s::vector AS dist FROM chunk_embeddings WHERE snapshot_id = %s ORDER BY dist ASC LIMIT 10;",
                (vec, snapshot_id),
            )
            _ = cur.fetchall()
            ms = (time.perf_counter() - t0) * 1000

    assert ms < float(os.getenv("VECTOR_PERF_MS", "200"))
