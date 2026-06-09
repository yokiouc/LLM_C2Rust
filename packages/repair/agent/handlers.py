"""State handler functions for the Repair Agent FSM.

Each handler receives a context dict and returns (next_state, output_dict).
Handlers are pure-ish functions that call into packages/ modules.
"""

import json
import time
import hashlib
from pathlib import Path
from typing import Any

from packages.core.constants import AgentState
from packages.core.types import HotspotInfo


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def _safe_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except Exception:
        return None


def _as_str_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return []


def _classify_error_kind(*, exit_code: int | None, stderr: str | None, step_error: str | None) -> str:
    if step_error:
        if "patch_constraint_violation:" in step_error:
            return "patch_constraint_violation"
        if "patch_apply_failed:" in step_error:
            return "apply_fail"
        if step_error == "retrieve_no_results":
            return "retrieve_empty"
    if exit_code == 124 or (stderr and "timeout" in stderr.lower()):
        return "timeout"
    if stderr and "assertion failed" in stderr.lower():
        return "test_fail"
    if exit_code and exit_code != 0:
        return "compile_fail"
    return "unknown"


def _slice_repair_priority(sl: Any) -> tuple[int, int]:
    """Prefer one focused high-value hotspot per run."""
    ops = " ".join(str(x) for x in (getattr(sl, "related_unsafe_ops", []) or []))
    content = str(getattr(sl, "content", "") or "")
    text = f"{ops}\n{content}"
    if "ptr::copy_nonoverlapping" in text or "ptr::copy(" in text:
        rank = 0
    elif ".add(" in text or ".offset(" in text:
        rank = 1
    elif "*" in text and "unsafe" in text:
        rank = 2
    elif "unsafe" in text:
        rank = 3
    else:
        rank = 4
    return (rank, int(getattr(sl, "start_line", 0) or 0))


# ---------------------------------------------------------------------------
# INIT handler
# ---------------------------------------------------------------------------

def handle_init(ctx: dict) -> tuple[AgentState, dict]:
    """Initialize run context, validate inputs."""
    return AgentState.PRECHECK, {
        "run_id": ctx.get("run_id"),
        "max_iters": ctx.get("max_iters", 2),
        "no_progress_limit": ctx.get("no_progress_limit", 1),
        "mode": ctx.get("mode", "enhanced"),
    }


# ---------------------------------------------------------------------------
# PRECHECK handler
# ---------------------------------------------------------------------------

def handle_precheck(ctx: dict) -> tuple[AgentState, dict]:
    """Validate workspace and mode. Baseline mode shortcuts to execute-only."""
    mode = str(ctx.get("mode") or "enhanced").strip().lower()
    base_dir = Path(ctx["workspace_path"]).resolve()

    if not base_dir.exists():
        return AgentState.STOP_HARD_ERROR, {"error": f"workspace not found: {base_dir}"}

    if mode == "baseline":
        return AgentState.RUN_BUILD, {"mode": "baseline", "skip_to_validation": True}

    return AgentState.HOTSPOT_DISCOVERY, {"mode": mode}


# ---------------------------------------------------------------------------
# HOTSPOT_DISCOVERY handler
# ---------------------------------------------------------------------------

def handle_hotspot_discovery(ctx: dict) -> tuple[AgentState, dict]:
    """Discover unsafe hotspots in the workspace."""
    from packages.repair.hotspot import discover_and_persist_hotspots, discover_hotspots

    base_dir = Path(ctx["workspace_path"]).resolve()
    hotspots = discover_hotspots(base_dir)

    ctx["hotspots"] = hotspots
    hotspot_ids: list[int] = []
    conn = ctx.get("conn")
    if conn is not None:
        hotspot_ids = discover_and_persist_hotspots(
            base_dir,
            conn=conn,
            run_id=ctx.get("run_id"),
            snapshot_id=ctx.get("snapshot_id"),
        )
    ctx["hotspot_ids"] = hotspot_ids
    return AgentState.SLICE_SELECT, {
        "hotspot_count": len(hotspots),
        "persisted_hotspot_count": len(hotspot_ids),
        "hotspots_summary": [
            {"file": h.file, "kind": h.hotspot_kind, "risk_score": h.risk_score,
             "line_start": h.line_start, "line_end": h.line_end, "symbol": h.symbol}
            for h in hotspots[:20]
        ],
    }


# ---------------------------------------------------------------------------
# SLICE_SELECT handler
# ---------------------------------------------------------------------------

