import os
import time
from pathlib import Path

import psycopg
import pytest

from embed.service import Chunk, batch_embed_and_upsert
from retrieval.service import hybrid_retrieve_evidence


def _dsn() -> str:
    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        pytest.skip("DATABASE_URL/POSTGRES_DSN not set")
    return dsn


def test_hybrid_retrieve_structure_and_filtering(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_MODEL_ID", "stub-1536")
    dsn = _dsn()
    root_dir = Path(__file__).resolve().parents[1]
    sql_path = root_dir / "retrieval" / "sql" / "lexical_search.sql"
    with open(sql_path, "r", encoding="utf-8") as f:
        fn_sql = f.read()
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(fn_sql)
                cur.execute("INSERT INTO projects (name) VALUES ('hyb') RETURNING project_id;")
                pid = cur.fetchone()[0]
                cur.execute("INSERT INTO repo_snapshots (project_id, commit_sha) VALUES (%s, 'hyb') RETURNING snapshot_id;", (pid,))
                sid = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO code_chunks (snapshot_id, kind, lang, content, content_tsv, meta, content_hash)
                    VALUES
                      (%s,'rust_baseline','rust','borrow checker unsafe',to_tsvector('simple','borrow checker unsafe'),'{"file":"a"}','h1'),
                      (%s,'idiom_template','rust','borrow checker safe',to_tsvector('simple','borrow checker safe'),'{"file":"b"}','h2'),
                      (%s,'other','rust','unrelated',to_tsvector('simple','unrelated'),'{"file":"c"}','h3')
                    RETURNING chunk_id;
                    """,
                    (sid, sid, sid),
                )
                ids = [r[0] for r in cur.fetchall()]

    written = batch_embed_and_upsert(
        chunks=[Chunk(chunk_id=int(ids[0]), content="borrow checker unsafe"), Chunk(chunk_id=int(ids[1]), content="borrow checker safe"), Chunk(chunk_id=int(ids[2]), content="unrelated")],
        model_id="stub-1536",
        snapshot_id=int(sid),
    )
    assert written == 3

    pack = hybrid_retrieve_evidence(
        snapshot_id=int(sid),
        query_text="borrow checker unsafe",
        filters={"kind": ["rust_baseline", "idiom_template"]},
        top_k=5,
    )

    assert "rrf_config" in pack
    assert "items" in pack
    assert all(item["kind"] in {"rust_baseline", "idiom_template"} for item in pack["items"])
    for item in pack["items"]:
        assert len(item["excerpt"]) <= 200
        assert "score" in item
        assert "rrf" in item["score"]
        assert "lexical_rank" in item["score"]
        assert "vector_rank" in item["score"]


@pytest.mark.skipif(os.getenv("RUN_RETRIEVAL_PERF_TEST") != "1", reason="set RUN_RETRIEVAL_PERF_TEST=1 to run")
def test_hybrid_service_p95_latency(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_MODEL_ID", "stub-1536")
    dsn = _dsn()
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("INSERT INTO projects (name) VALUES ('hybperf') ON CONFLICT DO NOTHING RETURNING project_id;")
                row = cur.fetchone()
                if row:
                    pid = row[0]
                else:
                    cur.execute("SELECT project_id FROM projects WHERE name = 'hybperf';")
                    pid = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO repo_snapshots (project_id, commit_sha) VALUES (%s, 'hybperf') ON CONFLICT DO NOTHING RETURNING snapshot_id;",
                    (pid,),
                )
                row = cur.fetchone()
                if row:
                    sid = row[0]
                else:
                    cur.execute("SELECT snapshot_id FROM repo_snapshots WHERE project_id = %s AND commit_sha = 'hybperf';", (pid,))
                    sid = cur.fetchone()[0]

    times = []
    for _ in range(30):
        t0 = time.perf_counter()
        _ = hybrid_retrieve_evidence(snapshot_id=int(sid), query_text="borrow checker unsafe", filters={"kind": ["rust_baseline"]}, top_k=20)
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    p95 = times[int(len(times) * 0.95) - 1]
    assert p95 <= 200.0
