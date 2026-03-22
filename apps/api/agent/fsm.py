import hashlib
import json
import re
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from db import connect
from diagnose.parser import parse_diagnostics
from patch.apply import apply_patch, rollback
from patch.generator import generate_controlled_patch
from patch.llm_provider import TemplateEditProvider
from retrieval.service import hybrid_retrieve_evidence
from runner.cmd import run_cmd


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    status: str


def _advisory_lock_key(repo_url: str, ref: str) -> int:
    s = f"{repo_url}#{ref}".encode("utf-8")
    h = hashlib.sha256(s).digest()
    return int.from_bytes(h[:8], "big", signed=True)


def _create_run(conn, *, repo_url: str, ref: str, task_description: str) -> str:
    run_id = str(uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_runs (run_id, repo_url, ref, task_description, status)
            VALUES (%s, %s, %s, %s, %s);
            """,
            (run_id, repo_url, ref, task_description, "INIT"),
        )
    return run_id


def _update_run_status(conn, *, run_id: str, status: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE agent_runs SET status = %s, updated_at = NOW() WHERE run_id = %s;", (status, run_id))


def _insert_step(
    conn,
    *,
    run_id: str,
    step_name: str,
    input_json: dict,
    output_json: dict,
    ok: bool,
    error_msg: str | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_steps (run_id, step_name, input_json, output_json, ok, error_msg)
            VALUES (%s, %s, %s, %s, %s, %s);
            """,
            (run_id, step_name, Jsonb(input_json), Jsonb(output_json), ok, error_msg),
        )


def _insert_patch_row(conn, *, run_id: str, file_path: str, unified_diff: str, status: str, error_msg: str | None) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO patches (run_id, file_path, unified_diff, status, error_msg)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING patch_id;
            """,
            (run_id, file_path, unified_diff, status, error_msg),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("insert_patch_failed")
        return str(row[0])


def _update_patch_row(conn, *, patch_id: str, status: str, error_msg: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE patches SET status = %s, error_msg = %s WHERE patch_id = %s;", (status, error_msg, patch_id))


def _upsert_metric(conn, *, run_id: str, key: str, value: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO metrics (run_id, key, value_json)
            VALUES (%s, %s, %s)
            ON CONFLICT (run_id, key) DO UPDATE SET value_json = EXCLUDED.value_json;
            """,
            (run_id, key, Jsonb(value)),
        )


def _sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def _as_str_list(v: Any) -> list[str]:
    if isinstance(v, list):
        out = []
        for x in v:
            s = str(x or "").strip()
            if s:
                out.append(s)
        return out
    return []


def _safe_int(v: Any) -> int | None:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def _default_evidence_type(*, kind: str, meta: dict[str, Any]) -> str:
    if str(meta.get("evidence_type") or "").strip():
        return str(meta["evidence_type"])
    k = str(kind or "")
    if k == "rust_function_slice":
        return "code_slice"
    if k in {
        "rust_rule_snippet",
        "rust_idiom_template",
        "replacement_strategy",
        "interface_constraint",
        "behavior_constraint",
        "c_source_summary",
        "c_build_info",
        "c_symbol_summary",
    }:
        return k
    return "code"


_RISK_WEIGHTS = {"unsafe": 3, "raw_ptr": 3, "ptr_arith": 2, "manual_mem": 2, "memcpy_memmove": 2}


def _risk_score(tags: list[str]) -> int:
    s = 0
    for t in tags:
        k = str(t or "").strip()
        if not k:
            continue
        s += int(_RISK_WEIGHTS.get(k, 0))
    return s