def handle_slice_select(ctx: dict) -> tuple[AgentState, dict]:
    """Build repair slices from discovered hotspots."""
    from packages.repair.slice_builder import build_and_persist_slices, build_slices_for_hotspots

    base_dir = Path(ctx["workspace_path"]).resolve()
    hotspots: list[HotspotInfo] = ctx.get("hotspots") or []

    if not hotspots:
        # No hotspots = nothing to repair, go to execute to verify baseline
        return AgentState.RETRIEVE_EVIDENCE, {"slice_count": 0, "skip_to_execute": True}

    slices = build_slices_for_hotspots(base_dir, hotspots)
    ctx["slices"] = slices
    slice_ids: list[int] = []
    conn = ctx.get("conn")
    hotspot_ids = ctx.get("hotspot_ids") or []
    if conn is not None and hotspot_ids:
        slice_ids = build_and_persist_slices(
            base_dir,
            hotspots,
            hotspot_ids,
            conn=conn,
            run_id=ctx.get("run_id"),
        )
    ctx["slice_ids"] = slice_ids

    # Pick the highest-risk slice as primary target
    if slices:
        primary = sorted(slices, key=_slice_repair_priority)[0]
        ctx["target_file"] = primary.file
        ctx["target_slice"] = primary

    primary_out = ctx.get("target_slice")
    return AgentState.RETRIEVE_EVIDENCE, {
        "slice_count": len(slices),
        "persisted_slice_count": len(slice_ids),
        "primary_file": primary_out.file if primary_out else None,
        "primary_symbol": primary_out.symbol if primary_out else None,
    }


# ---------------------------------------------------------------------------
# RETRIEVE_EVIDENCE handler
# ---------------------------------------------------------------------------

def handle_retrieve_evidence(ctx: dict) -> tuple[AgentState, dict]:
    """Retrieve evidence for the current slice/task."""
    # Use the legacy retrieval path (retrieval.service) which is still the
    # canonical search implementation. We import it at call time because
    # it lives in apps/api context.
    try:
        from retrieval.service import hybrid_retrieve_evidence
    except ImportError:
        from packages.evidence.retrieval import hybrid_retrieve_evidence

    snapshot_id = int(ctx.get("snapshot_id") or 0)
    task_description = str(ctx.get("task_description", ""))
    filters = ctx.get("filters") if isinstance(ctx.get("filters"), dict) else {}
    top_k = min(max(int(ctx.get("top_k") or 20), 1), 200)
    model_id = str(ctx.get("retrieval_model_id") or "").strip() or None

    pack = hybrid_retrieve_evidence(
        snapshot_id=snapshot_id,
        query_text=task_description,
        filters=filters,
        top_k=top_k,
        model_id=model_id,
    )
    items = list(pack.get("items") or [])
    ctx["evidence_items"] = items

    if not items:
        return AgentState.STOP_HARD_ERROR, {"error": "retrieve_no_results", "evidence_count": 0}

    link_ids: list[int] = []
    conn = ctx.get("conn")
    slice_ids = ctx.get("slice_ids") or []
    slices = ctx.get("slices") or []
    if conn is not None and slice_ids and slices:
        from packages.evidence.linker import link_slices_to_evidence
        link_ids = link_slices_to_evidence(
            conn=conn,
            slice_ids=slice_ids,
            slices=slices,
            evidence_items=items,
        )
    ctx["evidence_link_ids"] = link_ids

    return AgentState.BUILD_PROMPT, {"evidence_count": len(items), "evidence_link_count": len(link_ids)}


# ---------------------------------------------------------------------------
# BUILD_PROMPT handler
# ---------------------------------------------------------------------------

def handle_build_prompt(ctx: dict) -> tuple[AgentState, dict]:
    """Assemble the evidence pack and prompt for patch generation."""
    from packages.repair.prompt_builder import build_repair_prompt

    target_file = ctx.get("target_file", "")
    target_slice = ctx.get("target_slice")
    evidence_items = ctx.get("evidence_items") or []
    task_description = str(ctx.get("task_description", ""))
    last_issues = ctx.get("last_issues") or []

    # Build boundary from slice
    if target_slice:
        boundary = {
            "start_line": target_slice.start_line,
            "end_line": target_slice.end_line,
            "anchor_line": target_slice.anchor_line,
            "anchor_kind": "hotspot",
            "signature_text": target_slice.signature_text,
            "signature_line": target_slice.signature_line,
            "forbidden_regions": target_slice.forbidden_regions,
        }
    else:
        boundary = {"start_line": 1, "end_line": 100, "anchor_line": 1, "anchor_kind": "start"}

    # Identify strategy evidence
    strategies = [
        it for it in evidence_items
        if str((it.get("meta") or {}).get("evidence_type") or "").startswith(
            ("replacement_strategy", "rust_idiom_template", "interface_constraint", "behavior_constraint")
        )
    ]

    evidence_text = build_repair_prompt(
        task_description=task_description,
        target_file=target_file,
        boundary=boundary,
        evidence_items=evidence_items,
        strategies=strategies,
        diagnose_issues=last_issues,
        workspace_path=str(ctx.get("workspace_path") or ""),
    )

    ctx["evidence_text"] = evidence_text
    ctx["boundary"] = boundary
    ctx["strategies"] = strategies

    return AgentState.GENERATE_PATCH, {
        "prompt_len": len(evidence_text),
        "target_file": target_file,
        "boundary": boundary,
    }


