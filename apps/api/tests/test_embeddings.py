import asyncio
import json
import os

import psycopg
import pytest
from typer.testing import CliRunner

from cli import app
from embed.providers import StubProvider


def _dsn() -> str:
    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        pytest.skip("DATABASE_URL/POSTGRES_DSN not set")
    return dsn


def test_stub_provider_dimension():
    p = StubProvider(dimension=1536, seed=1)
    v = p.embed(["a", "b"])
    assert len(v) == 2
    assert len(v[0]) == 1536
    assert len(v[1]) == 1536
    v2 = asyncio.run(p.aembed(["a"]))
    assert len(v2) == 1
    assert len(v2[0]) == 1536


def test_embedding_upsert_idempotent_and_topk_order():
    dsn = _dsn()
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("INSERT INTO projects (name) VALUES ('p') RETURNING project_id;")
                project_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO repo_snapshots (project_id, commit_sha) VALUES (%s, 's') RETURNING snapshot_id;",
                    (project_id,),
                )
                snapshot_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO code_chunks (snapshot_id, kind, lang, content, content_tsv, meta, content_hash)
                    VALUES
                      (%s,'rust_baseline','rust','aaa',to_tsvector('simple','aaa'),'{"file":"a.rs"}','h1'),
                      (%s,'rust_baseline','rust','bbb',to_tsvector('simple','bbb'),'{"file":"b.rs"}','h2'),
                      (%s,'rust_baseline','rust','ccc',to_tsvector('simple','ccc'),'{"file":"c.rs"}','h3')
                    RETURNING chunk_id;
                    """,
                    (snapshot_id, snapshot_id, snapshot_id),
                )
                chunk_ids = [r[0] for r in cur.fetchall()]

    runner = CliRunner()
    env = os.environ.copy()
    env["DATABASE_URL"] = dsn

    r = runner.invoke(app, ["embed_chunks", "--model_id", "stub-1536", "--snapshot_id", str(snapshot_id), "--chunk_table", "code_chunks"], env=env)
    assert r.exit_code == 0
    written1 = json.loads(r.stdout)["written"]
    assert written1 == 3

    r = runner.invoke(app, ["embed_chunks", "--model_id", "stub-1536", "--snapshot_id", str(snapshot_id), "--chunk_table", "code_chunks"], env=env)
    assert r.exit_code == 0
    written2 = json.loads(r.stdout)["written"]
    assert written2 == 3

    r = runner.invoke(app, ["vector_search", "--model_id", "stub-1536", "--snapshot_id", str(snapshot_id), "--query_text", "aaa", "--top_k", "2"], env=env)
    assert r.exit_code == 0
    results = json.loads(r.stdout)
    assert len(results) == 2
    assert results[0]["chunk_id"] == chunk_ids[0]
    assert results[0]["dist"] <= results[1]["dist"]


def test_snapshot_filtering():
    dsn = _dsn()
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("INSERT INTO projects (name) VALUES ('p2') RETURNING project_id;")
                project_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO repo_snapshots (project_id, commit_sha) VALUES (%s, 's1') RETURNING snapshot_id;",
                    (project_id,),
                )
                s1 = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO repo_snapshots (project_id, commit_sha) VALUES (%s, 's2') RETURNING snapshot_id;",
                    (project_id,),
                )
                s2 = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO code_chunks (snapshot_id, kind, lang, content, content_tsv, meta, content_hash) VALUES (%s,'k','rust','same',to_tsvector('simple','same'),'{\"file\":\"a\"}','ha') RETURNING chunk_id;",
                    (s1,),
                )
                c1 = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO code_chunks (snapshot_id, kind, lang, content, content_tsv, meta, content_hash) VALUES (%s,'k','rust','same',to_tsvector('simple','same'),'{\"file\":\"b\"}','hb') RETURNING chunk_id;",
                    (s2,),
                )
                _ = cur.fetchone()[0]

    runner = CliRunner()
    env = os.environ.copy()
    env["DATABASE_URL"] = dsn

    r = runner.invoke(app, ["embed_chunks", "--model_id", "stub-1536", "--snapshot_id", str(s1)], env=env)
    assert r.exit_code == 0
    r = runner.invoke(app, ["embed_chunks", "--model_id", "stub-1536", "--snapshot_id", str(s2)], env=env)
    assert r.exit_code == 0

    r = runner.invoke(app, ["vector_search", "--model_id", "stub-1536", "--snapshot_id", str(s1), "--query_text", "same", "--top_k", "10"], env=env)
    assert r.exit_code == 0
    results = json.loads(r.stdout)
    assert results
    assert all(item["chunk_id"] == c1 for item in results)
