import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import httpx
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _api_dir() -> Path:
    return _repo_root() / "apps" / "api"


def _ensure_import_path() -> None:
    p = str(_api_dir())
    if p not in sys.path:
        sys.path.insert(0, p)


def _ensure_demo_workspace(workspace_dir: Path) -> None:
    (workspace_dir / "src").mkdir(parents=True, exist_ok=True)

    (workspace_dir / "Cargo.toml").write_text(
        "\n".join(
            [
                "[package]",
                'name = "demo_workspace"',
                'version = "0.1.0"',
                'edition = "2021"',
                "",
                "[lib]",
                'path = "src/lib.rs"',
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = [
        "pub fn demo() {",
        "    let x = 1;",
        "    let y = &x;",
        "    let _z = y;",
        "    let _a = x;",
        "    let _b = 2;",
        "    let _c = 3;",
        "    let _d = 4;",
        "    let _e = 5;",
        "    let _f = 6;",
        "    let _g = 7;",
        "}",
        "",
    ]
    (workspace_dir / "src" / "lib.rs").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def _get_or_create_demo_snapshot(conn: psycopg.Connection, *, project_name: str, commit_sha: str) -> int:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT project_id FROM projects WHERE name = %s;", (project_name,))
        row = cur.fetchone()
        if row:
            project_id = int(row["project_id"])
        else:
            cur.execute("INSERT INTO projects (name) VALUES (%s) RETURNING project_id;", (project_name,))
            project_id = int(cur.fetchone()["project_id"])

        cur.execute("SELECT snapshot_id FROM repo_snapshots WHERE project_id = %s AND commit_sha = %s;", (project_id, commit_sha))
        row = cur.fetchone()
        if row:
            return int(row["snapshot_id"])

        cur.execute("INSERT INTO repo_snapshots (project_id, commit_sha) VALUES (%s, %s) RETURNING snapshot_id;", (project_id, commit_sha))
        return int(cur.fetchone()["snapshot_id"])


def _get_or_create_demo_chunk(conn: psycopg.Connection, *, snapshot_id: int, rel_file: str, content: str) -> int:
    h = _sha256_text(content)
    meta = {
        "file": rel_file,
        "evidence_type": "code_slice",
        "risk_tags": ["unsafe", "raw_ptr", "manual_mem", "memcpy_memmove"],
        "constraint_tags": ["no_signature_change", "no_full_rewrite"],
        "api_tags": ["malloc", "free", "memcpy", "memmove", "Vec", "Box"],
        "symbol": "demo",
        "signature": "pub fn demo()",
        "calls": [],
    }
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT chunk_id
            FROM code_chunks
            WHERE snapshot_id = %s AND kind = %s AND lang = %s AND content_hash = %s;
            """,
            (snapshot_id, "rust_function_slice", "rust", h),
        )
        row = cur.fetchone()
        if row:
            chunk_id = int(row["chunk_id"])
            cur.execute("UPDATE code_chunks SET meta = %s WHERE chunk_id = %s;", (Jsonb(meta), chunk_id))
            return chunk_id

        cur.execute(
            """
            INSERT INTO code_chunks (snapshot_id, kind, lang, content, content_tsv, meta, content_hash)
            VALUES (%s, %s, %s, %s, to_tsvector('simple', %s), %s, %s)
            RETURNING chunk_id;
            """,
            (snapshot_id, "rust_function_slice", "rust", content, content, Jsonb(meta), h),
        )
        return int(cur.fetchone()["chunk_id"])


def _get_or_create_evidence_chunk(
    conn: psycopg.Connection,
    *,
    snapshot_id: int,
    kind: str,
    lang: str,
    content: str,
    meta: dict,
) -> int:
    h = _sha256_text(content)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT chunk_id
            FROM code_chunks
            WHERE snapshot_id = %s AND kind = %s AND lang = %s AND content_hash = %s;
            """,
            (snapshot_id, kind, lang, h),
        )
        row = cur.fetchone()
        if row:
            chunk_id = int(row["chunk_id"])
            cur.execute("UPDATE code_chunks SET meta = %s WHERE chunk_id = %s;", (Jsonb(meta), chunk_id))
            return chunk_id
        cur.execute(
            """
            INSERT INTO code_chunks (snapshot_id, kind, lang, content, content_tsv, meta, content_hash)
            VALUES (%s, %s, %s, %s, to_tsvector('simple', %s), %s, %s)
            RETURNING chunk_id;
            """,
            (snapshot_id, kind, lang, content, content, Jsonb(meta), h),
        )
        return int(cur.fetchone()["chunk_id"])


def _http_json(client: httpx.Client, method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    r = client.request(method, url, json=payload)
    try:
        return int(r.status_code), dict(r.json() or {})
    except Exception:
        return int(r.status_code), {"raw": r.text}


def _print_summary(run: dict) -> None:
    summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
    metrics = run.get("metrics") if isinstance(run.get("metrics"), dict) else {}
    patches = run.get("patches") if isinstance(run.get("patches"), list) else []

    patch = patches[0] if patches else {}
    diff = str(patch.get("unified_diff") or "")
    diff_lines = diff.splitlines()
    diff_preview = "\n".join(diff_lines[:12]) + ("\n..." if len(diff_lines) > 12 else "")

    out = {
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "final_status": summary.get("final_status"),
        "target_file": summary.get("target_file"),
        "evidence_count": summary.get("evidence_count"),
        "evidence_top": summary.get("evidence_top"),
        "risk_overview": summary.get("risk_overview"),
        "strategy_evidence_top": summary.get("strategy_evidence_top"),
        "patch_status": summary.get("patch_status"),
        "execute_exit_code": summary.get("execute_exit_code"),
        "diagnose_issue_count": summary.get("diagnose_issue_count"),
        "metrics": metrics,
        "patch_preview": diff_preview,
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.getenv("DEMO_API_URL", "http://localhost:8000"))
    ap.add_argument("--project", default="demo")
    ap.add_argument("--commit", default="demo-v1")
    ap.add_argument("--workspace", default="")
    args = ap.parse_args()

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        raise SystemExit("DATABASE_URL_not_set")

    ws = Path(args.workspace).resolve() if args.workspace else (_repo_root() / "demo_workspace").resolve()
    _ensure_demo_workspace(ws)

    _ensure_import_path()
    from embed.service import Chunk, batch_embed_and_upsert, ensure_embedding_model  # noqa: PLC0415

    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.transaction():
            snapshot_id = _get_or_create_demo_snapshot(conn, project_name=str(args.project), commit_sha=str(args.commit))
            rel_file = "src/lib.rs"
            content = (ws / rel_file).read_text(encoding="utf-8", errors="replace")
            chunk_id = _get_or_create_demo_chunk(conn, snapshot_id=snapshot_id, rel_file=rel_file, content=content + "\nE0502 cannot borrow `x` as mutable because it is also borrowed as immutable\n")
            evidence_chunk_ids: list[int] = []
            evidence_chunk_ids.append(
                _get_or_create_evidence_chunk(
                conn,
                snapshot_id=snapshot_id,
                kind="rust_rule_snippet",
                lang="text",
                content="\n".join(
                    [
                        "Rule (Rust borrow checker):",
                        "If you see E0502 (cannot borrow as mutable because it is also borrowed as immutable), reduce the immutable borrow scope, or clone the needed value, or restructure code to avoid overlapping borrows.",
                        "Constraints: do not change function signatures; keep changes minimal; output unified diff.",
                    ]
                )
                + "\n",
                meta={
                    "file": "evidence/rules/borrow_checker.txt",
                    "evidence_type": "rust_rule_snippet",
                    "constraint_tags": ["no_signature_change", "no_full_rewrite"],
                    "api_tags": ["clone", "mem::take"],
                    "applies_to_risk": ["unsafe", "raw_ptr"],
                    "strategy_title": "Borrow checker E0502: shrink borrow scope / clone / refactor borrows",
                },
                )
            )
            evidence_chunk_ids.append(
                _get_or_create_evidence_chunk(
                conn,
                snapshot_id=snapshot_id,
                kind="interface_constraint",
                lang="text",
                content="\n".join(
                    [
                        "Interface constraint:",
                        "Do NOT change public function signatures in src/lib.rs (e.g., pub fn demo()).",
                        "Only apply a minimal patch around the relevant lines.",
                    ]
                )
                + "\n",
                meta={
                    "file": "src/lib.rs",
                    "evidence_type": "interface_constraint",
                    "constraint_tags": ["no_signature_change", "no_full_rewrite"],
                    "applies_to_risk": ["unsafe", "raw_ptr", "manual_mem", "memcpy_memmove"],
                    "strategy_title": "Keep public API stable",
                },
                )
            )
            evidence_chunk_ids.append(
                _get_or_create_evidence_chunk(
                    conn,
                    snapshot_id=snapshot_id,
                    kind="behavior_constraint",
                    lang="text",
                    content="\n".join(
                        [
                            "Behavior constraint:",
                            "Preserve observable input-output behavior.",
                            "Do not break existing tests; avoid broad refactors that change semantics.",
                        ]
                    )
                    + "\n",
                    meta={
                        "file": "src/lib.rs",
                        "evidence_type": "behavior_constraint",
                        "constraint_tags": ["preserve_behavior", "no_full_rewrite", "do_not_break_tests"],
                        "strategy_title": "Preserve external behavior and tests",
                    },
                )
            )
            evidence_chunk_ids.append(
                _get_or_create_evidence_chunk(
                    conn,
                    snapshot_id=snapshot_id,
                    kind="replacement_strategy",
                    lang="text",
                    content="\n".join(
                        [
                            "Replacement strategy: confine unsafe to a narrow boundary wrapper.",
                            "Keep unsafe inside a small helper function; expose a safe API outside.",
                            "Applies to: raw pointers, pointer arithmetic.",
                        ]
                    )
                    + "\n",
                    meta={
                        "file": "evidence/strategies/unsafe_boundary.txt",
                        "evidence_type": "replacement_strategy",
                        "applies_to_risk": ["unsafe", "raw_ptr", "ptr_arith"],
                        "constraint_tags": ["no_signature_change", "minimal_patch"],
                        "api_tags": ["unsafe", "wrapper"],
                        "strategy_id": "unsafe_boundary_wrapper",
                        "strategy_title": "Confine unsafe to a narrow boundary",
                    },
                )
            )
            evidence_chunk_ids.append(
                _get_or_create_evidence_chunk(
                    conn,
                    snapshot_id=snapshot_id,
                    kind="replacement_strategy",
                    lang="text",
                    content="\n".join(
                        [
                            "Replacement strategy: malloc/free -> Vec or Box.",
                            "Prefer Vec<T> for buffers, Box<T> for single heap values.",
                            "Applies to: manual memory management (malloc/free).",
                        ]
                    )
                    + "\n",
                    meta={
                        "file": "evidence/strategies/malloc_free.txt",
                        "evidence_type": "replacement_strategy",
                        "applies_to_risk": ["manual_mem"],
                        "constraint_tags": ["preserve_behavior", "minimal_patch"],
                        "api_tags": ["Vec", "Box", "alloc"],
                        "strategy_id": "malloc_free_vec_box",
                        "strategy_title": "Replace malloc/free with Vec/Box",
                    },
                )
            )
            evidence_chunk_ids.append(
                _get_or_create_evidence_chunk(
                    conn,
                    snapshot_id=snapshot_id,
                    kind="replacement_strategy",
                    lang="text",
                    content="\n".join(
                        [
                            "Replacement strategy: memcpy/memmove -> safe slice copy.",
                            "Use copy_from_slice / clone_from_slice when sizes match; avoid raw pointer copies.",
                            "Applies to: memcpy/memmove hotspots.",
                        ]
                    )
                    + "\n",
                    meta={
                        "file": "evidence/strategies/memcpy_memmove.txt",
                        "evidence_type": "replacement_strategy",
                        "applies_to_risk": ["memcpy_memmove", "raw_ptr"],
                        "constraint_tags": ["preserve_behavior", "minimal_patch"],
                        "api_tags": ["copy_from_slice", "clone_from_slice"],
                        "strategy_id": "memcpy_safe_slice_copy",
                        "strategy_title": "Replace memcpy/memmove with safe slice copy",
                    },
                )
            )
            evidence_chunk_ids.append(
                _get_or_create_evidence_chunk(
                    conn,
                    snapshot_id=snapshot_id,
                    kind="c_build_info",
                    lang="text",
                    content="\n".join(
                        [
                            "C-side build info (lightweight evidence):",
                            "Original source language: C (C99).",
                            "Build hint: make && make test (example).",
                            "This is a minimal placeholder to show C-side evidence is stored in the evidence base.",
                        ]
                    )
                    + "\n",
                    meta={
                        "file": "evidence/c/build_info.txt",
                        "evidence_type": "c_build_info",
                        "source_lang": "c",
                        "constraint_tags": ["preserve_behavior"],
                        "strategy_title": "C-side build info (minimal)",
                    },
                )
            )

    ensure_embedding_model(model_id="stub-1536", provider_type="stub", dimension=1536, config={"seed": 1337, "dimension": 1536})
    embed_inputs = [Chunk(chunk_id=int(chunk_id), content="E0502 cannot borrow x")]
    for cid in evidence_chunk_ids:
        embed_inputs.append(Chunk(chunk_id=int(cid), content="E0502 cannot borrow x strategy constraint evidence"))
    batch_embed_and_upsert(chunks=embed_inputs, model_id="stub-1536", snapshot_id=int(snapshot_id))

    with httpx.Client(timeout=10, trust_env=False) as client:
        code, health = _http_json(client, "GET", f"{args.api.rstrip('/')}/health")
        if code != 200 or not health.get("ok"):
            raise SystemExit("api_not_ready")

        retrieve_payload = {
            "snapshot_id": int(snapshot_id),
            "query_text": "E0502 cannot borrow x",
            "filters": {
                "kind": [
                    "rust_function_slice",
                    "rust_rule_snippet",
                    "interface_constraint",
                    "behavior_constraint",
                    "replacement_strategy",
                    "c_build_info",
                ]
            },
            "top_k": 10,
        }
        code, pack = _http_json(client, "POST", f"{args.api.rstrip('/')}/retrieve", retrieve_payload)
        if code != 200 or not (pack.get("items") or []):
            raise SystemExit("retrieve_failed_or_empty")

        run_payload = {
            "snapshot_id": int(snapshot_id),
            "workspace_path": str(ws),
            "task_description": "E0502 cannot borrow x",
            "filters": {
                "kind": [
                    "rust_function_slice",
                    "rust_rule_snippet",
                    "interface_constraint",
                    "behavior_constraint",
                    "replacement_strategy",
                    "c_build_info",
                ]
            },
            "top_k": 10,
            "retrieval_model_id": "stub-1536",
            "patch_backend": "template_edit",
            "env": {"RUNNER_MODE": "mock", "MOCK_SCENARIO": "compile_fail"},
            "cmd": ["cargo", "test"],
            "timeout": 3,
        }
        code, run_resp = _http_json(client, "POST", f"{args.api.rstrip('/')}/agent/run", run_payload)
        if code != 201 or "run_id" not in run_resp:
            raise SystemExit(f"agent_run_failed:{run_resp}")

        run_id = str(run_resp["run_id"])
        time.sleep(0.1)
        code, run = _http_json(client, "GET", f"{args.api.rstrip('/')}/runs/{run_id}")
        if code != 200:
            raise SystemExit("run_fetch_failed")
        _print_summary(run)


if __name__ == "__main__":
    main()