# ---------------------------------------------------------------------------
# GENERATE_PATCH handler
# ---------------------------------------------------------------------------

def handle_generate_patch(ctx: dict) -> tuple[AgentState, dict]:
    """Generate a controlled patch using LLM or template provider."""
    from packages.repair.generator import generate_controlled_patch, get_last_generation_info
    from packages.repair.llm_provider import TemplateEditProvider

    # For baseline mode, skip patch generation entirely
    mode = ctx.get("mode", "enhanced")
    if mode == "baseline" or ctx.get("skip_to_execute"):
        ctx["generated_diff"] = ""
        return AgentState.RUN_BUILD, {"mode": "baseline", "diff_len": 0}

    evidence_text = ctx.get("evidence_text", "")
    target_file = ctx.get("target_file", "")

    patch_backend = str(ctx.get("patch_backend") or "").strip().lower()
    provider = TemplateEditProvider() if patch_backend in {"template_edit", "demo"} else None

    diff = generate_controlled_patch(evidence=evidence_text, target_function=target_file, provider=provider)
    generation_info = get_last_generation_info()

    if not diff.strip():
        return AgentState.DIAGNOSE, {"error": "patch_generate_empty", "diff_len": 0, "generation_info": generation_info}

    ctx["generated_diff"] = diff
    return AgentState.VALIDATE_PATCH, {"diff_len": len(diff), "target_file": target_file, "generation_info": generation_info}


# ---------------------------------------------------------------------------
# VALIDATE_PATCH handler
# ---------------------------------------------------------------------------

def handle_validate_patch(ctx: dict) -> tuple[AgentState, dict]:
    """Validate the generated patch against constraints."""
    from packages.repair.patch_validator import validate_patch_constraints

    diff = ctx.get("generated_diff", "")
    target_file = ctx.get("target_file", "")
    boundary = ctx.get("boundary") or {}
    target_slice = ctx.get("target_slice")

    signature_text = None
    if target_slice and target_slice.signature_text:
        signature_text = target_slice.signature_text

    ok, violation = validate_patch_constraints(
        diff=diff,
        target_file=target_file,
        signature_text=signature_text,
        boundary=boundary,
    )

    if not ok:
        code = (violation or {}).get("code", "unknown")
        return AgentState.DIAGNOSE, {
            "error": f"patch_constraint_violation:{code}",
            "constraint_violation": violation,
        }

    return AgentState.APPLY_PATCH, {"validation": "pass"}


# ---------------------------------------------------------------------------
# APPLY_PATCH handler
# ---------------------------------------------------------------------------

def handle_apply_patch(ctx: dict) -> tuple[AgentState, dict]:
    """Apply the validated patch to the workspace."""
    from packages.repair.patch_engine import apply_patch

    base_dir = Path(ctx["workspace_path"]).resolve()
    diff = ctx.get("generated_diff", "")

    result = apply_patch(base_dir, diff)
    ctx["last_apply_result"] = result
    ctx["last_backup_dir"] = result.backup_dir

    if not result.ok:
        return AgentState.ROLLBACK, {
            "error": f"patch_apply_failed:{result.error_msg}",
            "patch_status": result.status,
        }

    return AgentState.RUN_BUILD, {
        "patch_status": result.status,
        "file_paths": result.file_paths,
    }


# ---------------------------------------------------------------------------
# RUN_BUILD / RUN_TEST / RUN_LINT handlers
# ---------------------------------------------------------------------------

