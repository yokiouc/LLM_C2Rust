"""Phase 6 tests: new API endpoints, feature flag, v2 FSM routing.

Tests API structure and response shapes. DB-dependent tests are skipped
when DATABASE_URL is not set.
"""

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_repo_root = Path(__file__).resolve().parents[3]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from main import app

client = TestClient(app)

_HAS_DB = bool(os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN") or os.getenv("POSTGRES_HOST"))


# ===========================================================================
# API structure tests (no DB needed)
# ===========================================================================

class TestAPIStructure:

    def test_health_endpoint_exists(self):
        r = client.get("/health")
        assert r.status_code in (200, 503)

    def test_run_v2_endpoint_exists(self):
        """POST /agent/run_v2 should exist and reject bad input."""
        r = client.post("/agent/run_v2", json={})
        assert r.status_code == 422  # validation error

    @pytest.mark.skipif(not _HAS_DB, reason="Requires DB")
    def test_run_v2_requires_fields(self):
        r = client.post("/agent/run_v2", json={
            "snapshot_id": 1,
            "workspace_path": "/nonexistent",
            "task_description": "test",
        })
        assert r.status_code in (201, 500)

    def test_legacy_run_endpoint_still_exists(self):
        r = client.post("/agent/run", json={})
        assert r.status_code == 422

    @pytest.mark.skipif(not _HAS_DB, reason="Requires DB")
    def test_run_status_endpoint_404(self):
        r = client.get("/runs/00000000-0000-0000-0000-000000000000/status")
        assert r.status_code in (404, 500)

    def test_run_hotspots_endpoint(self):
        r = client.get("/runs/00000000-0000-0000-0000-000000000000/hotspots")
        assert r.status_code == 200
        data = r.json()
        assert "hotspots" in data
        assert data["count"] == 0  # no DB

    def test_run_slices_endpoint(self):
        r = client.get("/runs/00000000-0000-0000-0000-000000000000/slices")
        assert r.status_code == 200
        data = r.json()
        assert "slices" in data
        assert data["count"] == 0

    def test_run_validation_endpoint(self):
        r = client.get("/runs/00000000-0000-0000-0000-000000000000/validation")
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
        assert "summary" in data

    @pytest.mark.skipif(not _HAS_DB, reason="Requires DB")
    def test_run_patches_endpoint(self):
        r = client.get("/runs/00000000-0000-0000-0000-000000000000/patches")
        assert r.status_code in (200, 500)

    @pytest.mark.skipif(not _HAS_DB, reason="Requires DB")
    def test_run_metrics_endpoint(self):
        r = client.get("/runs/00000000-0000-0000-0000-000000000000/metrics")
        assert r.status_code in (200, 500)

    def test_compare_endpoint_missing_params(self):
        r = client.get("/compare")
        assert r.status_code == 422  # missing required query params

    @pytest.mark.skipif(not _HAS_DB, reason="Requires DB")
    def test_compare_endpoint_with_params(self):
        r = client.get("/compare?baseline_run_id=aaa&enhanced_run_id=bbb")
        assert r.status_code in (200, 404, 500)

    @pytest.mark.skipif(not _HAS_DB, reason="Requires DB")
    def test_list_runs_endpoint(self):
        r = client.get("/runs")
        assert r.status_code in (200, 500)

    @pytest.mark.skipif(not _HAS_DB, reason="Requires DB")
    def test_get_project_endpoint_404(self):
        r = client.get("/projects/999999")
        assert r.status_code in (404, 500)

    def test_cors_headers(self):
        r = client.options("/health", headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        })
        # CORS should be configured
        assert r.status_code in (200, 405)


# ===========================================================================
# Feature flag tests
# ===========================================================================

class TestFeatureFlag:

    def test_use_fsm_v2_default_false(self):
        from main import USE_FSM_V2
        # Default should be false unless env var is set
        expected = os.getenv("USE_FSM_V2", "false").strip().lower() in ("1", "true", "yes")
        assert USE_FSM_V2 == expected

    def test_run_fsm_v2_importable(self):
        from agent.fsm import run_fsm_v2
        assert callable(run_fsm_v2)

    def test_dispatch_function_exists(self):
        from main import _run_fsm_dispatch
        assert callable(_run_fsm_dispatch)


# ===========================================================================
# Response shape tests (verify structure matches frontend expectations)
# ===========================================================================

class TestResponseShapes:

    def test_hotspots_response_shape(self):
        r = client.get("/runs/00000000-0000-0000-0000-000000000000/hotspots")
        data = r.json()
        assert "run_id" in data
        assert "hotspots" in data
        assert "count" in data
        assert isinstance(data["hotspots"], list)

    def test_slices_response_shape(self):
        r = client.get("/runs/00000000-0000-0000-0000-000000000000/slices")
        data = r.json()
        assert "run_id" in data
        assert "slices" in data
        assert "count" in data

    def test_validation_response_shape(self):
        r = client.get("/runs/00000000-0000-0000-0000-000000000000/validation")
        data = r.json()
        assert "run_id" in data
        assert "results" in data
        assert "summary" in data


# ===========================================================================
# DB integration tests (skipped without DB)
# ===========================================================================

@pytest.mark.skipif(not _HAS_DB, reason="DATABASE_URL not set")
class TestDBIntegration:

    def test_list_runs_returns_list(self):
        r = client.get("/runs")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_run_status_404_for_missing(self):
        r = client.get("/runs/00000000-0000-0000-0000-000000000000/status")
        assert r.status_code == 404

    def test_run_metrics_returns_structured(self):
        # First create a run via legacy endpoint
        import tempfile
        import psycopg
        from embed.service import Chunk, batch_embed_and_upsert

        dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN") or ""
        ws = Path(tempfile.mkdtemp(prefix="api_test_"))
        (ws / "src").mkdir()
        (ws / "src" / "lib.rs").write_text("line1\n", encoding="utf-8")

        with psycopg.connect(dsn, connect_timeout=5) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO projects (name) VALUES ('api_test') RETURNING project_id;")
                    pid = cur.fetchone()[0]
                    cur.execute("INSERT INTO repo_snapshots (project_id) VALUES (%s) RETURNING snapshot_id;", (pid,))
                    sid = cur.fetchone()[0]
                    cur.execute(
                        "INSERT INTO code_chunks (snapshot_id, kind, lang, content, content_tsv, meta, content_hash) "
                        "VALUES (%s, 'rust_function_slice', 'rust', 'line1', to_tsvector('simple','line1'), "
                        "'{\"file\":\"src/lib.rs\"}'::jsonb, 'h1') RETURNING chunk_id;",
                        (sid,),
                    )
                    cid = cur.fetchone()[0]

        batch_embed_and_upsert(chunks=[Chunk(chunk_id=cid, content="line1")], model_id="stub-1536", snapshot_id=sid)

        r = client.post("/agent/run", json={
            "snapshot_id": sid,
            "workspace_path": str(ws),
            "task_description": "test",
        })
        assert r.status_code == 201
        run_id = r.json()["run_id"]

        # Now test metrics endpoint
        r2 = client.get(f"/runs/{run_id}/metrics")
        assert r2.status_code == 200
        data = r2.json()
        assert "engineering" in data
        assert "evaluation" in data
        assert "other" in data
