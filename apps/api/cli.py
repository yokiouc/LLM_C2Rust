import json
import os
import sys
import time
import re
from pathlib import Path
from typing import Any

import typer
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation
from psycopg.rows import dict_row
from tqdm import tqdm

from crud import create_project, create_snapshot, delete_chunk, insert_chunk, list_chunks
from db import connect
from embed.exceptions import EmbeddingException
from embed.service import Chunk, batch_embed_and_upsert
from embed.providers import provider_from_model_row
from ingest.treesitter_chunker import chunk as chunk_rs
from tools.c2rust_runner import run as run_c2rust_tool
from patch.engine import load_config as load_patch_config
from patch.engine import run_converge as run_patch_converge

app = typer.Typer(add_completion=False)


def fail(*, error: str, code: str, exit_code: int = 1):
    sys.stderr.write(json.dumps({"error": error, "code": code}) + "\n")
    raise typer.Exit(exit_code)


def _read_c2rust_tool_config() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return {}
    raw = pyproject.read_bytes()
    try:
        import tomllib

        data = tomllib.loads(raw.decode("utf-8"))
    except Exception:
        try:
            import tomli

            data = tomli.loads(raw.decode("utf-8"))
        except Exception:
            return {}
    return dict(data.get("tool", {}).get("c2rust", {}) or {})


