import os
import tempfile
import threading
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient

from agent.fsm import run_fsm
from embed.service import Chunk, batch_embed_and_upsert
from main import app


def _dsn() -> str:
    return os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN") or ""


def _setup_workspace_and_snapshot(*, name: str) -> tuple[int, str]:
    dsn = _dsn()
    base_dir = Path(tempfile.mkdtemp(prefix=f"agent_ws_{name}_")).resolve()
    (base_dir / "src").mkdir(parents=True, exist_ok=True)
    (base_dir / "src" / "lib.rs").write_text("line1\nline2\n", encoding="utf-8", newline="\n")

    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("INSERT INTO projects (name) VALUES (%s) RETURNING project_id;", (f"agent_{name}",))
                row = cur.fetchone()
                assert row
                pid = int(row[0])
                cur.execute("INSERT INTO repo_snapshots (project_id, commit_sha) VALUES (%s, %s) RETURNING snapshot_id;", (pid, f"agent_{name}"))
                row = cur.fetchone()
                assert row
                sid = int(row[0])
                cur.execute(
                    """
                    INSERT INTO code_chunks (snapshot_id, kind, lang, content, content_tsv, meta, content_hash)
                    VALUES (%s,'rust_function_slice','rust',%s,to_tsvector('simple',%s),%s,'h1')
                    RETURNING chunk_id;
                    """,
                    (
                        sid,
                        "line1\nline2\n",
                        "line1\nline2\n",
                        Jsonb({"file": "src/lib.rs"}),
                    ),
                )
                row = cur.fetchone()
                assert row
                chunk_id = int(row[0])

    written = batch_embed_and_upsert(chunks=[Chunk(chunk_id=chunk_id, content="line1\nline2\n")], model_id="stub-1536", snapshot_id=sid)
    assert written == 1
    return sid, str(base_dir)


def test_agent_run_api_creates_steps_and_patch(database_url: str):
    os.environ["RETRIEVAL_MODEL_ID"] = "stub-1536"
    sid, ws = _setup_workspace_and_snapshot(name="ok")
    client = TestClient(app)
    r = client.post("/agent/run", json={"snapshot_id": sid, "workspace_path": ws, "task_description": "line1"})
    assert r.status_code == 201
    payload = r.json()
    assert "run_id" in payload

    run_id = payload["run_id"]
    r2 = client.get(f"/runs/{run_id}")
    assert r2.status_code == 200
    rec = r2.json()
    assert rec["run_id"] == run_id
    assert len(rec["steps"]) == 6
    assert len(rec["patches"]) == 1
    diff = rec["patches"][0]["unified_diff"]
    assert "--- a/" in diff and "+++ b/" in diff and "@@ " in diff
    assert rec["summary"]["evidence_top"]
    first = rec["summary"]["evidence_top"][0]
    assert "meta" in first
    assert "evidence_type" in first["meta"]
    assert "risk_tags" in first["meta"]
    assert "constraint_tags" in first["meta"]
    assert "api_tags" in first["meta"]

    with psycopg.connect(_dsn(), connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key FROM metrics WHERE run_id = %s ORDER BY key ASC;", (run_id,))
            keys = [r[0] for r in cur.fetchall()]
    assert "final_stop_reason" in keys
    assert "iteration_count" in keys
    assert "rollback_count" in keys
    assert "total_ms" in keys


def test_agent_run_apply_failure_records_rolled_back(database_url: str):
    os.environ["RETRIEVAL_MODEL_ID"] = "stub-1536"
    sid, ws = _setup_workspace_and_snapshot(name="applyfail")
    rec = run_fsm({"snapshot_id": sid, "workspace_path": ws, "task_description": "line1", "force_invalid_diff": True})
    client = TestClient(app)
    r2 = client.get(f"/runs/{rec.run_id}")
    assert r2.status_code == 200
    data = r2.json()
    assert data["status"] in {"FAILED", "STOP"}
    assert len(data["patches"]) == 1
    assert data["patches"][0]["status"] == "rolled_back"
    assert data["patches"][0]["error_msg"]


def test_concurrent_runs_are_mutexed(database_url: str):
    prev_model = os.environ.get("RETRIEVAL_MODEL_ID")
    prev_scenario = os.environ.get("MOCK_SCENARIO")
    os.environ["RETRIEVAL_MODEL_ID"] = "stub-1536"
    os.environ["MOCK_SCENARIO"] = "timeout"
    sid, ws = _setup_workspace_and_snapshot(name="lock")
    results = []
    errors = []

    def worker():
        try:
            results.append(run_fsm({"snapshot_id": sid, "workspace_path": ws, "task_description": "line1", "timeout": 1}))
        except Exception as e:
            errors.append(str(e))

    try:
        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        if prev_model is None:
            os.environ.pop("RETRIEVAL_MODEL_ID", None)
        else:
            os.environ["RETRIEVAL_MODEL_ID"] = prev_model
        if prev_scenario is None:
            os.environ.pop("MOCK_SCENARIO", None)
        else:
            os.environ["MOCK_SCENARIO"] = prev_scenario

    assert len(results) == 1
    assert len(errors) == 9
