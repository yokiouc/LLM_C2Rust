import json
import logging
import time
from typing import Any

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation
from starlette.exceptions import HTTPException as StarletteHTTPException

from crud import create_project, create_snapshot, delete_chunk, delete_project, delete_snapshot, insert_chunk, list_chunks, list_projects, list_snapshots
from db import connect
from retrieval.service import hybrid_retrieve_evidence
from agent.fsm import run_fsm

logger = logging.getLogger("c2rust_api")
logging.basicConfig(level=logging.INFO, format="%(message)s")

app = FastAPI()


def json_error(*, status_code: int, error: str, code: str):
    return JSONResponse(status_code=status_code, content={"error": error, "code": code})


@app.exception_handler(RequestValidationError)
def validation_exception_handler(_request: Request, _exc: RequestValidationError):
    return json_error(status_code=422, error="validation_error", code="validation_error")


@app.exception_handler(StarletteHTTPException)
def http_exception_handler(_request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return json_error(status_code=404, error="not_found", code="not_found")
    return json_error(status_code=exc.status_code, error="http_error", code="http_error")


@app.exception_handler(Exception)
def unhandled_exception_handler(_request: Request, _exc: Exception):
    logger.exception(json.dumps({"event": "unhandled_exception"}))
    return json_error(status_code=500, error="internal_error", code="internal_error")


class CreateProjectIn(BaseModel):
    name: str = Field(min_length=1)
    desc: str | None = None


class CreateSnapshotIn(BaseModel):
    project_id: int
    commit_sha: str | None = None
    branch: str | None = None


class InsertChunkIn(BaseModel):
    snapshot_id: int
    kind: str = Field(min_length=1, max_length=64)
    lang: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1)
    meta: dict[str, Any]


class RetrieveIn(BaseModel):
    snapshot_id: int
    query_text: str = Field(min_length=1)
    filters: dict[str, Any] = Field(default_factory=dict)
    top_k: int = 50


class AgentRunIn(BaseModel):
    snapshot_id: int
    workspace_path: str = Field(min_length=1)
    task_description: str = Field(min_length=1)
    repo_url: str | None = None
    ref: str | None = None
    mode: str | None = None
    cmd: list[str] | None = None
    timeout: int | None = None
    env: dict[str, Any] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)
    top_k: int = 20
    retrieval_model_id: str | None = None
    patch_backend: str | None = None
    max_iters: int | None = None
    no_progress_limit: int | None = None