def _dedup_str_list(xs: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in xs:
        s = str(x or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


_CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_CALL_SKIP = {"fn", "if", "for", "while", "match", "loop", "return", "unsafe", "let", "pub", "mod", "struct", "enum", "impl", "use"}


def _extract_signature(content: str) -> str | None:
    for raw in (content or "").splitlines()[:30]:
        line = raw.strip()
        if "fn " not in line:
            continue
        if line.startswith(("fn ", "pub fn ", "pub(crate) fn ", "pub(crate) unsafe fn ", "unsafe fn ")):
            if "{" in line:
                return line.split("{", 1)[0].strip()
            return line
    return None


def _extract_calls(content: str) -> list[str]:
    hits = []
    for m in _CALL_RE.finditer(content or ""):
        name = m.group(1)
        if name in _CALL_SKIP:
            continue
        hits.append(name)
        if len(hits) >= 40:
            break
    return _dedup_str_list(hits)[:20]


def _scan_risk_tags(content: str) -> list[str]:
    s = content or ""
    tags: list[str] = []
    if "unsafe" in s:
        tags.append("unsafe")
    if any(x in s for x in ["*const", "*mut", "as *const", "as *mut"]):
        tags.append("raw_ptr")
    if any(x in s for x in ["malloc", "free"]):
        tags.append("manual_mem")
    if any(x in s for x in ["memcpy", "memmove"]):
        tags.append("memcpy_memmove")
    if any(x in s for x in [".add(", ".offset(", "wrapping_add", "wrapping_sub"]):
        tags.append("ptr_arith")
    return _dedup_str_list(tags)


def _scan_api_tags(content: str) -> list[str]:
    s = content or ""
    tags: list[str] = []
    if "Vec" in s:
        tags.append("Vec")
    if "Box" in s:
        tags.append("Box")
    for api in ["copy_from_slice", "ptr::copy", "ptr::copy_nonoverlapping", "malloc", "free", "memcpy", "memmove"]:
        if api in s:
            tags.append(api)
    return _dedup_str_list(tags)


@app.command("create_project")
def create_project_cmd(name: str, desc: str | None = typer.Option(None, "--desc")):
    started = time.perf_counter()
    try:
        with connect() as conn:
            project_id = create_project(conn, name=name, description=desc)
        sys.stdout.write(json.dumps({"project_id": project_id, "ms": int((time.perf_counter() - started) * 1000)}) + "\n")
    except UniqueViolation:
        fail(error="project_already_exists", code="conflict")


@app.command("create_snapshot")
def create_snapshot_cmd(
    project_id: int,
    commit_sha: str | None = typer.Option(None, "--commit_sha"),
    branch: str | None = typer.Option(None, "--branch"),
):
    started = time.perf_counter()
    try:
        with connect() as conn:
            snapshot_id = create_snapshot(conn, project_id=project_id, commit_sha=commit_sha, branch=branch)
        sys.stdout.write(json.dumps({"snapshot_id": snapshot_id, "ms": int((time.perf_counter() - started) * 1000)}) + "\n")
    except ForeignKeyViolation:
        fail(error="project_not_found", code="foreign_key_violation")
    except UniqueViolation:
        fail(error="snapshot_already_exists", code="conflict")


@app.command("insert_chunk")
def insert_chunk_cmd(
    snapshot_id: int,
    kind: str = typer.Option(..., "--kind"),
    lang: str = typer.Option(..., "--lang"),
    content: str = typer.Option(..., "--content"),
    meta: str = typer.Option(..., "--meta"),
):
    started = time.perf_counter()
    try:
        meta_obj: dict[str, Any] = json.loads(meta)
    except Exception:
        fail(error="invalid_meta_json", code="validation_error")

    if "file" not in meta_obj:
        fail(error="meta_missing_file", code="validation_error")

    try:
        with connect() as conn:
            chunk_id = insert_chunk(conn, snapshot_id=snapshot_id, kind=kind, lang=lang, content=content, meta=meta_obj)
        sys.stdout.write(json.dumps({"chunk_id": chunk_id, "ms": int((time.perf_counter() - started) * 1000)}) + "\n")
    except ForeignKeyViolation:
        fail(error="snapshot_not_found", code="foreign_key_violation")
    except UniqueViolation:
        fail(error="chunk_already_exists", code="conflict")
    except CheckViolation:
        fail(error="invalid_meta", code="validation_error")


@app.command("list_chunks")
def list_chunks_cmd(
    snapshot_id: int,
    limit: int = typer.Option(50, "--limit"),
    offset: int = typer.Option(0, "--offset"),
):
    with connect() as conn:
        rows = list_chunks(conn, snapshot_id=snapshot_id, limit=min(max(limit, 1), 200), offset=max(offset, 0))
    sys.stdout.write(json.dumps(rows, default=str) + "\n")


@app.command("delete_chunk")
def delete_chunk_cmd(chunk_id: int):
    started = time.perf_counter()
    with connect() as conn:
        ok = delete_chunk(conn, chunk_id=chunk_id)
    if not ok:
        fail(error="not_found", code="not_found")
    sys.stdout.write(json.dumps({"ok": True, "ms": int((time.perf_counter() - started) * 1000)}) + "\n")


@app.command("embed_chunks")
def embed_chunks_cmd(
    model_id: str = typer.Option(..., "--model_id"),
    snapshot_id: int = typer.Option(..., "--snapshot_id"),
    chunk_table: str = typer.Option("code_chunks", "--chunk_table"),
):
    started = time.perf_counter()
    if chunk_table not in {"code_chunks"}:
        fail(error="invalid_chunk_table", code="validation_error")
    try:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT chunk_id, content FROM " + chunk_table + " WHERE snapshot_id = %s ORDER BY chunk_id;", (snapshot_id,))
                rows = cur.fetchall()
        chunks = [Chunk(chunk_id=int(r["chunk_id"]), content=str(r["content"])) for r in rows]

        written = 0
        for i in tqdm(range(0, len(chunks), 128), desc="embed_chunks"):
            written += batch_embed_and_upsert(chunks=chunks[i : i + 128], model_id=model_id, snapshot_id=snapshot_id)
    except EmbeddingException as e:
        fail(error=str(e), code="embedding_error")
    except Exception:
        fail(error="embed_failed", code="internal_error")

    sys.stdout.write(json.dumps({"written": written, "ms": int((time.perf_counter() - started) * 1000)}) + "\n")


@app.command("run_c2rust")
def run_c2rust_cmd(
    c_project_path: str,
    output_dir: str,
):
    started = time.perf_counter()
    r = run_c2rust_tool(c_project_path=Path(c_project_path), output_dir=Path(output_dir))
    sys.stdout.write(
        json.dumps(
            {
                "snapshot_version": r.snapshot_version,
                "c2rust_version": r.c2rust_version,
                "exit_code": r.exit_code,
                "duration_ms": r.duration_ms,
                "log_path": r.log_path,
                "manifest_path": r.manifest_path,
                "rust_workspace_dir": r.rust_workspace_dir,
                "ms": int((time.perf_counter() - started) * 1000),
            }
        )
        + "\n"
    )
    if r.exit_code != 0:
        raise typer.Exit(1)


@app.command("ingest_workspace")
def ingest_workspace_cmd(
    rust_workspace_dir: str,
    project_name: str | None = typer.Option(None, "--project_name"),
    skip_tree_sitter: bool = typer.Option(False, "--skip-tree-sitter"),
):
    started = time.perf_counter()
    root = Path(rust_workspace_dir).resolve()
    cfg = _read_c2rust_tool_config()
    ts_cfg = cfg.get("treesitter") if isinstance(cfg.get("treesitter"), dict) else {}
    fallback_window_lines = int((ts_cfg or {}).get("fallback_window_lines") or 50)
    max_bytes = int((ts_cfg or {}).get("max_bytes") or 1048576)
    manifest_path = root / ".c2rust_manifest.json"
    snapshot_version = ""
    c2rust_version = None
    if manifest_path.exists():
        try:
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
            snapshot_version = str(m.get("snapshot_version") or "")
            c2rust_version = (str(m.get("c2rust_version")) if m.get("c2rust_version") is not None else None)
        except Exception:
            snapshot_version = ""
            c2rust_version = None

    if not snapshot_version:
        snapshot_version = str(root)

    name = project_name or root.name
    snapshot_id = 0
    os_env_backup = dict(os.environ)
    try:
        os.environ["RUST_WORKSPACE_ROOT"] = str(root)
        os.environ["FALLBACK_WINDOW_LINES"] = str(fallback_window_lines)
        os.environ["TREE_SITTER_MAX_BYTES"] = str(max_bytes)
        if skip_tree_sitter:
            os.environ["SKIP_TREE_SITTER"] = "1"
        with connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SELECT project_id FROM projects WHERE name = %s;", (name,))
                    row = cur.fetchone()
                    if row:
                        project_id = int(row[0])
                    else:
                        cur.execute("INSERT INTO projects (name) VALUES (%s) RETURNING project_id;", (name,))
                        project_id = int(cur.fetchone()[0])

                    try:
                        cur.execute(
                            "INSERT INTO repo_snapshots (project_id, commit_sha, branch) VALUES (%s, %s, %s) RETURNING snapshot_id;",
                            (project_id, snapshot_version, None),
                        )
                        snapshot_id = int(cur.fetchone()[0])
                    except UniqueViolation:
                        cur.execute(
                            "SELECT snapshot_id FROM repo_snapshots WHERE project_id = %s AND commit_sha = %s;",
                            (project_id, snapshot_version),
                        )
                        snapshot_id = int(cur.fetchone()[0])

            written = 0
            for rs_file in sorted(root.rglob("*.rs"), key=lambda p: p.as_posix().lower()):
                slices = chunk_rs(rs_file)
                for s in slices:
                    evidence_type = "code_window" if s.degraded else "code_slice"
                    risk_tags = _scan_risk_tags(s.content)
                    api_tags = _scan_api_tags(s.content)
                    signature = _extract_signature(s.content)
                    calls = _extract_calls(s.content)
                    meta = {
                        "file": s.file_rel,
                        "evidence_type": evidence_type,
                        "risk_tags": risk_tags,
                        "constraint_tags": ["no_signature_change", "no_full_rewrite"],
                        "api_tags": api_tags,
                        "symbol": s.name,
                        "signature": signature,
                        "calls": calls,
                        "origin_function": s.name,
                        "span": {
                            "start": {"row": s.start_row, "col": s.start_col},
                            "end": {"row": s.end_row, "col": s.end_col},
                        },
                        "degraded": s.degraded,
                        "degrade_reason": s.degrade_reason,
                        "c2rust_version": c2rust_version,
                        "snapshot_version": snapshot_version,
                    }
                    insert_chunk(conn, snapshot_id=snapshot_id, kind="rust_function_slice", lang="rust", content=s.content, meta=meta)
                    written += 1
    finally:
        os.environ.clear()
        os.environ.update(os_env_backup)

    sys.stdout.write(
        json.dumps(
            {
                "project_name": name,
                "snapshot_id": snapshot_id,
                "snapshot_version": snapshot_version,
                "written": written,
                "ms": int((time.perf_counter() - started) * 1000),
            }
        )
        + "\n"
    )


@app.command("converge_patch")
def converge_patch_cmd(
    base_dir: str,
    evidence_path: str,
    target_function: str,
    out_dir: str,
    config_path: str | None = typer.Option(None, "--config"),
    max_iters: int | None = typer.Option(None, "--max-iters"),
    no_progress_limit: int | None = typer.Option(None, "--no-progress-limit"),
    validate_cmd: str | None = typer.Option(None, "--validate-cmd"),
):
    started = time.perf_counter()
    cfg_path = Path(config_path) if config_path else Path(__file__).resolve().parent / "patch" / "convergence.yaml"
    cfg, cfg_hash = load_patch_config(path=cfg_path, overrides={"max_iters": max_iters, "no_progress_limit": no_progress_limit})
    evidence = Path(evidence_path).read_text(encoding="utf-8", errors="replace")
    best, history = run_patch_converge(
        base_dir=Path(base_dir),
        evidence=evidence,
        target_function=target_function,
        prompt_template_path=Path(__file__).resolve().parent / "patch" / "controlled_prompt.md",
        config=cfg,
        config_hash=cfg_hash,
        out_dir=Path(out_dir),
        validate_cmd=validate_cmd.split() if validate_cmd else None,
    )
    sys.stdout.write(
        json.dumps({"best_diff_len": len(best), "iters": len(history), "config_hash": cfg_hash, "ms": int((time.perf_counter() - started) * 1000)})
        + "\n"
    )
    if best:
        sys.stdout.write(best)


@app.command("vector_search")
def vector_search_cmd(
    model_id: str = typer.Option(..., "--model_id"),
    snapshot_id: int = typer.Option(..., "--snapshot_id"),
    query_text: str = typer.Option(..., "--query_text"),
    top_k: int = typer.Option(10, "--top_k"),
    max_dist: float | None = typer.Option(None, "--max_dist"),
):
    sql_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "retrieval", "sql", "vector_search.sql"))
    if not os.path.exists(sql_path):
        sql_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "retrieval", "sql", "vector_search.sql"))
    try:
        with open(sql_path, "r", encoding="utf-8") as f:
            raw_sql = f.read()
    except Exception:
        fail(error="vector_search_sql_not_found", code="config_error")

    query_sql = raw_sql.replace(":query_vector", "%(query_vector)s").replace(":snapshot_id", "%(snapshot_id)s").replace(":top_k", "%(top_k)s").replace(":max_dist", "%(max_dist)s")

    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT model_id, provider_type, dimension, config_jsonb FROM embedding_models WHERE model_id = %s;", (model_id,))
            row = cur.fetchone()
        if not row:
            fail(error="model_not_found", code="not_found")

        provider = provider_from_model_row(
            model_id=str(row["model_id"]),
            provider_type=str(row["provider_type"]),
            dimension=int(row["dimension"]),
            config=dict(row["config_jsonb"] or {}),
        )
        vec = provider.embed([query_text])[0]
        vec_lit = "[" + ",".join(str(float(x)) for x in vec) + "]"

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                query_sql,
                {"query_vector": vec_lit, "snapshot_id": snapshot_id, "top_k": top_k, "max_dist": max_dist},
            )
            hits = cur.fetchall()

    out = [{"chunk_id": h["chunk_id"], "dist": float(h["dist"])} for h in hits]
    sys.stdout.write(json.dumps(out, default=str) + "\n")


def main():
    app()


if __name__ == "__main__":
    main()
