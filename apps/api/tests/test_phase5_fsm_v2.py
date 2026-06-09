"""Phase 5 tests: new FSM engine, handlers, state transitions, progress tracking.

Tests the new packages/repair/agent/ FSM without requiring a real database.
Uses mock DB connections and mock runner mode.
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

_repo_root = Path(__file__).resolve().parents[3]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

UNSAFE_CODE = """\
use std::ptr;

pub unsafe fn process(buf: *mut u8, len: usize) -> i32 {
    if buf.is_null() {
        return -1;
    }
    for i in 0..len {
        *buf.add(i) = 0;
    }
    len as i32
}
"""

SAFE_CODE = """\
pub fn add(a: i32, b: i32) -> i32 {
    a + b
}
"""


@pytest.fixture
def unsafe_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws_unsafe"
    ws.mkdir()
    src = ws / "src"
    src.mkdir()
    (src / "lib.rs").write_text(UNSAFE_CODE, encoding="utf-8")
    (ws / "Cargo.toml").write_text(
        '[package]\nname = "test"\nversion = "0.1.0"\nedition = "2021"\n',
        encoding="utf-8",
    )
    return ws


@pytest.fixture
def safe_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws_safe"
    ws.mkdir()
    src = ws / "src"
    src.mkdir()
    (src / "lib.rs").write_text(SAFE_CODE, encoding="utf-8")
    (ws / "Cargo.toml").write_text(
        '[package]\nname = "test"\nversion = "0.1.0"\nedition = "2021"\n',
        encoding="utf-8",
    )
    return ws


# ===========================================================================
# Handler unit tests
# ===========================================================================

class TestHandlers:

    def test_handle_init(self):
        from packages.repair.agent.handlers import handle_init
        from packages.core.constants import AgentState

        ctx = {"run_id": "test-123", "max_iters": 3, "mode": "enhanced"}
        next_state, output = handle_init(ctx)
        assert next_state == AgentState.PRECHECK
        assert output["mode"] == "enhanced"

    def test_handle_precheck_enhanced(self, unsafe_workspace: Path):
        from packages.repair.agent.handlers import handle_precheck
        from packages.core.constants import AgentState

        ctx = {"workspace_path": str(unsafe_workspace), "mode": "enhanced"}
        next_state, output = handle_precheck(ctx)
        assert next_state == AgentState.HOTSPOT_DISCOVERY

    def test_handle_precheck_baseline(self, unsafe_workspace: Path):
        from packages.repair.agent.handlers import handle_precheck
        from packages.core.constants import AgentState

        ctx = {"workspace_path": str(unsafe_workspace), "mode": "baseline"}
        next_state, output = handle_precheck(ctx)
        assert next_state == AgentState.RUN_BUILD
        assert output.get("skip_to_validation") is True

    def test_handle_precheck_missing_workspace(self):
        from packages.repair.agent.handlers import handle_precheck
        from packages.core.constants import AgentState

        ctx = {"workspace_path": "/nonexistent/path", "mode": "enhanced"}
        next_state, output = handle_precheck(ctx)
        assert next_state == AgentState.STOP_HARD_ERROR

    def test_handle_hotspot_discovery(self, unsafe_workspace: Path):
        from packages.repair.agent.handlers import handle_hotspot_discovery
        from packages.core.constants import AgentState

        ctx = {"workspace_path": str(unsafe_workspace)}
        next_state, output = handle_hotspot_discovery(ctx)
        assert next_state == AgentState.SLICE_SELECT
        assert output["hotspot_count"] > 0
        assert "hotspots" in ctx  # stored in context

    def test_handle_hotspot_discovery_safe_code(self, safe_workspace: Path):
        from packages.repair.agent.handlers import handle_hotspot_discovery
        from packages.core.constants import AgentState

        ctx = {"workspace_path": str(safe_workspace)}
        next_state, output = handle_hotspot_discovery(ctx)
        assert next_state == AgentState.SLICE_SELECT
        assert output["hotspot_count"] == 0

    def test_handle_slice_select(self, unsafe_workspace: Path):
        from packages.repair.agent.handlers import handle_hotspot_discovery, handle_slice_select
        from packages.core.constants import AgentState

        ctx = {"workspace_path": str(unsafe_workspace)}
        handle_hotspot_discovery(ctx)
        next_state, output = handle_slice_select(ctx)
        assert next_state == AgentState.RETRIEVE_EVIDENCE
        assert output["slice_count"] > 0
        assert "target_file" in ctx

    def test_handle_slice_select_no_hotspots(self, safe_workspace: Path):
        from packages.repair.agent.handlers import handle_slice_select
        from packages.core.constants import AgentState

        ctx = {"workspace_path": str(safe_workspace), "hotspots": []}
        next_state, output = handle_slice_select(ctx)
        assert next_state == AgentState.RETRIEVE_EVIDENCE
        assert output.get("skip_to_execute") is True

    def test_handle_run_build_mock(self, unsafe_workspace: Path):
        from packages.repair.agent.handlers import handle_run_build
        from packages.core.constants import AgentState

        ctx = {
            "workspace_path": str(unsafe_workspace),
            "env": {"RUNNER_MODE": "mock", "MOCK_SCENARIO": "success"},
            "timeout": 10,
        }
        next_state, output = handle_run_build(ctx)
        assert next_state == AgentState.RUN_TEST
        assert output["ok"] is True

    def test_handle_run_build_fail_mock(self, unsafe_workspace: Path):
        from packages.repair.agent.handlers import handle_run_build
        from packages.core.constants import AgentState

        ctx = {
            "workspace_path": str(unsafe_workspace),
            "env": {"RUNNER_MODE": "mock", "MOCK_SCENARIO": "compile_fail"},
            "timeout": 10,
        }
        next_state, output = handle_run_build(ctx)
        assert next_state == AgentState.DIAGNOSE

    def test_handle_run_test_mock(self, unsafe_workspace: Path):
        from packages.repair.agent.handlers import handle_run_test
        from packages.core.constants import AgentState

        ctx = {
            "workspace_path": str(unsafe_workspace),
            "env": {"RUNNER_MODE": "mock", "MOCK_SCENARIO": "success"},
            "timeout": 10,
        }
        next_state, output = handle_run_test(ctx)
        assert next_state == AgentState.RUN_LINT
        assert output["ok"] is True

    def test_handle_diagnose_with_rollback(self, unsafe_workspace: Path):
        from packages.repair.agent.handlers import handle_diagnose
        from packages.core.constants import AgentState
        from packages.core.types import ValidationResult

        ctx = {
            "workspace_path": str(unsafe_workspace),
            "validation_results": [
                ValidationResult(phase="build", ok=False, exit_code=1, duration_ms=100,
                                 stderr="error[E0308]: mismatched types"),
            ],
            "last_backup_dir": "/some/backup",
        }
        next_state, output = handle_diagnose(ctx)
        assert next_state == AgentState.ROLLBACK
        assert output["issue_count"] >= 0

    def test_handle_rollback(self, unsafe_workspace: Path):
        from packages.repair.agent.handlers import handle_rollback
        from packages.core.constants import AgentState

        # Create a backup to rollback
        backup = Path(tempfile.mkdtemp(prefix="test_backup_"))
        ctx = {
            "workspace_path": str(unsafe_workspace),
            "last_backup_dir": str(backup),
            "rollback_count": 0,
        }
        next_state, output = handle_rollback(ctx)
        assert next_state == AgentState.SCORE_PROGRESS
        assert ctx["rollback_count"] == 1

    def test_handle_score_progress_success(self, safe_workspace: Path):
        from packages.repair.agent.handlers import handle_score_progress
        from packages.core.constants import AgentState
        from packages.core.types import ValidationResult

        ctx = {
            "workspace_path": str(safe_workspace),
            "mode": "enhanced",
            "iteration_count": 1,
            "max_iters": 5,
            "no_progress_limit": 3,
            "no_progress_count": 0,
            "progress_score_history": [],
            "validation_results": [
                ValidationResult(phase="build", ok=True, exit_code=0, duration_ms=100),
                ValidationResult(phase="test", ok=True, exit_code=0, duration_ms=200),
            ],
            "generated_diff": "some diff content",
        }
        next_state, output = handle_score_progress(ctx)
        assert next_state == AgentState.SUCCESS
        assert output["all_passed"] is True
        assert len(ctx["progress_score_history"]) == 1

    def test_handle_score_progress_max_iters(self, unsafe_workspace: Path):
        from packages.repair.agent.handlers import handle_score_progress
        from packages.core.constants import AgentState
        from packages.core.types import ValidationResult

        ctx = {
            "workspace_path": str(unsafe_workspace),
            "mode": "enhanced",
            "iteration_count": 5,
            "max_iters": 5,
            "no_progress_limit": 3,
            "no_progress_count": 0,
            "progress_score_history": [10.0, 8.0, 6.0, 5.0],
            "validation_results": [
                ValidationResult(phase="build", ok=False, exit_code=1, duration_ms=100),
            ],
        }
        next_state, output = handle_score_progress(ctx)
        assert next_state == AgentState.STOP_MAX_ITERS

    def test_handle_score_progress_no_progress(self, unsafe_workspace: Path):
        from packages.repair.agent.handlers import handle_score_progress
        from packages.core.constants import AgentState
        from packages.core.types import ValidationResult

        ctx = {
            "workspace_path": str(unsafe_workspace),
            "mode": "enhanced",
            "iteration_count": 2,
            "max_iters": 10,
            "no_progress_limit": 2,
            "no_progress_count": 1,
            "progress_score_history": [10.0],
            "validation_results": [
                ValidationResult(phase="build", ok=False, exit_code=1, duration_ms=100),
            ],
            "last_patch_hash": "abc",
            "current_patch_hash": "abc",  # same = no progress
            "last_error_signature": None,
            "current_error_signature": None,
        }
        next_state, output = handle_score_progress(ctx)
        assert next_state == AgentState.STOP_NO_PROGRESS

    def test_handle_score_progress_baseline_fail(self, unsafe_workspace: Path):
        from packages.repair.agent.handlers import handle_score_progress
        from packages.core.constants import AgentState
        from packages.core.types import ValidationResult

        ctx = {
            "workspace_path": str(unsafe_workspace),
            "mode": "baseline",
            "iteration_count": 1,
            "max_iters": 1,
            "no_progress_limit": 0,
            "no_progress_count": 0,
            "progress_score_history": [],
            "validation_results": [
                ValidationResult(phase="build", ok=False, exit_code=1, duration_ms=100),
            ],
            "primary_error_kind": "compile_fail",
        }
        next_state, output = handle_score_progress(ctx)
        assert next_state == AgentState.STOP_HARD_ERROR


# ===========================================================================
# State transition tests
# ===========================================================================

class TestStateTransitions:

    def test_terminal_states_have_no_handlers(self):
        from packages.repair.agent.handlers import HANDLER_MAP
        from packages.core.constants import AgentState, TERMINAL_STATES

        for state in TERMINAL_STATES:
            assert state not in HANDLER_MAP, f"Terminal state {state} should not have a handler"

    def test_all_non_terminal_states_have_handlers(self):
        from packages.repair.agent.handlers import HANDLER_MAP
        from packages.core.constants import AgentState, TERMINAL_STATES

        expected_states = {
            AgentState.INIT, AgentState.PRECHECK,
            AgentState.HOTSPOT_DISCOVERY, AgentState.SLICE_SELECT,
            AgentState.RETRIEVE_EVIDENCE, AgentState.BUILD_PROMPT,
            AgentState.GENERATE_PATCH, AgentState.VALIDATE_PATCH,
            AgentState.APPLY_PATCH, AgentState.RUN_BUILD,
            AgentState.RUN_TEST, AgentState.RUN_LINT,
            AgentState.DIAGNOSE, AgentState.SCORE_PROGRESS,
            AgentState.ROLLBACK,
        }
        for state in expected_states:
            assert state in HANDLER_MAP, f"Missing handler for state {state}"

    def test_handler_return_types(self):
        from packages.repair.agent.handlers import HANDLER_MAP
        from packages.core.constants import AgentState

        # All handlers should be callable
        for state, handler in HANDLER_MAP.items():
            assert callable(handler), f"Handler for {state} is not callable"


# ===========================================================================
# FSM engine tests (mocked DB)
# ===========================================================================

class TestFSMEngine:

    def test_fsm_engine_import(self):
        from packages.repair.agent.fsm import run_fsm, run_fsm_with_conn
        assert callable(run_fsm)
        assert callable(run_fsm_with_conn)

    def test_run_fsm_v2_available_from_legacy(self):
        """Verify run_fsm_v2 is importable from the legacy module."""
        from agent.fsm import run_fsm_v2
        assert callable(run_fsm_v2)


# ===========================================================================
# Progress score tests
# ===========================================================================

class TestProgressScore:

    def test_progress_score_decreases_means_improvement(self):
        """Lower progress score = fewer unsafe constructs = better."""
        from packages.repair.agent.handlers import handle_score_progress
        from packages.core.types import ValidationResult

        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            src.mkdir()
            # Start with unsafe code
            (src / "lib.rs").write_text(
                "pub fn f() { unsafe { let p: *mut i32 = std::ptr::null_mut(); } }\n",
                encoding="utf-8",
            )

            ctx = {
                "workspace_path": td,
                "mode": "enhanced",
                "iteration_count": 1,
                "max_iters": 5,
                "no_progress_limit": 3,
                "no_progress_count": 0,
                "progress_score_history": [],
                "validation_results": [
                    ValidationResult(phase="build", ok=False, exit_code=1, duration_ms=100),
                ],
                "last_patch_hash": None,
                "current_patch_hash": None,
                "last_error_signature": None,
                "current_error_signature": None,
            }

            _, output1 = handle_score_progress(ctx)
            score1 = output1["progress_score"]

            # Now replace with safer code
            (src / "lib.rs").write_text("pub fn f() { let x = 1; }\n", encoding="utf-8")
            ctx["validation_results"] = [
                ValidationResult(phase="build", ok=False, exit_code=1, duration_ms=100),
            ]
            ctx["iteration_count"] = 2

            _, output2 = handle_score_progress(ctx)
            score2 = output2["progress_score"]

            assert score2 < score1, f"Score should decrease: {score1} -> {score2}"
            assert len(ctx["progress_score_history"]) == 2

    def test_progress_score_history_persisted_in_context(self):
        from packages.repair.agent.handlers import handle_score_progress
        from packages.core.types import ValidationResult

        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "lib.rs").write_text("fn f() {}\n", encoding="utf-8")
            ctx = {
                "workspace_path": td,
                "mode": "enhanced",
                "iteration_count": 1,
                "max_iters": 5,
                "no_progress_limit": 3,
                "no_progress_count": 0,
                "progress_score_history": [100.0, 80.0],
                "validation_results": [
                    ValidationResult(phase="build", ok=False, exit_code=1, duration_ms=100),
                ],
                "last_patch_hash": None,
                "current_patch_hash": "new",
                "last_error_signature": None,
                "current_error_signature": "new",
            }
            handle_score_progress(ctx)
            assert len(ctx["progress_score_history"]) == 3


# ===========================================================================
# Full pipeline mock test (no DB)
# ===========================================================================

class TestFullPipelineMock:

    def test_hotspot_to_score_pipeline(self, unsafe_workspace: Path):
        """Walk through the handler chain manually to verify the full pipeline."""
        from packages.repair.agent.handlers import (
            handle_init, handle_precheck, handle_hotspot_discovery,
            handle_slice_select, handle_run_build, handle_run_test,
            handle_run_lint, handle_score_progress,
        )
        from packages.core.constants import AgentState
        from packages.core.types import ValidationResult

        ctx = {
            "run_id": "mock-run",
            "workspace_path": str(unsafe_workspace),
            "mode": "enhanced",
            "max_iters": 2,
            "no_progress_limit": 1,
            "snapshot_id": 1,
            "task_description": "test",
            "env": {"RUNNER_MODE": "mock", "MOCK_SCENARIO": "success"},
            "timeout": 10,
        }

        # INIT -> PRECHECK
        state, out = handle_init(ctx)
        assert state == AgentState.PRECHECK

        # PRECHECK -> HOTSPOT_DISCOVERY
        state, out = handle_precheck(ctx)
        assert state == AgentState.HOTSPOT_DISCOVERY

        # HOTSPOT_DISCOVERY -> SLICE_SELECT
        state, out = handle_hotspot_discovery(ctx)
        assert state == AgentState.SLICE_SELECT
        assert out["hotspot_count"] > 0

        # SLICE_SELECT -> RETRIEVE_EVIDENCE
        state, out = handle_slice_select(ctx)
        assert state == AgentState.RETRIEVE_EVIDENCE

        # Skip retrieval (would need DB), simulate build/test
        # RUN_BUILD (mock success) -> RUN_TEST
        state, out = handle_run_build(ctx)
        assert state == AgentState.RUN_TEST
        assert out["ok"] is True

        # RUN_TEST (mock success) -> RUN_LINT
        state, out = handle_run_test(ctx)
        assert state == AgentState.RUN_LINT

        # RUN_LINT (mock success) -> SCORE_PROGRESS
        state, out = handle_run_lint(ctx)
        assert state == AgentState.SCORE_PROGRESS

        # SCORE_PROGRESS — no generated diff, baseline-like behavior
        ctx["generated_diff"] = ""
        ctx["iteration_count"] = 2
        ctx["progress_score_history"] = []
        state, out = handle_score_progress(ctx)
        # With no diff and max_iters reached, should stop
        assert state in (AgentState.STOP_MAX_ITERS, AgentState.RETRIEVE_EVIDENCE, AgentState.STOP_HARD_ERROR)

    def test_baseline_mode_pipeline(self, unsafe_workspace: Path):
        """Test baseline mode flow: precheck -> execute -> score."""
        from packages.repair.agent.handlers import (
            handle_init, handle_precheck, handle_run_build,
            handle_run_test, handle_score_progress,
        )
        from packages.core.constants import AgentState

        ctx = {
            "run_id": "mock-baseline",
            "workspace_path": str(unsafe_workspace),
            "mode": "baseline",
            "max_iters": 1,
            "no_progress_limit": 0,
            "env": {"RUNNER_MODE": "mock", "MOCK_SCENARIO": "success"},
            "timeout": 10,
            "progress_score_history": [],
            "iteration_count": 1,
            "no_progress_count": 0,
            "validation_results": [],
        }

        state, _ = handle_init(ctx)
        state, out = handle_precheck(ctx)
        assert state == AgentState.RUN_BUILD
        assert out.get("skip_to_validation")

        # Simulate running build+test+lint (baseline validates directly)
        state, out = handle_run_build(ctx)
        assert state == AgentState.RUN_TEST

        state, out = handle_run_test(ctx)
        assert state == AgentState.RUN_LINT

        # Score progress in baseline mode with all passing
        state, out = handle_score_progress(ctx)
        assert state == AgentState.SUCCESS
