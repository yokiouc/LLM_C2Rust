"""Repair Agent FSM engine.

Drives the state machine by dispatching to handlers, persisting steps/metrics,
and managing the repair loop lifecycle.
"""

import hashlib
import json
import time
import traceback
from pathlib import Path
from typing import Any
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from packages.core.constants import AgentState, TERMINAL_STATES
from packages.core.types import RunRecord
from .handlers import HANDLER_MAP, _sha256_text
from .states import is_terminal


# ---------------------------------------------------------------------------
# DB helpers (self-contained, use whatever connection is passed in)
# ---------------------------------------------------------------------------

def _advisory_lock_key(repo_url: str, ref: str) -> int:
    s = f"{repo_url}#{ref}".encode("utf-8")
    h = hashlib.sha256(s).digest()
    return int.from_bytes(h[:8], "big", signed=True)


def _create_run(conn: Any, *, repo_url: str, ref: str, task_description: str) -> str:
    run_id = str(uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO agent_runs (run_id, repo_url, ref, task_description, status) VALUES (%s, %s, %s, %s, %s);",
            (run_id, repo_url, ref, task_description, "INIT"),
        )
    return run_id


def _update_run_status(conn: Any, *, run_id: str, status: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE agent_runs SET status = %s, updated_at = NOW() WHERE run_id = %s;", (status, run_id))


def _insert_step(conn: Any, *, run_id: str, step_name: str, input_json: dict, output_json: dict, ok: bool, error_msg: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO agent_steps (run_id, step_name, input_json, output_json, ok, error_msg) VALUES (%s, %s, %s, %s, %s, %s);",
            (run_id, step_name, Jsonb(input_json), Jsonb(output_json), ok, error_msg),
        )


def _insert_patch_row(conn: Any, *, run_id: str, file_path: str, unified_diff: str, status: str, error_msg: str | None) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO patches (run_id, file_path, unified_diff, status, error_msg) VALUES (%s, %s, %s, %s, %s) RETURNING patch_id;",
            (run_id, file_path, unified_diff, status, error_msg),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("insert_patch_failed")
        return str(row[0])


def _update_patch_row(conn: Any, *, patch_id: str, status: str, error_msg: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE patches SET status = %s, error_msg = %s WHERE patch_id = %s;", (status, error_msg, patch_id))


def _upsert_metric(conn: Any, *, run_id: str, key: str, value: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO metrics (run_id, key, value_json) VALUES (%s, %s, %s) ON CONFLICT (run_id, key) DO UPDATE SET value_json = EXCLUDED.value_json;",
            (run_id, key, Jsonb(value)),
        )


# ---------------------------------------------------------------------------
# FSM Engine
# ---------------------------------------------------------------------------

def run_fsm_with_conn(conn: Any, context: dict) -> RunRecord:
    """Execute the repair FSM within the given DB connection.

    This is the core engine. The outer run_fsm() handles connection management
    and advisory locking.
    """
    run_id = context["run_id"]
    mode = str(context.get("mode") or "enhanced").strip().lower()
    max_iters = min(max(int(context.get("max_iters") or 2), 1), 20)
    no_progress_limit = min(max(int(context.get("no_progress_limit") or 1), 0), 10)

    # Initialize tracking
    ctx = dict(context)
    ctx["mode"] = mode
    ctx["max_iters"] = max_iters
    ctx["no_progress_limit"] = no_progress_limit
    ctx["iteration_count"] = 0
    ctx["rollback_count"] = 0
    ctx["no_progress_count"] = 0
    ctx["progress_score_history"] = []
    ctx["last_issues"] = []
    ctx["validation_results"] = []
    ctx["generated_diff"] = ""
    ctx["last_patch_hash"] = None
    ctx["last_error_signature"] = None
    ctx["conn"] = conn

    # Timing
    total_ms = 0
    retrieve_ms = 0
    generate_ms = 0
    validate_ms = 0
    build_ms = 0
    test_ms = 0

    from packages.metrics.safety import compute_safety_metrics
    safety_before = compute_safety_metrics(Path(ctx["workspace_path"]))
    ctx["safety_before"] = safety_before

    # Initialize metrics
    for k, v in [
        ("mode", mode), ("final_status", "RUNNING"), ("final_stop_reason", "RUNNING"),
        ("iteration_count", 0), ("rollback_count", 0), ("no_progress_count", 0),
        ("total_ms", 0), ("retrieve_ms", 0), ("generate_ms", 0),
        ("validate_ms", 0), ("build_ms", 0), ("test_ms", 0),
        ("progress_score_history", []),
        ("compile_ok_before", False), ("test_ok_before", False),
        ("lint_ok_before", False), ("fmt_ok_before", False),
        ("unsafe_block_count_before", safety_before.unsafe_block_count),
        ("raw_ptr_count_before", safety_before.raw_ptr_count),
        ("unsafe_api_count_before", safety_before.unsafe_api_count),
        ("manual_mem_call_count_before", safety_before.manual_mem_call_count),
    ]:
        _upsert_metric(conn, run_id=run_id, key=k, value=v)

    # State machine loop
    state = AgentState.INIT
    last_patch_id: str | None = None
    step_count = 0
    max_steps = 200  # safety limit

    while not is_terminal(state) and step_count < max_steps:
        step_count += 1

        # Track iteration count when we enter RETRIEVE_EVIDENCE
        if state == AgentState.RETRIEVE_EVIDENCE:
            ctx["iteration_count"] = ctx.get("iteration_count", 0) + 1

        handler = HANDLER_MAP.get(state)
        if handler is None:
            # No handler = terminal or unknown state
            break

        # Execute handler with timing and error capture
        t0 = time.perf_counter()
        input_json = {
            "state": state.value,
            "iter": ctx.get("iteration_count", 0),
            "run_id": run_id,
            "snapshot_id": ctx.get("snapshot_id"),
            "workspace_path": str(ctx.get("workspace_path", "")),
        }
        ok = True
        error_msg = None
        output_json: dict[str, Any] = {}

        try:
            _update_run_status(conn, run_id=run_id, status=state.value)
            next_state, output_json = handler(ctx)
        except Exception as e:
            ok = False
            error_msg = f"{type(e).__name__}: {e}"
            output_json = {"traceback": traceback.format_exc()}
            next_state = AgentState.STOP_HARD_ERROR
        finally:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            total_ms += elapsed_ms
            output_json["elapsed_ms"] = elapsed_ms
            _insert_step(conn, run_id=run_id, step_name=state.value,
                         input_json=input_json, output_json=output_json,
                         ok=ok, error_msg=error_msg)

        # Accumulate timing by category
        if state == AgentState.RETRIEVE_EVIDENCE:
            retrieve_ms += elapsed_ms
            _upsert_metric(conn, run_id=run_id, key="retrieve_count", value=int(output_json.get("evidence_count") or 0))
            _upsert_metric(conn, run_id=run_id, key="evidence_link_count", value=int(output_json.get("evidence_link_count") or 0))
        elif state in (AgentState.BUILD_PROMPT, AgentState.GENERATE_PATCH, AgentState.VALIDATE_PATCH):
            generate_ms += elapsed_ms
        elif state == AgentState.RUN_BUILD:
            build_ms += elapsed_ms
        elif state == AgentState.RUN_TEST:
            test_ms += elapsed_ms
        elif state == AgentState.RUN_LINT:
            validate_ms += elapsed_ms

        # Post-step actions: persist patches, track hashes
        if state == AgentState.APPLY_PATCH and ok:
            diff = ctx.get("generated_diff", "")
            apply_result = ctx.get("last_apply_result")
            if diff and apply_result:
                file_path = apply_result.file_paths[0] if apply_result.file_paths else ctx.get("target_file", "")
                last_patch_id = _insert_patch_row(
                    conn, run_id=run_id, file_path=file_path,
                    unified_diff=diff, status=apply_result.status,
                    error_msg=apply_result.error_msg,
                )
                ctx["current_patch_hash"] = _sha256_text(diff)
                _upsert_metric(conn, run_id=run_id, key="last_patch_hash", value=ctx["current_patch_hash"])

        if state == AgentState.ROLLBACK and last_patch_id:
            _update_patch_row(conn, patch_id=last_patch_id, status="rolled_back",
                              error_msg=f"rolled_back_after_{ctx.get('primary_error_kind', 'unknown')}")
            # Also record in patch_rollbacks table
            try:
                from packages.repair.repository import create_rollback
                create_rollback(
                    conn, run_id=run_id, patch_id=last_patch_id,
                    rollback_reason=ctx.get("primary_error_kind", "unknown"),
                    rollback_detail={"iteration": ctx.get("iteration_count", 0)},
                    backup_path=ctx.get("last_backup_dir"),
                )
            except Exception:
                pass  # Best effort — table may not exist in legacy DB
            last_patch_id = None

        if state == AgentState.DIAGNOSE:
            issues = ctx.get("last_issues") or []
            first = issues[0] if issues and isinstance(issues[0], dict) else {}
            error_sig = "|".join([
                str(ctx.get("primary_error_kind") or ""),
                str(first.get("file") or ""),
                str(first.get("error_code") or ""),
            ])
            ctx["current_error_signature"] = error_sig
            _upsert_metric(conn, run_id=run_id, key="last_error_signature", value=error_sig)
            _upsert_metric(conn, run_id=run_id, key="diagnose_issue_count", value=len(issues))
            _upsert_metric(conn, run_id=run_id, key="primary_error_kind", value=ctx.get("primary_error_kind"))

        # Persist validation results to new table (best effort)
        if state in (AgentState.RUN_BUILD, AgentState.RUN_TEST, AgentState.RUN_LINT):
            try:
                from packages.repair.repository import create_validation_result
                vr = (ctx.get("validation_results") or [])[-1] if ctx.get("validation_results") else None
                if vr:
                    status_str = "pass" if vr.ok else ("error" if vr.exit_code == 124 else "fail")
                    create_validation_result(
                        conn, run_id=run_id, patch_id=last_patch_id,
                        stage=vr.phase, status=status_str,
                        exit_code=vr.exit_code, duration_ms=vr.duration_ms,
                        issue_count=vr.issue_count,
                        parsed_issues=vr.parsed_issues,
                        output={"stdout_len": len(vr.stdout), "stderr_len": len(vr.stderr)},
                    )
            except Exception:
                pass  # Best effort

        # Advance state
        state = next_state

    # ---------------------------------------------------------------------------
    # Finalize
    # ---------------------------------------------------------------------------

    # Determine final status from terminal state
    stop_reason_map = {
        AgentState.SUCCESS: "success",
        AgentState.STOP_NO_PROGRESS: "no_progress",
        AgentState.STOP_MAX_ITERS: "max_iters",
        AgentState.STOP_HARD_ERROR: ctx.get("primary_error_kind") or "hard_error",
        # Legacy
        AgentState.STOP: ctx.get("primary_error_kind") or "unknown",
        AgentState.FAILED: ctx.get("primary_error_kind") or "unknown",
    }
    final_stop_reason = stop_reason_map.get(state, "unknown")
    final_status = "OK" if state == AgentState.SUCCESS else "FAILED"
    safety_after = compute_safety_metrics(Path(ctx["workspace_path"]))

    latest_by_phase: dict[str, Any] = {}
    for vr in ctx.get("validation_results", []) or []:
        latest_by_phase[str(vr.phase)] = vr
    compile_ok_after = bool(latest_by_phase.get("build") and latest_by_phase["build"].ok)
    test_ok_after = bool(latest_by_phase.get("test") and latest_by_phase["test"].ok)
    lint_ok_after = bool(latest_by_phase.get("clippy") and latest_by_phase["clippy"].ok)
    fmt_ok_after = bool(latest_by_phase.get("fmt") and latest_by_phase["fmt"].ok)
    patch_size_lines = len(str(ctx.get("generated_diff") or "").splitlines())

    from packages.metrics.collector import build_eval_metrics, build_run_metrics, metrics_to_db_pairs
    from packages.metrics.compare import build_comparison
    run_metrics = build_run_metrics(
        iteration_count=int(ctx.get("iteration_count", 0)),
        patch_rounds=int(ctx.get("iteration_count", 0)) if mode == "enhanced" else 0,
        rollback_count=int(ctx.get("rollback_count", 0)),
        total_ms=total_ms,
        retrieve_ms=retrieve_ms,
        generate_ms=generate_ms,
        validate_ms=validate_ms,
        build_ms=build_ms,
        test_ms=test_ms,
    )
    eval_metrics = build_eval_metrics(
        compile_ok_before=False,
        compile_ok_after=compile_ok_after,
        test_ok_before=False,
        test_ok_after=test_ok_after,
        lint_ok_before=False,
        lint_ok_after=lint_ok_after,
        fmt_ok_before=False,
        fmt_ok_after=fmt_ok_after,
        safety_before=safety_before,
        safety_after=safety_after,
        patch_size_lines=patch_size_lines,
        final_stop_reason=final_stop_reason,
        primary_error_kind=str(ctx.get("primary_error_kind") or ""),
        progress_score_history=ctx.get("progress_score_history", []),
    )
    for key, value in metrics_to_db_pairs(run_metrics, eval_metrics):
        _upsert_metric(conn, run_id=run_id, key=key, value=value)

    self_compare = build_comparison(
        project=str(ctx.get("repo_url") or ""),
        snapshot_id=int(ctx.get("snapshot_id") or 0),
        baseline_metrics={
            "run_id": run_id,
            "unsafe_block_count_before": safety_before.unsafe_block_count,
            "raw_ptr_count_before": safety_before.raw_ptr_count,
            "unsafe_api_count_before": safety_before.unsafe_api_count,
            "total_ms": total_ms,
        },
        enhanced_metrics={
            "run_id": run_id,
            "unsafe_block_count_after": safety_after.unsafe_block_count,
            "raw_ptr_count_after": safety_after.raw_ptr_count,
            "unsafe_api_count_after": safety_after.unsafe_api_count,
            "total_ms": total_ms,
            "iteration_count": int(ctx.get("iteration_count", 0)),
            "rollback_count": int(ctx.get("rollback_count", 0)),
            "final_stop_reason": final_stop_reason,
        },
    )
    _upsert_metric(conn, run_id=run_id, key="unsafe_blocks_delta", value=self_compare.unsafe_blocks_delta)
    _upsert_metric(conn, run_id=run_id, key="raw_ptr_delta", value=self_compare.raw_ptr_delta)
    _upsert_metric(conn, run_id=run_id, key="unsafe_api_delta", value=self_compare.unsafe_api_delta)

    # Persist final metrics
    for k, v in [
        ("final_status", final_status),
        ("final_stop_reason", final_stop_reason),
        ("iteration_count", ctx.get("iteration_count", 0)),
        ("rollback_count", ctx.get("rollback_count", 0)),
        ("no_progress_count", ctx.get("no_progress_count", 0)),
        ("total_ms", total_ms),
        ("retrieve_ms", retrieve_ms),
        ("generate_ms", generate_ms),
        ("validate_ms", validate_ms),
        ("build_ms", build_ms),
        ("test_ms", test_ms),
        ("progress_score_history", ctx.get("progress_score_history", [])),
    ]:
        _upsert_metric(conn, run_id=run_id, key=k, value=v)

    # Record final STOP step
    _insert_step(
        conn, run_id=run_id,
        step_name=state.value,
        input_json={"state": state.value, "iter": ctx.get("iteration_count", 0)},
        output_json={
            "status": final_status,
            "stop_reason": final_stop_reason,
            "progress_score_history": ctx.get("progress_score_history", []),
            "primary_error_kind": ctx.get("primary_error_kind"),
        },
        ok=(final_status == "OK"),
        error_msg=None,
    )

    # Update run status. Legacy FSM used STOP for success; v2 records the
    # terminal state directly so formal experiment data has clear semantics.
    db_status = AgentState.SUCCESS.value if state == AgentState.SUCCESS else "FAILED"
    _update_run_status(conn, run_id=run_id, status=db_status)

    return RunRecord(run_id=run_id, status=db_status)


def run_fsm(context: dict) -> RunRecord:
    """Top-level entry point: acquire lock, create run, execute FSM.

    Compatible with the legacy apps/api/agent/fsm.run_fsm() signature.
    """
    # Import connect — works from both packages and apps/api context
    try:
        from packages.core.db import connect
    except ImportError:
        from db import connect

    snapshot_id = int(context.get("snapshot_id") or 0)
    workspace_path = str(context.get("workspace_path") or "").strip()
    if snapshot_id <= 0:
        raise ValueError("snapshot_id_required")
    if not workspace_path:
        raise ValueError("workspace_path_required")

    base_dir = Path(workspace_path).resolve()
    if not base_dir.exists():
        raise FileNotFoundError(workspace_path)

    repo_url = str(context.get("repo_url") or f"workspace://{base_dir}")
    ref = str(context.get("ref") or str(snapshot_id))
    task_description = str(context.get("task_description", "mock task"))

    with connect() as conn:
        with conn.transaction():
            # Advisory lock
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s::bigint);", (_advisory_lock_key(repo_url, ref),))
                got = bool(cur.fetchone()[0])
            if not got:
                raise RuntimeError("run_lock_not_acquired")

            # Create run
            run_id = _create_run(conn, repo_url=repo_url, ref=ref, task_description=task_description)

            # Build context
            ctx = dict(context)
            ctx["run_id"] = run_id
            ctx["workspace_path"] = str(base_dir)
            ctx["repo_url"] = repo_url
            ctx["ref"] = ref
            ctx["task_description"] = task_description

            # Execute FSM
            result = run_fsm_with_conn(conn, ctx)

            # Release lock
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s::bigint);", (_advisory_lock_key(repo_url, ref),))

        # Fetch final status
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT run_id, status FROM agent_runs WHERE run_id = %s;", (run_id,))
            row = cur.fetchone()

    return RunRecord(run_id=str(row["run_id"]), status=str(row["status"]))