@app.get("/health")
def health():
    try:
        with connect(timeout_seconds=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        return {"ok": True, "db": "ok"}
    except Exception:
        return JSONResponse(status_code=503, content={"ok": False, "db": "error"})


@app.post("/projects", status_code=201)
def post_projects(body: CreateProjectIn):
    started = time.perf_counter()
    try:
        with connect() as conn:
            project_id = create_project(conn, name=body.name, description=body.desc)
        logger.info(json.dumps({"event": "write", "table": "projects", "pk": project_id, "ms": int((time.perf_counter() - started) * 1000)}))
        return {"project_id": project_id}
    except UniqueViolation:
        return json_error(status_code=409, error="project_already_exists", code="conflict")
    except Exception:
        logger.error(json.dumps({"event": "error", "table": "projects"}))
        raise


@app.get("/projects")
def get_projects(limit: int = 50, offset: int = 0):
    with connect() as conn:
        rows = list_projects(conn, limit=min(max(limit, 1), 200), offset=max(offset, 0))
    return rows


@app.delete("/projects/{project_id}", status_code=204)
def delete_projects(project_id: int):
    started = time.perf_counter()
    try:
        with connect() as conn:
            ok = delete_project(conn, project_id=project_id)
        if not ok:
            return json_error(status_code=404, error="not_found", code="not_found")
        logger.info(json.dumps({"event": "write", "table": "projects", "pk": project_id, "ms": int((time.perf_counter() - started) * 1000)}))
        return JSONResponse(status_code=204, content=None)
    except Exception:
        logger.error(json.dumps({"event": "error", "table": "projects", "pk": project_id}))
        raise


@app.post("/snapshots", status_code=201)
def post_snapshots(body: CreateSnapshotIn):
    started = time.perf_counter()
    try:
        with connect() as conn:
            snapshot_id = create_snapshot(conn, project_id=body.project_id, commit_sha=body.commit_sha, branch=body.branch)
        logger.info(json.dumps({"event": "write", "table": "repo_snapshots", "pk": snapshot_id, "ms": int((time.perf_counter() - started) * 1000)}))
        return {"snapshot_id": snapshot_id}
    except ForeignKeyViolation:
        return json_error(status_code=409, error="project_not_found", code="foreign_key_violation")
    except UniqueViolation:
        return json_error(status_code=409, error="snapshot_already_exists", code="conflict")
    except Exception:
        logger.error(json.dumps({"event": "error", "table": "repo_snapshots"}))
        raise


@app.get("/snapshots")
def get_snapshots(project_id: int, limit: int = 50, offset: int = 0):
    with connect() as conn:
        rows = list_snapshots(conn, project_id=project_id, limit=min(max(limit, 1), 200), offset=max(offset, 0))
    return rows


@app.delete("/snapshots/{snapshot_id}", status_code=204)
def delete_snapshots(snapshot_id: int):
    started = time.perf_counter()
    try:
        with connect() as conn:
            ok = delete_snapshot(conn, snapshot_id=snapshot_id)
        if not ok:
            return json_error(status_code=404, error="not_found", code="not_found")
        logger.info(json.dumps({"event": "write", "table": "repo_snapshots", "pk": snapshot_id, "ms": int((time.perf_counter() - started) * 1000)}))
        return JSONResponse(status_code=204, content=None)
    except Exception:
        logger.error(json.dumps({"event": "error", "table": "repo_snapshots", "pk": snapshot_id}))
        raise


@app.post("/chunks", status_code=201)
def post_chunks(body: InsertChunkIn):
    if "file" not in body.meta:
        return json_error(status_code=422, error="meta_missing_file", code="validation_error")

    started = time.perf_counter()
    try:
        with connect() as conn:
            chunk_id = insert_chunk(
                conn,
                snapshot_id=body.snapshot_id,
                kind=body.kind,
                lang=body.lang,
                content=body.content,
                meta=body.meta,
            )
        logger.info(json.dumps({"event": "write", "table": "code_chunks", "pk": chunk_id, "ms": int((time.perf_counter() - started) * 1000)}))
        return {"chunk_id": chunk_id}
    except ForeignKeyViolation:
        return json_error(status_code=409, error="snapshot_not_found", code="foreign_key_violation")
    except UniqueViolation:
        return json_error(status_code=409, error="chunk_already_exists", code="conflict")
    except CheckViolation:
        return json_error(status_code=422, error="invalid_meta", code="validation_error")
    except Exception:
        logger.error(json.dumps({"event": "error", "table": "code_chunks"}))
        raise


@app.get("/chunks")
def get_chunks(snapshot_id: int, limit: int = 50, offset: int = 0):
    with connect() as conn:
        rows = list_chunks(conn, snapshot_id=snapshot_id, limit=min(max(limit, 1), 200), offset=max(offset, 0))
    return rows


@app.delete("/chunks/{chunk_id}", status_code=204)
def delete_chunks(chunk_id: int):
    started = time.perf_counter()
    try:
        with connect() as conn:
            ok = delete_chunk(conn, chunk_id=chunk_id)
        if not ok:
            return json_error(status_code=404, error="not_found", code="not_found")
        logger.info(json.dumps({"event": "write", "table": "code_chunks", "pk": chunk_id, "ms": int((time.perf_counter() - started) * 1000)}))
        return JSONResponse(status_code=204, content=None)
    except Exception:
        logger.error(json.dumps({"event": "error", "table": "code_chunks", "pk": chunk_id}))
        raise


@app.post("/retrieve")
def post_retrieve(body: RetrieveIn):
    try:
        result = hybrid_retrieve_evidence(
            snapshot_id=body.snapshot_id,
            query_text=body.query_text,
            filters=body.filters or {},
            top_k=min(max(body.top_k, 1), 200),
        )
        return result
    except Exception:
        return json_error(status_code=500, error="retrieve_failed", code="internal_error")


@app.post("/agent/run", status_code=201)
def post_agent_run(body: AgentRunIn):
    try:
        rec = run_fsm(
            {
                "snapshot_id": body.snapshot_id,
                "workspace_path": body.workspace_path,
                "task_description": body.task_description,
                "repo_url": body.repo_url,
                "ref": body.ref,
                "mode": body.mode,
                "cmd": body.cmd,
                "timeout": body.timeout,
                "env": body.env,
                "filters": body.filters,
                "top_k": body.top_k,
                "retrieval_model_id": body.retrieval_model_id,
                "patch_backend": body.patch_backend,
                "max_iters": body.max_iters,
                "no_progress_limit": body.no_progress_limit,
            }
        )
        return {"run_id": rec.run_id, "status": rec.status}
    except Exception as e:
        if str(e) == "run_lock_not_acquired":
            return json_error(status_code=409, error="run_locked", code="conflict")
        logger.exception(json.dumps({"event": "error", "endpoint": "agent_run"}))
        return json_error(status_code=500, error="agent_run_failed", code="internal_error")


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    with connect() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                "SELECT run_id, repo_url, ref, task_description, status, created_at, updated_at FROM agent_runs WHERE run_id = %s;",
                (run_id,),
            )
            run = cur.fetchone()
        if not run:
            return json_error(status_code=404, error="not_found", code="not_found")

        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                """
                SELECT step_id, step_name, input_json, output_json, ok, error_msg, created_at
                FROM agent_steps
                WHERE run_id = %s
                ORDER BY created_at ASC;
                """,
                (run_id,),
            )
            steps = cur.fetchall()

        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                """
                SELECT patch_id, file_path, unified_diff, status, error_msg, created_at
                FROM patches
                WHERE run_id = %s
                ORDER BY created_at ASC;
                """,
                (run_id,),
            )
            patches = cur.fetchall()

        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                """
                SELECT key, value_json
                FROM metrics
                WHERE run_id = %s
                ORDER BY key ASC;
                """,
                (run_id,),
            )
            metric_rows = cur.fetchall()

    metrics = {str(r["key"]): r["value_json"] for r in (metric_rows or [])}

    def _last_step(name: str):
        for s in reversed(steps):
            if s.get("step_name") == name:
                return s
        return None

    retrieve_step = _last_step("RETRIEVE")
    generate_step = _last_step("GENERATE")
    execute_step = _last_step("EXECUTE")
    diagnose_step = _last_step("DIAGNOSE")

    evidence_items = []
    if retrieve_step and isinstance(retrieve_step.get("output_json"), dict):
        out = retrieve_step["output_json"]
        ev = out.get("evidence") if isinstance(out.get("evidence"), dict) else {}
        evidence_items = list(ev.get("items") or []) if isinstance(ev, dict) else []

    target_file = ""
    recommended_boundary = None
    patch_constraints = None
    constraint_violation = None
    if generate_step and isinstance(generate_step.get("output_json"), dict):
        gout = generate_step["output_json"]
        target_file = str(gout.get("target_file") or "")
        if isinstance(gout.get("recommended_boundary"), dict):
            recommended_boundary = gout.get("recommended_boundary")
        if isinstance(gout.get("constraints"), list):
            patch_constraints = gout.get("constraints")
        if isinstance(gout.get("constraint_violation"), dict):
            constraint_violation = gout.get("constraint_violation")

    patch_obj = patches[0] if patches else None
    patch_status = str(patch_obj.get("status") or "") if isinstance(patch_obj, dict) else ""
    patch_file = str(patch_obj.get("file_path") or "") if isinstance(patch_obj, dict) else ""

    runner_exit = None
    if execute_step and isinstance(execute_step.get("output_json"), dict):
        runner = execute_step["output_json"].get("runner")
        if isinstance(runner, dict) and runner.get("exit_code") is not None:
            runner_exit = int(runner["exit_code"])

    issue_count = 0
    if diagnose_step and isinstance(diagnose_step.get("output_json"), dict):
        issues = diagnose_step["output_json"].get("issues")
        if isinstance(issues, list):
            issue_count = len(issues)

    risk_counts: dict[str, int] = {}
    strategy_evidence: list[dict[str, Any]] = []
    for it in evidence_items:
        m = it.get("meta") if isinstance(it, dict) else None
        meta: dict[str, Any] = m if isinstance(m, dict) else {}
        ev_type = str(meta.get("evidence_type") or "")
        if ev_type.startswith("code"):
            tags = meta.get("risk_tags")
            if isinstance(tags, list):
                for t in tags:
                    k = str(t or "").strip()
                    if not k:
                        continue
                    risk_counts[k] = int(risk_counts.get(k, 0)) + 1
        else:
            strategy_evidence.append(
                {
                    "evidence_type": ev_type,
                    "strategy_title": meta.get("strategy_title"),
                    "applies_to_risk": meta.get("applies_to_risk"),
                    "api_tags": meta.get("api_tags"),
                    "constraint_tags": meta.get("constraint_tags"),
                    "file": meta.get("file"),
                }
            )

    summary = {
        "evidence_count": int(metrics.get("retrieve_count") or len(evidence_items) or 0),
        "evidence_top": evidence_items[:5],
        "risk_overview": {"counts": risk_counts},
        "strategy_evidence_top": strategy_evidence[:5],
        "target_file": target_file or patch_file,
        "recommended_boundary": recommended_boundary,
        "patch_constraints": patch_constraints,
        "constraint_violation": constraint_violation,
        "patch_status": patch_status,
        "execute_exit_code": runner_exit,
        "diagnose_issue_count": int(metrics.get("diagnose_issue_count") or issue_count or 0),
        "final_status": str(metrics.get("final_status") or run["status"]),
        "iteration_count": metrics.get("iteration_count"),
        "no_progress_count": metrics.get("no_progress_count"),
        "rollback_count": metrics.get("rollback_count"),
        "total_ms": metrics.get("total_ms"),
        "retrieve_ms": metrics.get("retrieve_ms"),
        "generate_ms": metrics.get("generate_ms"),
        "execute_ms": metrics.get("execute_ms"),
        "final_stop_reason": metrics.get("final_stop_reason"),
        "primary_error_kind": metrics.get("primary_error_kind"),
        "last_patch_hash": metrics.get("last_patch_hash"),
        "last_error_signature": metrics.get("last_error_signature"),
    }

    return {
        "run_id": run["run_id"],
        "status": run["status"],
        "steps": steps,
        "patches": patches,
        "metrics": metrics,
        "summary": summary,
        "created_at": run["created_at"],
    }