def _run_cargo_phase(ctx: dict, stage: str, next_on_pass: AgentState) -> tuple[AgentState, dict]:
    """Shared logic for build/test/lint phases."""
    from packages.runner.validator import run_validation_phase

    base_dir = Path(ctx["workspace_path"]).resolve()
    env = ctx.get("env") or {}
    if not isinstance(env, dict):
        env = {}
    timeout = int(ctx.get("timeout", 30))

    result = run_validation_phase(
        stage=stage,
        workspace_path=base_dir,
        env={str(k): str(v) for k, v in env.items()},
        timeout=timeout,
    )

    # Store result for metrics
    ctx.setdefault("validation_results", []).append(result)

    output = {
        "stage": stage,
        "ok": result.ok,
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
        "issue_count": result.issue_count,
        "runner": {
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "log_path": result.log_path,
        },
    }

    if result.ok:
        return next_on_pass, output

    if stage == "clippy" and ctx.get("generated_diff", "").strip() and ctx.get("last_backup_dir"):
        from packages.repair.import_cleanup import cleanup_clippy_diagnostics_and_validate

        raw_text = result.stderr if result.stderr.strip() else result.stdout
        cleanup = cleanup_clippy_diagnostics_and_validate(
            workspace_path=base_dir,
            target_file=str(ctx.get("target_file") or ""),
            diagnostics=raw_text,
            env={str(k): str(v) for k, v in env.items()},
            timeout=timeout,
        )
        output["clippy_cleanup"] = {
            "ok": cleanup.ok,
            "changed": cleanup.changed,
            "error": cleanup.error,
            "diff": cleanup.diff,
        }
        if cleanup.ok and cleanup.changed:
            cleanup_results = list(cleanup.validation_results or [])
            ctx["validation_results"] = ctx.get("validation_results", [])[:-1] + cleanup_results
            if cleanup_results:
                last = cleanup_results[-1]
                output.update({
                    "ok": bool(last.ok),
                    "exit_code": last.exit_code,
                    "duration_ms": result.duration_ms + sum(int(v.duration_ms) for v in cleanup_results),
                    "issue_count": last.issue_count,
                    "runner": {
                        "exit_code": last.exit_code,
                        "duration_ms": last.duration_ms,
                        "stdout": last.stdout,
                        "stderr": last.stderr,
                        "log_path": last.log_path,
                    },
                })
            ctx["cleanup_diff"] = cleanup.diff
            return next_on_pass, output

    return AgentState.DIAGNOSE, output


def handle_run_build(ctx: dict) -> tuple[AgentState, dict]:
    return _run_cargo_phase(ctx, "build", AgentState.RUN_TEST)


def handle_run_test(ctx: dict) -> tuple[AgentState, dict]:
    return _run_cargo_phase(ctx, "test", AgentState.RUN_LINT)


def handle_run_lint(ctx: dict) -> tuple[AgentState, dict]:
    return _run_cargo_phase(ctx, "clippy", AgentState.SCORE_PROGRESS)


# ---------------------------------------------------------------------------
# DIAGNOSE handler
# ---------------------------------------------------------------------------

def handle_diagnose(ctx: dict) -> tuple[AgentState, dict]:
    """Parse errors and decide whether to rollback or stop."""
    from packages.repair.diagnose import parse_diagnostics

    # Get error info from the last failing step
    validation_results = ctx.get("validation_results") or []
    last_vr = validation_results[-1] if validation_results else None

    raw_text = ""
    exit_code = None
    if last_vr:
        raw_text = last_vr.stderr if last_vr.stderr.strip() else last_vr.stdout
        exit_code = last_vr.exit_code

    issues = parse_diagnostics(raw_text) if raw_text.strip() else []
    ctx["last_issues"] = issues

    error_kind = _classify_error_kind(
        exit_code=exit_code,
        stderr=raw_text,
        step_error=str(ctx.get("_step_error") or ""),
    )
    ctx["primary_error_kind"] = error_kind

    # If we have a patch applied, rollback
    if ctx.get("last_backup_dir"):
        return AgentState.ROLLBACK, {
            "issues": issues,
            "error_kind": error_kind,
            "issue_count": len(issues),
        }

    # No patch to rollback — this is a pre-patch failure
    return AgentState.SCORE_PROGRESS, {
        "issues": issues,
        "error_kind": error_kind,
        "issue_count": len(issues),
    }


# ---------------------------------------------------------------------------
# ROLLBACK handler
# ---------------------------------------------------------------------------

def handle_rollback(ctx: dict) -> tuple[AgentState, dict]:
    """Rollback the last applied patch."""
    from packages.repair.patch_engine import rollback

    base_dir = Path(ctx["workspace_path"]).resolve()
    backup_dir = ctx.get("last_backup_dir")

    if backup_dir:
        rollback(base_dir, Path(backup_dir))

    ctx["rollback_count"] = ctx.get("rollback_count", 0) + 1
    ctx["last_backup_dir"] = None  # Clear after rollback

    return AgentState.SCORE_PROGRESS, {
        "rollback_count": ctx["rollback_count"],
        "backup_dir": backup_dir,
    }