def _prioritize_high_risk(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored: list[tuple[int, int, int, dict[str, Any]]] = []
    for idx, it in enumerate(items):
        m = it.get("meta")
        meta: dict[str, Any] = m if isinstance(m, dict) else {}
        ev_type = str(meta.get("evidence_type") or "")
        is_code = 1 if ev_type.startswith("code") else 0
        tags = meta.get("risk_tags")
        risk = _risk_score(tags) if isinstance(tags, list) else 0
        scored.append((is_code, risk, -idx, it))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [x[3] for x in scored]


def _pick_target_and_reorder(*, base_dir: Path, items: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    picked_idx = -1
    picked_file = ""
    for i, it in enumerate(items):
        m = it.get("meta")
        meta: dict[str, Any] = m if isinstance(m, dict) else {}
        file_rel = str(meta.get("file") or "").strip()
        ev_type = str(meta.get("evidence_type") or "")
        if not file_rel:
            continue
        if not ev_type.startswith("code"):
            continue
        if (base_dir / file_rel).exists():
            picked_idx = i
            picked_file = file_rel
            break
    if picked_idx <= 0:
        return picked_file, items
    first = items[picked_idx]
    rest = [x for j, x in enumerate(items) if j != picked_idx]
    return picked_file, [first, *rest]


_HUNK_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")


def _extract_first_signature_line(file_text: str) -> tuple[int | None, str | None]:
    for i, raw in enumerate((file_text or "").splitlines(), start=1):
        line = raw.strip()
        if "fn " not in line:
            continue
        if line.startswith(("fn ", "pub fn ", "pub(crate) fn ", "unsafe fn ", "pub(crate) unsafe fn ")):
            return i, raw
    return None, None


def _find_risk_line(file_text: str) -> int | None:
    pats = ["unsafe", "*const", "*mut", "as *const", "as *mut", "malloc", "free", "memcpy", "memmove", ".add(", ".offset("]
    for i, raw in enumerate((file_text or "").splitlines(), start=1):
        for p in pats:
            if p in raw:
                return i
    return None


def _recommended_boundary(*, file_text: str) -> dict[str, Any]:
    lines = (file_text or "").splitlines()
    n = len(lines) if lines else 1
    sig_line, sig_text = _extract_first_signature_line(file_text)
    risk_line = _find_risk_line(file_text)
    anchor = risk_line or (sig_line or 1)
    start = max(1, anchor - 8)
    end = min(n, anchor + 8)
    return {
        "start_line": int(start),
        "end_line": int(end),
        "anchor_line": int(anchor),
        "anchor_kind": "risk" if risk_line else ("signature" if sig_line else "start"),
        "signature_line": int(sig_line) if sig_line else None,
        "signature_text": sig_text,
    }


def _validate_patch_constraints(
    *,
    diff: str,
    target_file: str,
    signature_text: str | None,
    boundary: dict[str, Any],
    max_changed_pairs: int = 20,
    max_total_lines: int = 120,
) -> tuple[bool, dict[str, Any] | None]:
    lines = (diff or "").splitlines()
    if len(lines) > max_total_lines:
        return False, {"code": "too_large", "detail": {"max_total_lines": max_total_lines, "actual_lines": len(lines)}}

    file_paths: set[str] = set()
    hunk_headers = 0
    changed = 0
    old_start: int | None = None

    for ln in lines:
        if ln.startswith("--- a/") or ln.startswith("+++ b/"):
            p = ln.split("/", 1)[1].strip()
            if p:
                file_paths.add(p)
            continue

        if ln.startswith("@@"):
            hunk_headers += 1
            if old_start is None:
                m = _HUNK_RE.match(ln)
                if m:
                    old_start = int(m.group(1))
            continue

        if ln.startswith(("+", "-")) and not ln.startswith(("+++ ", "--- ")):
            changed += 1
            if signature_text and signature_text.strip() and signature_text.strip() in ln[1:]:
                return False, {"code": "signature_changed", "detail": {"signature": signature_text.strip()}}

    if not file_paths:
        return False, {"code": "missing_file_header", "detail": {}}
    if len(file_paths) != 1:
        return False, {"code": "multi_file_patch", "detail": {"files": sorted(file_paths)}}
    only_file = next(iter(file_paths))
    if only_file != target_file:
        return False, {"code": "target_file_mismatch", "detail": {"expected": target_file, "actual": only_file}}
    if hunk_headers != 1:
        return False, {"code": "multi_hunk", "detail": {"hunks": hunk_headers}}
    if changed == 0:
        return False, {"code": "no_changes", "detail": {}}
    if changed > max_changed_pairs * 2:
        return False, {"code": "too_many_changes", "detail": {"max_changed_pairs": max_changed_pairs, "actual_change_lines": changed}}
    if old_start is None:
        return False, {"code": "missing_hunk_header", "detail": {}}

    start_line = boundary.get("start_line")
    end_line = boundary.get("end_line")
    if isinstance(start_line, int) and isinstance(end_line, int):
        if not (start_line <= old_start <= end_line):
            return False, {"code": "outside_boundary", "detail": {"old_start": old_start, "boundary": {"start_line": start_line, "end_line": end_line}}}

    return True, None


def _classify_error_kind(*, runner_exit_code: int | None, stderr: str | None, step_error: str | None) -> str:
    if step_error:
        if step_error.startswith("patch_constraint_violation:"):
            return "patch_constraint_violation"
        if step_error.startswith("patch_apply_failed:"):
            return "apply_fail"
        if step_error == "retrieve_no_results":
            return "retrieve_empty"
    if runner_exit_code == 124 or (stderr and "timeout" in stderr.lower()):
        return "timeout"
    if stderr and "assertion failed" in stderr.lower():
        return "test_fail"
    if runner_exit_code and runner_exit_code != 0:
        return "compile_fail"
    return "unknown"


def _affected_scope_from_file(p: str | None) -> dict[str, Any] | None:
    if not p:
        return None
    s = str(p)
    parts = s.replace("\\", "/").split("/")
    if len(parts) >= 2:
        return {"kind": "module", "value": "/".join(parts[:-1]), "file": s}
    return {"kind": "file", "value": s}


def run_fsm(context: dict) -> RunRecord:
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

    mode = str(context.get("mode") or "enhanced").strip().lower()
    if mode not in {"baseline", "enhanced"}:
        mode = "enhanced"

    max_iters = int(context.get("max_iters") or 2)
    no_progress_limit = int(context.get("no_progress_limit") or 1)
    max_iters = min(max(max_iters, 1), 5)
    no_progress_limit = min(max(no_progress_limit, 0), 5)

    with connect() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s::bigint);", (_advisory_lock_key(repo_url, ref),))
                got = bool(cur.fetchone()[0])
            if not got:
                raise RuntimeError("run_lock_not_acquired")

            run_id = _create_run(conn, repo_url=repo_url, ref=ref, task_description=task_description)

            total_ms = 0
            retrieve_ms = 0
            generate_ms = 0
            execute_ms = 0

            rollback_count = 0
            iteration_count = 0
            no_progress_count = 0
            last_patch_hash: str | None = None
            last_error_signature: str | None = None

            last_issues: list[dict[str, Any]] = []
            final_stop_reason = "unknown"

            primary_error_kind: str | None = None
            primary_file: str | None = None
            primary_line: int | None = None
            primary_error_code: str | None = None
            affected_scope: dict[str, Any] | None = None
            repair_constraints: dict[str, Any] | None = None

            def _step(step_name: str, iter_idx: int, fn):
                nonlocal total_ms
                t0 = time.perf_counter()
                input_json = {
                    "state": step_name,
                    "iter": iter_idx,
                    "repo_url": repo_url,
                    "ref": ref,
                    "snapshot_id": snapshot_id,
                    "workspace_path": str(base_dir),
                }
                ok = True
                error_msg = None
                output_json: dict[str, Any] = {}
                try:
                    _update_run_status(conn, run_id=run_id, status=step_name)
                    output_json = fn(input_json)
                except Exception as e:
                    ok = False
                    error_msg = f"{type(e).__name__}: {e}"
                    output_json = {"traceback": traceback.format_exc()}
                finally:
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    total_ms += elapsed_ms
                    output_json["elapsed_ms"] = elapsed_ms
                    _insert_step(conn, run_id=run_id, step_name=step_name, input_json=input_json, output_json=output_json, ok=ok, error_msg=error_msg)
                return ok, error_msg, output_json

            _step("INIT", 0, lambda _inp: {"run_id": run_id, "max_iters": max_iters, "no_progress_limit": no_progress_limit})

            for k, v in [
                ("mode", mode),
                ("retrieve_count", 0),
                ("patch_generated", False),
                ("patch_applied", False),
                ("execute_ok", False),
                ("diagnose_issue_count", 0),
                ("final_status", "RUNNING"),
                ("iteration_count", 0),
                ("no_progress_count", 0),
                ("rollback_count", 0),
                ("total_ms", 0),
                ("retrieve_ms", 0),
                ("generate_ms", 0),
                ("execute_ms", 0),
                ("final_stop_reason", "RUNNING"),
                ("primary_error_kind", None),
                ("last_patch_hash", None),
                ("last_error_signature", None),
            ]:
                _upsert_metric(conn, run_id=run_id, key=k, value=v)

            if mode == "baseline":
                iteration_count = 1

                def _do_execute(_inp: dict[str, Any]) -> dict[str, Any]:
                    cmd = context.get("cmd") or ["cargo", "test"]
                    if not isinstance(cmd, list):
                        raise ValueError("cmd_must_be_list")
                    env = context.get("env") or {}
                    if not isinstance(env, dict):
                        raise ValueError("env_must_be_dict")
                    rr = run_cmd(
                        cmd=[str(x) for x in cmd],
                        cwd=str(base_dir),
                        env={str(k): str(v) for k, v in env.items()},
                        timeout=int(context.get("timeout", 30)),
                        capture=True,
                    )
                    return {
                        "runner": {
                            "exit_code": rr.exit_code,
                            "duration_ms": rr.duration_ms,
                            "log_path": rr.log_path,
                            "stdout": rr.stdout,
                            "stderr": rr.stderr,
                        }
                    }

                ok_e, err_e, out_e = _step("EXECUTE", iteration_count, _do_execute)
                execute_ms += int(out_e.get("elapsed_ms") or 0)
                runner = out_e.get("runner") if isinstance(out_e.get("runner"), dict) else {}
                exit_code = _safe_int(runner.get("exit_code"))
                stderr = str(runner.get("stderr") or "")
                execute_ok = bool(ok_e) and exit_code == 0
                _upsert_metric(conn, run_id=run_id, key="execute_ok", value=bool(execute_ok))

                if not execute_ok:

                    def _do_diagnose(_inp: dict[str, Any]) -> dict[str, Any]:
                        nonlocal last_issues
                        raw = str(runner.get("log_path") or "") if runner.get("log_path") else stderr
                        last_issues = parse_diagnostics(raw)
                        return {"issues": last_issues}

                    ok_d, err_d, out_d = _step("DIAGNOSE", iteration_count, _do_diagnose)
                    issues = out_d.get("issues") if isinstance(out_d.get("issues"), list) else []
                    _upsert_metric(conn, run_id=run_id, key="diagnose_issue_count", value=int(len(issues)))

                    first_issue = issues[0] if issues and isinstance(issues[0], dict) else {}
                    primary_file = str(first_issue.get("file") or "") or None
                    primary_line = _safe_int(first_issue.get("line"))
                    primary_error_code = str(first_issue.get("error_code") or "") or None
                    affected_scope = _affected_scope_from_file(primary_file)

                    primary_error_kind = _classify_error_kind(runner_exit_code=exit_code, stderr=stderr, step_error=None)
                    _upsert_metric(conn, run_id=run_id, key="primary_error_kind", value=primary_error_kind)

                    final_stop_reason = primary_error_kind
                else:
                    final_stop_reason = "success"

                final_status = "OK" if final_stop_reason == "success" else "FAILED"
                _upsert_metric(conn, run_id=run_id, key="final_status", value=final_status)
                _upsert_metric(conn, run_id=run_id, key="final_stop_reason", value=final_stop_reason)
                _upsert_metric(conn, run_id=run_id, key="iteration_count", value=int(iteration_count))
                _upsert_metric(conn, run_id=run_id, key="no_progress_count", value=int(no_progress_count))
                _upsert_metric(conn, run_id=run_id, key="rollback_count", value=int(rollback_count))
                _upsert_metric(conn, run_id=run_id, key="total_ms", value=int(total_ms))
                _upsert_metric(conn, run_id=run_id, key="retrieve_ms", value=int(retrieve_ms))
                _upsert_metric(conn, run_id=run_id, key="generate_ms", value=int(generate_ms))
                _upsert_metric(conn, run_id=run_id, key="execute_ms", value=int(execute_ms))

                _step(
                    "STOP",
                    iteration_count,
                    lambda _inp: {
                        "status": final_status,
                        "stop_reason": final_stop_reason,
                        "primary_error": {
                            "error_kind": primary_error_kind,
                            "primary_file": primary_file,
                            "primary_line": primary_line,
                            "primary_error_code": primary_error_code,
                            "affected_scope": affected_scope,
                            "repair_constraints": None,
                        },
                    },
                )

                _update_run_status(conn, run_id=run_id, status="FAILED" if final_status != "OK" else "STOP")

                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s::bigint);", (_advisory_lock_key(repo_url, ref),))

                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("SELECT run_id, status FROM agent_runs WHERE run_id = %s;", (run_id,))
                    row = cur.fetchone()
                return RunRecord(run_id=str(row["run_id"]), status=str(row["status"]))

            evidence_items: list[dict[str, Any]] = []
            target_file = ""
            generated_diff = ""

            while iteration_count < max_iters:
                iteration_count += 1
                iter_idx = iteration_count

                def _do_retrieve(_inp: dict[str, Any]) -> dict[str, Any]:
                    nonlocal evidence_items
                    top_k = int(context.get("top_k") or 20)
                    filters = context.get("filters") if isinstance(context.get("filters"), dict) else {}
                    model_id = str(context.get("retrieval_model_id") or "").strip() or None
                    pack = hybrid_retrieve_evidence(
                        snapshot_id=snapshot_id,
                        query_text=task_description,
                        filters=filters,
                        top_k=min(max(top_k, 1), 200),
                        model_id=model_id,
                    )
                    items = list(pack.get("items") or [])
                    evidence_items = []
                    for it in items:
                        meta = dict(it.get("meta") or {}) if isinstance(it, dict) else {}
                        ev_type = _default_evidence_type(kind=str(it.get("kind") or ""), meta=meta)
                        evidence_items.append(
                            {
                                "chunk_id": int(it.get("chunk_id")),
                                "kind": str(it.get("kind") or ""),
                                "lang": str(it.get("lang") or ""),
                                "excerpt": str(it.get("excerpt") or ""),
                                "meta": {
                                    "file": str(meta.get("file") or ""),
                                    "evidence_type": ev_type,
                                    "risk_tags": _as_str_list(meta.get("risk_tags")),
                                    "constraint_tags": _as_str_list(meta.get("constraint_tags")),
                                    "api_tags": _as_str_list(meta.get("api_tags")),
                                    "symbol": (str(meta.get("symbol") or "") or None),
                                    "signature": (str(meta.get("signature") or "") or None),
                                    "calls": _as_str_list(meta.get("calls")),
                                    "strategy_id": (str(meta.get("strategy_id") or "") or None),
                                    "strategy_title": (str(meta.get("strategy_title") or "") or None),
                                    "applies_to_risk": _as_str_list(meta.get("applies_to_risk")),
                                },
                                "score": it.get("score"),
                            }
                        )
                    evidence_items = _prioritize_high_risk(evidence_items)
                    return {"evidence_count": len(evidence_items), "evidence": {"items": evidence_items[: min(len(evidence_items), 20)]}}

                ok_r, err_r, out_r = _step("RETRIEVE", iter_idx, _do_retrieve)
                retrieve_ms += int(out_r.get("elapsed_ms") or 0)
                _upsert_metric(conn, run_id=run_id, key="retrieve_count", value=int(out_r.get("evidence_count") or 0))
                if not ok_r or not evidence_items:
                    final_stop_reason = "retrieve_empty"
                    primary_error_kind = "retrieve_empty"
                    break

                target_file, evidence_items = _pick_target_and_reorder(base_dir=base_dir, items=evidence_items)
                if not target_file:
                    final_stop_reason = "target_file_missing"
                    primary_error_kind = "unknown"
                    break

                file_text = (base_dir / target_file).read_text(encoding="utf-8", errors="replace")
                boundary = _recommended_boundary(file_text=file_text)
                constraints = [
                    "single_file_only",
                    "target_file_must_match",
                    "no_signature_change",
                    "no_full_rewrite",
                    "limit_changed_lines",
                    "prefer_hotspot_neighborhood",
                ]
                forbidden = ["multi_file_patch", "signature_change", "full_file_rewrite"]
                strategies = [
                    it
                    for it in evidence_items
                    if str((it.get("meta") or {}).get("evidence_type") or "").startswith(
                        ("replacement_strategy", "rust_rule_snippet", "interface_constraint", "behavior_constraint")
                    )
                ]
                repair_constraints = {"constraints": constraints, "forbidden": forbidden}

                def _do_generate(_inp: dict[str, Any]) -> dict[str, Any]:
                    nonlocal generated_diff
                    evidence_obj = {
                        "task_description": task_description,
                        "recommended_boundary": {"file": target_file, **{k: boundary.get(k) for k in ["start_line", "end_line", "anchor_line", "anchor_kind"]}},
                        "constraints": constraints,
                        "forbidden": forbidden,
                        "strategies": strategies[:10],
                        "items": evidence_items,
                        "diagnose": last_issues,
                    }
                    evidence_text = json.dumps(evidence_obj, ensure_ascii=False)
                    patch_backend = str(context.get("patch_backend") or "").strip().lower()
                    provider = TemplateEditProvider() if patch_backend in {"template_edit", "demo"} else None
                    generated_diff = generate_controlled_patch(evidence=evidence_text, target_function=target_file, provider=provider)
                    if not generated_diff.strip():
                        raise RuntimeError("patch_generate_failed")

                    ok2, viol = _validate_patch_constraints(
                        diff=generated_diff,
                        target_file=target_file,
                        signature_text=str(boundary.get("signature_text") or "") or None,
                        boundary={"start_line": boundary["start_line"], "end_line": boundary["end_line"]},
                    )
                    if not ok2:
                        raise RuntimeError(f"patch_constraint_violation:{str((viol or {}).get('code') or 'unknown')}|{json.dumps(viol or {})}")
                    return {
                        "diff_len": len(generated_diff),
                        "target_file": target_file,
                        "recommended_boundary": evidence_obj["recommended_boundary"],
                        "constraints": constraints,
                        "forbidden": forbidden,
                    }

                ok_g, err_g, out_g = _step("GENERATE", iter_idx, _do_generate)
                generate_ms += int(out_g.get("elapsed_ms") or 0)
                _upsert_metric(conn, run_id=run_id, key="patch_generated", value=bool(generated_diff.strip()))
                if not ok_g:
                    primary_error_kind = "patch_constraint_violation" if err_g and "patch_constraint_violation:" in err_g else "unknown"
                    final_stop_reason = "patch_constraint_violation" if primary_error_kind == "patch_constraint_violation" else "generate_error"
                    break

                current_patch_hash = _sha256_text(generated_diff)
                _upsert_metric(conn, run_id=run_id, key="last_patch_hash", value=current_patch_hash)

                last_backup_dir = None
                last_patch_id = None

                def _do_apply(_inp: dict[str, Any]) -> dict[str, Any]:
                    nonlocal last_backup_dir, last_patch_id
                    apply_result = apply_patch(base_dir, generated_diff)
                    patch_err = apply_result.error_msg
                    if patch_err and not apply_result.ok:
                        patch_err = patch_err + "\n" + traceback.format_exc()
                    file_path = apply_result.file_paths[0] if apply_result.file_paths else target_file
                    last_patch_id = _insert_patch_row(conn, run_id=run_id, file_path=file_path, unified_diff=generated_diff, status=apply_result.status, error_msg=patch_err)
                    last_backup_dir = apply_result.backup_dir
                    return {
                        "patch_id": last_patch_id,
                        "patch_status": apply_result.status,
                        "patch_ok": bool(apply_result.ok),
                        "patch_error": apply_result.error_msg,
                        "file_paths": apply_result.file_paths,
                        "backup_dir": last_backup_dir,
                    }

                ok_a, err_a, out_a = _step("APPLY", iter_idx, _do_apply)
                _upsert_metric(conn, run_id=run_id, key="patch_applied", value=bool(out_a.get("patch_ok")))
                if not ok_a or not bool(out_a.get("patch_ok")):
                    primary_error_kind = "apply_fail"
                    final_stop_reason = "apply_fail"
                    break

                def _do_execute(_inp: dict[str, Any]) -> dict[str, Any]:
                    cmd = context.get("cmd") or ["cargo", "test"]
                    if not isinstance(cmd, list):
                        raise ValueError("cmd_must_be_list")
                    env = context.get("env") or {}
                    if not isinstance(env, dict):
                        raise ValueError("env_must_be_dict")
                    rr = run_cmd(
                        cmd=[str(x) for x in cmd],
                        cwd=str(base_dir),
                        env={str(k): str(v) for k, v in env.items()},
                        timeout=int(context.get("timeout", 30)),
                        capture=True,
                    )
                    return {
                        "runner": {
                            "exit_code": rr.exit_code,
                            "duration_ms": rr.duration_ms,
                            "log_path": rr.log_path,
                            "stdout": rr.stdout,
                            "stderr": rr.stderr,
                        }
                    }

                ok_e, err_e, out_e = _step("EXECUTE", iter_idx, _do_execute)
                execute_ms += int(out_e.get("elapsed_ms") or 0)
                runner = out_e.get("runner") if isinstance(out_e.get("runner"), dict) else {}
                exit_code = _safe_int(runner.get("exit_code"))
                stderr = str(runner.get("stderr") or "")
                execute_ok = bool(ok_e) and exit_code == 0
                _upsert_metric(conn, run_id=run_id, key="execute_ok", value=bool(execute_ok))
                if execute_ok:
                    final_stop_reason = "success"
                    break

                def _do_diagnose(_inp: dict[str, Any]) -> dict[str, Any]:
                    nonlocal last_issues
                    raw = str(runner.get("log_path") or "") if runner.get("log_path") else stderr
                    last_issues = parse_diagnostics(raw)
                    return {"issues": last_issues}

                ok_d, err_d, out_d = _step("DIAGNOSE", iter_idx, _do_diagnose)
                issues = out_d.get("issues") if isinstance(out_d.get("issues"), list) else []
                _upsert_metric(conn, run_id=run_id, key="diagnose_issue_count", value=int(len(issues)))

                first_issue = issues[0] if issues and isinstance(issues[0], dict) else {}
                primary_file = str(first_issue.get("file") or "") or None
                primary_line = _safe_int(first_issue.get("line"))
                primary_error_code = str(first_issue.get("error_code") or "") or None
                affected_scope = _affected_scope_from_file(primary_file)

                primary_error_kind = _classify_error_kind(runner_exit_code=exit_code, stderr=stderr, step_error=None)
                error_signature = "|".join([str(primary_error_kind or ""), str(primary_file or ""), str(primary_error_code or "")])
                _upsert_metric(conn, run_id=run_id, key="primary_error_kind", value=primary_error_kind)

                if last_backup_dir:
                    rollback(base_dir, Path(last_backup_dir))
                    rollback_count += 1
                    _upsert_metric(conn, run_id=run_id, key="rollback_count", value=int(rollback_count))
                    if last_patch_id:
                        _update_patch_row(conn, patch_id=str(last_patch_id), status="rolled_back", error_msg=f"rolled_back_after_{primary_error_kind}")

                patch_same = last_patch_hash is not None and current_patch_hash == last_patch_hash
                error_same = last_error_signature is not None and error_signature == last_error_signature
                no_progress_hit = patch_same or error_same
                no_progress_count = (no_progress_count + 1) if no_progress_hit else 0
                _upsert_metric(conn, run_id=run_id, key="no_progress_count", value=int(no_progress_count))

                last_patch_hash = current_patch_hash
                last_error_signature = error_signature
                _upsert_metric(conn, run_id=run_id, key="last_patch_hash", value=last_patch_hash)
                _upsert_metric(conn, run_id=run_id, key="last_error_signature", value=last_error_signature)

                if no_progress_limit > 0 and no_progress_count >= no_progress_limit:
                    final_stop_reason = "no_progress"
                    break

            final_status = "OK" if final_stop_reason == "success" else "FAILED"
            _upsert_metric(conn, run_id=run_id, key="final_status", value=final_status)
            _upsert_metric(conn, run_id=run_id, key="final_stop_reason", value=final_stop_reason)
            _upsert_metric(conn, run_id=run_id, key="iteration_count", value=int(iteration_count))
            _upsert_metric(conn, run_id=run_id, key="total_ms", value=int(total_ms))
            _upsert_metric(conn, run_id=run_id, key="retrieve_ms", value=int(retrieve_ms))
            _upsert_metric(conn, run_id=run_id, key="generate_ms", value=int(generate_ms))
            _upsert_metric(conn, run_id=run_id, key="execute_ms", value=int(execute_ms))

            _step(
                "STOP",
                iteration_count,
                lambda _inp: {
                    "status": final_status,
                    "stop_reason": final_stop_reason,
                    "primary_error": {
                        "error_kind": primary_error_kind,
                        "primary_file": primary_file,
                        "primary_line": primary_line,
                        "primary_error_code": primary_error_code,
                        "affected_scope": affected_scope,
                        "repair_constraints": repair_constraints,
                    },
                },
            )

            _update_run_status(conn, run_id=run_id, status="FAILED" if final_status != "OK" else "STOP")

            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s::bigint);", (_advisory_lock_key(repo_url, ref),))

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT run_id, status FROM agent_runs WHERE run_id = %s;", (run_id,))
            row = cur.fetchone()
    return RunRecord(run_id=str(row["run_id"]), status=str(row["status"]))
