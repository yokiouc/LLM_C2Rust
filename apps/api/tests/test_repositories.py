"""Tests for packages/ repository modules.

Tests that require a real database are skipped when DATABASE_URL is not set.
Pure-logic tests (imports, type construction, safety metrics) run always.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure packages/ is importable
_repo_root = Path(__file__).resolve().parents[3]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


# ---------------------------------------------------------------------------
# Import tests — verify all repository modules load cleanly
# ---------------------------------------------------------------------------

class TestImports:
    def test_evidence_repository_imports(self):
        from packages.evidence.repository import (
            create_hotspot, list_hotspots, get_hotspot,
            create_slice, list_slices, get_slice,
            link_evidence, list_evidence_links,
        )
        assert callable(create_hotspot)
        assert callable(list_hotspots)
        assert callable(get_hotspot)
        assert callable(create_slice)
        assert callable(list_slices)
        assert callable(get_slice)
        assert callable(link_evidence)
        assert callable(list_evidence_links)

    def test_repair_repository_imports(self):
        from packages.repair.repository import (
            create_validation_result, list_validation_results,
            get_validation_result, get_validation_summary,
            create_rollback, list_rollbacks,
        )
        assert callable(create_validation_result)
        assert callable(list_validation_results)
        assert callable(get_validation_result)
        assert callable(get_validation_summary)
        assert callable(create_rollback)
        assert callable(list_rollbacks)

    def test_metrics_repository_imports(self):
        from packages.metrics.repository import (
            compute_safety_metrics, get_run_metrics,
            aggregate_runs, compare_baseline,
            list_run_pairs_for_comparison,
        )
        assert callable(compute_safety_metrics)
        assert callable(get_run_metrics)
        assert callable(aggregate_runs)
        assert callable(compare_baseline)
        assert callable(list_run_pairs_for_comparison)


# ---------------------------------------------------------------------------
# Core types tests
# ---------------------------------------------------------------------------

class TestCoreTypes:
    def test_hotspot_info_construction(self):
        from packages.core.types import HotspotInfo
        h = HotspotInfo(
            file="src/lib.rs",
            symbol="do_stuff",
            line_start=10,
            line_end=25,
            hotspot_kind="unsafe_block",
            risk_score=6,
            risk_tags=["unsafe", "raw_ptr"],
        )
        assert h.file == "src/lib.rs"
        assert h.risk_score == 6
        assert len(h.risk_tags) == 2

    def test_slice_info_construction(self):
        from packages.core.types import SliceInfo
        s = SliceInfo(
            file="src/lib.rs",
            start_line=8,
            end_line=30,
            anchor_line=15,
            symbol="do_stuff",
            signature_text="pub fn do_stuff(ptr: *mut i32) -> i32",
            signature_line=10,
            keep_signature=True,
            forbidden_regions=[{"start": 10, "end": 10, "reason": "signature"}],
            related_vars=["ptr"],
            related_unsafe_ops=["*ptr"],
        )
        assert s.keep_signature is True
        assert len(s.forbidden_regions) == 1

    def test_validation_result_construction(self):
        from packages.core.types import ValidationResult
        v = ValidationResult(
            phase="build",
            ok=True,
            exit_code=0,
            duration_ms=1200,
            parsed_issues=[],
            issue_count=0,
        )
        assert v.phase == "build"
        assert v.ok is True

    def test_safety_metrics_construction(self):
        from packages.core.types import SafetyMetrics
        m = SafetyMetrics(
            unsafe_block_count=3,
            raw_ptr_count=5,
            unsafe_api_count=1,
            manual_mem_call_count=2,
        )
        assert m.unsafe_block_count == 3
        assert m.manual_mem_call_count == 2


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------

class TestConstants:
    def test_agent_states_include_full_fsm(self):
        from packages.core.constants import AgentState
        required = {
            "INIT", "PRECHECK", "HOTSPOT_DISCOVERY", "SLICE_SELECT",
            "RETRIEVE_EVIDENCE", "BUILD_PROMPT", "GENERATE_PATCH",
            "VALIDATE_PATCH", "APPLY_PATCH", "RUN_BUILD", "RUN_TEST",
            "RUN_LINT", "DIAGNOSE", "SCORE_PROGRESS", "ROLLBACK",
            "SUCCESS", "STOP_NO_PROGRESS", "STOP_MAX_ITERS", "STOP_HARD_ERROR",
        }
        actual = {s.value for s in AgentState}
        assert required.issubset(actual), f"Missing states: {required - actual}"

    def test_evidence_types_complete(self):
        from packages.core.constants import EvidenceType
        required = {
            "rust_function_slice", "rust_unsafe_block", "rust_idiom_template",
            "replacement_strategy", "interface_constraint", "behavior_constraint",
            "compile_fix_hint", "c_symbol_summary", "c_resource_flow_summary",
        }
        actual = {e.value for e in EvidenceType}
        assert required == actual

    def test_hotspot_kinds_complete(self):
        from packages.core.constants import HotspotKind
        required = {
            "unsafe_block", "raw_ptr_deref", "ptr_arithmetic",
            "manual_mem_api", "memcpy_memmove", "cross_func_resource",
            "unsafe_fn_decl", "extern_call",
        }
        actual = {h.value for h in HotspotKind}
        assert required == actual

    def test_validation_phases(self):
        from packages.core.constants import ValidationPhase
        phases = {p.value for p in ValidationPhase}
        assert "cargo_build" in phases
        assert "cargo_test" in phases
        assert "cargo_clippy" in phases
        assert "cargo_fmt_check" in phases


# ---------------------------------------------------------------------------
# Safety metrics tests (file-based, no DB needed)
# ---------------------------------------------------------------------------

class TestSafetyMetrics:
    def test_compute_safety_metrics_on_demo_workspace(self):
        from packages.metrics.safety import compute_safety_metrics
        demo_ws = _repo_root / "demo_workspace"
        if not demo_ws.exists():
            pytest.skip("demo_workspace not found")
        m = compute_safety_metrics(demo_ws)
        assert m.total_lines > 0
        # demo_workspace should have some code
        assert m.unsafe_block_count >= 0
        assert m.raw_ptr_count >= 0

    def test_compute_safety_metrics_on_temp_dir(self):
        from packages.metrics.safety import compute_safety_metrics
        with tempfile.TemporaryDirectory() as td:
            rs = Path(td) / "src"
            rs.mkdir()
            (rs / "main.rs").write_text(
                "pub fn safe() { let x = 1; }\n"
                "pub unsafe fn risky() { let p: *const i32 = std::ptr::null(); }\n"
                "fn uses_ptr() { unsafe { let q: *mut u8 = malloc(10) as *mut u8; free(q as *mut _); } }\n",
                encoding="utf-8",
            )
            m = compute_safety_metrics(Path(td))
            assert m.total_lines == 3
            assert m.unsafe_block_count >= 1
            assert m.raw_ptr_count >= 1
            assert m.manual_mem_call_count >= 1

    def test_compute_rust_metrics_in_dir_compat(self):
        """Test backward-compatible dict API."""
        from packages.metrics.safety import compute_rust_metrics_in_dir
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "lib.rs").write_text("fn safe() {}\n", encoding="utf-8")
            d = compute_rust_metrics_in_dir(Path(td))
            assert "unsafe_blocks" in d
            assert "raw_ptr_count" in d
            assert "unsafe_api_count" in d
            assert "manual_mem_call_count" in d


# ---------------------------------------------------------------------------
# Comparison logic tests (pure logic, no DB)
# ---------------------------------------------------------------------------

class TestComparison:
    def test_build_comparison(self):
        from packages.metrics.compare import build_comparison

        result = build_comparison(
            project="test_proj",
            snapshot_id=1,
            baseline_metrics={
                "run_id": "aaa",
                "execute_ok": False,
                "final_status": "FAILED",
                "unsafe_blocks": 5,
                "raw_ptr_count": 3,
                "total_ms": 100,
            },
            enhanced_metrics={
                "run_id": "bbb",
                "execute_ok": True,
                "final_status": "OK",
                "unsafe_blocks": 2,
                "raw_ptr_count": 1,
                "total_ms": 500,
                "iteration_count": 3,
                "rollback_count": 1,
                "final_stop_reason": "success",
            },
        )
        assert result.project == "test_proj"
        assert result.baseline_compile_ok is False
        assert result.enhanced_compile_ok is True
        assert result.unsafe_blocks_delta == -3  # 2 - 5
        assert result.raw_ptr_delta == -2  # 1 - 3
        assert result.enhanced_iterations == 3
        assert result.enhanced_stop_reason == "success"


# ---------------------------------------------------------------------------
# Collector tests (pure logic, no DB)
# ---------------------------------------------------------------------------

class TestCollector:
    def test_build_run_metrics(self):
        from packages.metrics.collector import build_run_metrics
        m = build_run_metrics(
            iteration_count=3,
            patch_rounds=2,
            rollback_count=1,
            total_ms=5000,
        )
        assert m.iteration_count == 3
        assert m.rollback_count == 1

    def test_build_eval_metrics(self):
        from packages.metrics.collector import build_eval_metrics
        from packages.core.types import SafetyMetrics
        m = build_eval_metrics(
            compile_ok_before=False,
            compile_ok_after=True,
            safety_before=SafetyMetrics(unsafe_block_count=5, raw_ptr_count=3),
            safety_after=SafetyMetrics(unsafe_block_count=2, raw_ptr_count=1),
            final_stop_reason="success",
        )
        assert m.compile_ok_before is False
        assert m.compile_ok_after is True
        assert m.safety_before.unsafe_block_count == 5
        assert m.safety_after.raw_ptr_count == 1

    def test_metrics_to_db_pairs(self):
        from packages.metrics.collector import build_run_metrics, build_eval_metrics, metrics_to_db_pairs
        rm = build_run_metrics(total_ms=1000)
        em = build_eval_metrics(final_stop_reason="success")
        pairs = metrics_to_db_pairs(rm, em)
        keys = [k for k, v in pairs]
        assert "total_ms" in keys
        assert "final_stop_reason" in keys
        assert "unsafe_block_count_before" in keys
        assert "unsafe_block_count_after" in keys


# ---------------------------------------------------------------------------
# Evidence schema tests
# ---------------------------------------------------------------------------

class TestEvidenceSchema:
    def test_validate_meta_ok(self):
        from packages.evidence.schema import validate_meta
        errors = validate_meta({"file": "src/lib.rs", "evidence_type": "rust_function_slice"})
        assert errors == []

    def test_validate_meta_missing_file(self):
        from packages.evidence.schema import validate_meta
        errors = validate_meta({"evidence_type": "rust_function_slice"})
        assert any("file" in e for e in errors)

    def test_validate_meta_unknown_evidence_type(self):
        from packages.evidence.schema import validate_meta
        errors = validate_meta({"file": "x.rs", "evidence_type": "totally_fake"})
        assert any("unknown" in e for e in errors)

    def test_default_evidence_type_infer(self):
        from packages.evidence.schema import default_evidence_type
        assert default_evidence_type(kind="rust_function_slice", meta={}) == "rust_function_slice"
        assert default_evidence_type(kind="replacement_strategy", meta={}) == "replacement_strategy"
        assert default_evidence_type(kind="unknown", meta={}) == "code_slice"
        assert default_evidence_type(kind="x", meta={"evidence_type": "compile_fix_hint"}) == "compile_fix_hint"


# ---------------------------------------------------------------------------
# FSM states tests
# ---------------------------------------------------------------------------

class TestFSMStates:
    def test_terminal_states(self):
        from packages.repair.agent.states import is_terminal
        from packages.core.constants import AgentState
        assert is_terminal(AgentState.SUCCESS) is True
        assert is_terminal(AgentState.STOP_NO_PROGRESS) is True
        assert is_terminal(AgentState.STOP_MAX_ITERS) is True
        assert is_terminal(AgentState.STOP_HARD_ERROR) is True
        assert is_terminal(AgentState.INIT) is False
        assert is_terminal(AgentState.DIAGNOSE) is False

    def test_valid_transitions(self):
        from packages.repair.agent.states import validate_transition
        from packages.core.constants import AgentState
        assert validate_transition(AgentState.INIT, AgentState.HOTSPOT_DISCOVERY) is True
        assert validate_transition(AgentState.APPLY_PATCH, AgentState.RUN_BUILD) is True
        assert validate_transition(AgentState.RUN_BUILD, AgentState.RUN_TEST) is True
        assert validate_transition(AgentState.SUCCESS, AgentState.INIT) is False


# ---------------------------------------------------------------------------
# DB integration tests (skipped if DATABASE_URL not set)
# ---------------------------------------------------------------------------

_HAS_DB = bool(os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN") or os.getenv("POSTGRES_HOST"))


@pytest.mark.skipif(not _HAS_DB, reason="DATABASE_URL not set")
class TestDBIntegration:
    """Integration tests that require a real database with migration 006 applied."""

    def _setup_run(self, conn) -> tuple[str, int]:
        """Create a project, snapshot, and agent run for testing."""
        from uuid import uuid4
        with conn.cursor() as cur:
            cur.execute("INSERT INTO projects (name) VALUES (%s) RETURNING project_id;", (f"test_{uuid4().hex[:8]}",))
            project_id = cur.fetchone()[0]

            cur.execute(
                "INSERT INTO repo_snapshots (project_id, commit_sha) VALUES (%s, %s) RETURNING snapshot_id;",
                (project_id, "test_sha"),
            )
            snapshot_id = cur.fetchone()[0]

            run_id = str(uuid4())
            cur.execute(
                "INSERT INTO agent_runs (run_id, repo_url, ref, task_description, status) VALUES (%s, %s, %s, %s, %s);",
                (run_id, "test://repo", "main", "test task", "INIT"),
            )
        return run_id, snapshot_id

    def test_hotspot_crud(self):
        from packages.core.db import connect
        from packages.evidence.repository import create_hotspot, list_hotspots, get_hotspot

        with connect() as conn:
            with conn.transaction():
                run_id, snap_id = self._setup_run(conn)
                hid = create_hotspot(
                    conn,
                    run_id=run_id,
                    snapshot_id=snap_id,
                    file_path="src/lib.rs",
                    symbol="test_fn",
                    start_line=1,
                    end_line=10,
                    hotspot_kind="unsafe_block",
                    risk_score=6.0,
                    risk_level="high",
                    risk_tags=["unsafe", "raw_ptr"],
                    unsafe_count=2,
                    raw_ptr_count=1,
                )
                assert hid > 0

                rows = list_hotspots(conn, run_id=run_id)
                assert len(rows) == 1
                assert rows[0]["hotspot_kind"] == "unsafe_block"

                h = get_hotspot(conn, hotspot_id=hid)
                assert h is not None
                assert h["risk_level"] == "high"

    def test_slice_crud(self):
        from packages.core.db import connect
        from packages.evidence.repository import create_hotspot, create_slice, list_slices

        with connect() as conn:
            with conn.transaction():
                run_id, snap_id = self._setup_run(conn)
                hid = create_hotspot(
                    conn, run_id=run_id, snapshot_id=snap_id,
                    file_path="src/lib.rs", start_line=1, end_line=10,
                    hotspot_kind="unsafe_block",
                )
                sid = create_slice(
                    conn,
                    hotspot_id=hid,
                    run_id=run_id,
                    file_path="src/lib.rs",
                    symbol="test_fn",
                    slice_start=1,
                    slice_end=10,
                    anchor_line=5,
                    forbidden_regions=[{"start": 1, "end": 1, "reason": "signature"}],
                    related_vars=["ptr"],
                    related_unsafe_ops=["*ptr"],
                )
                assert sid > 0

                rows = list_slices(conn, run_id=run_id)
                assert len(rows) == 1
                assert rows[0]["forbidden_regions"] == [{"start": 1, "end": 1, "reason": "signature"}]

    def test_validation_result_crud(self):
        from packages.core.db import connect
        from packages.repair.repository import (
            create_validation_result, list_validation_results, get_validation_summary,
        )

        with connect() as conn:
            with conn.transaction():
                run_id, _ = self._setup_run(conn)
                vid = create_validation_result(
                    conn,
                    run_id=run_id,
                    stage="build",
                    status="pass",
                    exit_code=0,
                    duration_ms=1200,
                )
                assert vid > 0

                create_validation_result(
                    conn, run_id=run_id, stage="test", status="fail",
                    exit_code=1, duration_ms=3000, issue_count=2,
                )

                rows = list_validation_results(conn, run_id=run_id)
                assert len(rows) == 2

                summary = get_validation_summary(conn, run_id=run_id)
                assert summary["build"]["status"] == "pass"
                assert summary["test"]["status"] == "fail"

    def test_rollback_crud(self):
        from packages.core.db import connect
        from packages.repair.repository import create_rollback, list_rollbacks
        from uuid import uuid4

        with connect() as conn:
            with conn.transaction():
                run_id, _ = self._setup_run(conn)
                # Create a patch first
                patch_id = str(uuid4())
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO patches (patch_id, run_id, file_path, unified_diff, status) VALUES (%s, %s, %s, %s, %s);",
                        (patch_id, run_id, "src/lib.rs", "--- a/x\n+++ b/x\n@@ -1,1 +1,1 @@\n-a\n+b\n", "applied"),
                    )

                rid = create_rollback(
                    conn,
                    run_id=run_id,
                    patch_id=patch_id,
                    rollback_reason="compile_fail",
                    rollback_detail={"error": "E0308"},
                )
                assert rid > 0

                rows = list_rollbacks(conn, run_id=run_id)
                assert len(rows) == 1
                assert rows[0]["rollback_reason"] == "compile_fail"