# ---------------------------------------------------------------------------
# SCORE_PROGRESS handler
# ---------------------------------------------------------------------------

def handle_score_progress(ctx: dict) -> tuple[AgentState, dict]:
    """Evaluate progress and decide whether to continue, stop, or succeed."""
    from packages.metrics.safety import compute_safety_metrics

    base_dir = Path(ctx["workspace_path"]).resolve()
    iteration = ctx.get("iteration_count", 0)
    max_iters = ctx.get("max_iters", 2)
    no_progress_limit = ctx.get("no_progress_limit", 1)
    no_progress_count = ctx.get("no_progress_count", 0)

    # Compute current safety metrics
    current_safety = compute_safety_metrics(base_dir)

    # Compute progress score: lower is better (fewer unsafe constructs)
    progress_score = float(
        current_safety.unsafe_block_count * 3
        + current_safety.raw_ptr_count * 2
        + current_safety.unsafe_api_count
        + current_safety.manual_mem_call_count
    )

    history: list[float] = ctx.get("progress_score_history", [])
    history.append(progress_score)
    ctx["progress_score_history"] = history

    # Check if last validation passed
    validation_results = ctx.get("validation_results") or []
    all_passed = all(vr.ok for vr in validation_results) if validation_results else False

    # Mode: baseline just runs once
    mode = ctx.get("mode", "enhanced")
    if mode == "baseline":
        if all_passed:
            return AgentState.SUCCESS, {"progress_score": progress_score, "all_passed": True}
        return AgentState.STOP_HARD_ERROR, {
            "progress_score": progress_score,
            "error_kind": ctx.get("primary_error_kind", "unknown"),
        }

    # Success: all validation passed
    if all_passed and ctx.get("generated_diff", "").strip():
        return AgentState.SUCCESS, {"progress_score": progress_score, "all_passed": True}

    # Check max iterations
    if iteration >= max_iters:
        return AgentState.STOP_MAX_ITERS, {
            "progress_score": progress_score,
            "iteration_count": iteration,
        }

    # Check no-progress: compare current patch hash and error signature
    current_patch_hash = ctx.get("current_patch_hash")
    last_patch_hash = ctx.get("last_patch_hash")
    current_error_sig = ctx.get("current_error_signature")
    last_error_sig = ctx.get("last_error_signature")

    patch_same = last_patch_hash is not None and current_patch_hash == last_patch_hash
    error_same = last_error_sig is not None and current_error_sig == last_error_sig

    if patch_same or error_same:
        no_progress_count += 1
    else:
        no_progress_count = 0
    ctx["no_progress_count"] = no_progress_count

    if no_progress_limit > 0 and no_progress_count >= no_progress_limit:
        return AgentState.STOP_NO_PROGRESS, {
            "progress_score": progress_score,
            "no_progress_count": no_progress_count,
        }

    # Update tracking for next iteration
    ctx["last_patch_hash"] = current_patch_hash
    ctx["last_error_signature"] = current_error_sig

    # Continue: clear validation results for next iteration
    ctx["validation_results"] = []
    ctx["generated_diff"] = ""

    return AgentState.RETRIEVE_EVIDENCE, {
        "progress_score": progress_score,
        "continue_iteration": True,
    }


# ---------------------------------------------------------------------------
# Handler dispatch table
# ---------------------------------------------------------------------------

HANDLER_MAP: dict[AgentState, Any] = {
    AgentState.INIT: handle_init,
    AgentState.PRECHECK: handle_precheck,
    AgentState.HOTSPOT_DISCOVERY: handle_hotspot_discovery,
    AgentState.SLICE_SELECT: handle_slice_select,
    AgentState.RETRIEVE_EVIDENCE: handle_retrieve_evidence,
    AgentState.BUILD_PROMPT: handle_build_prompt,
    AgentState.GENERATE_PATCH: handle_generate_patch,
    AgentState.VALIDATE_PATCH: handle_validate_patch,
    AgentState.APPLY_PATCH: handle_apply_patch,
    AgentState.RUN_BUILD: handle_run_build,
    AgentState.RUN_TEST: handle_run_test,
    AgentState.RUN_LINT: handle_run_lint,
    AgentState.DIAGNOSE: handle_diagnose,
    AgentState.SCORE_PROGRESS: handle_score_progress,
    AgentState.ROLLBACK: handle_rollback,
}
