import argparse
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class PilotSpec:
    name: str
    project: str
    commit: str
    workspace_dir: Path
    query_text: str
    baseline_env: dict
    enhanced_env: dict


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _api_dir() -> Path:
    return _repo_root() / "apps" / "api"


def _ensure_import_path() -> None:
    import sys

    p = str(_api_dir())
    if p not in sys.path:
        sys.path.insert(0, p)


def _dsn() -> str:
    return os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN") or ""


def _sha256_text(s: str) -> str:
    import hashlib

    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def _http_json(client: httpx.Client, method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    r = client.request(method, url, json=payload)
    try:
        return int(r.status_code), dict(r.json() or {})
    except Exception:
        return int(r.status_code), {"raw": r.text}


def _ensure_workspace_pilot0(path: Path) -> None:
    (path / "src").mkdir(parents=True, exist_ok=True)
    (path / "Cargo.toml").write_text(
        "\n".join(
            [
                "[package]",
                'name = "pilot0_demo"',
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
    (path / "src" / "lib.rs").write_text(
        "\n".join(
            [
                "pub fn demo() {",
                "    let x = 1;",
                "    let y = &x;",
                "    let _z = y;",
                "    let _a = x;",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )


def _ensure_workspace_pilot1(path: Path) -> None:
    (path / "src").mkdir(parents=True, exist_ok=True)
    (path / "Cargo.toml").write_text(
        "\n".join(
            [
                "[package]",
                'name = "pilot1_small"',
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
    (path / "src" / "lib.rs").write_text(
        "\n".join(
            [
                "mod utils;",
                "",
                "pub fn entry(buf: &mut [u8]) {",
                "    utils::copy_buf(buf);",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    (path / "src" / "utils.rs").write_text(
        "\n".join(
            [
                "pub fn copy_buf(buf: &mut [u8]) {",
                "    let n = buf.len();",
                "    if n > 0 {",
                "        buf[0] = 42;",
                "    }",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )


def _get_or_create_snapshot(conn: psycopg.Connection, *, project_name: str, commit_sha: str) -> int:
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


def _get_or_create_chunk(conn: psycopg.Connection, *, snapshot_id: int, kind: str, lang: str, content: str, meta: dict) -> int:
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


def _prepare_snapshot_and_embeddings(*, spec: PilotSpec) -> int:
    dsn = _dsn()
    if not dsn:
        raise SystemExit("DATABASE_URL_not_set")

    _ensure_import_path()
    from embed.service import Chunk, batch_embed_and_upsert, ensure_embedding_model  # noqa: PLC0415

    spec.workspace_dir.mkdir(parents=True, exist_ok=True)
    if spec.name == "pilot-0":
        _ensure_workspace_pilot0(spec.workspace_dir)
    else:
        _ensure_workspace_pilot1(spec.workspace_dir)

    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.transaction():
            snapshot_id = _get_or_create_snapshot(conn, project_name=spec.project, commit_sha=spec.commit)

            if spec.name == "pilot-0":
                rel_file = "src/lib.rs"
                content = (spec.workspace_dir / rel_file).read_text(encoding="utf-8", errors="replace")
                code_meta = {
                    "file": rel_file,
                    "evidence_type": "code_slice",
                    "risk_tags": ["unsafe", "raw_ptr"],
                    "constraint_tags": ["no_signature_change", "no_full_rewrite"],
                    "api_tags": ["clone", "mem::take"],
                    "symbol": "demo",
                    "signature": "pub fn demo()",
                    "calls": [],
                }
                code_chunk_id = _get_or_create_chunk(
                    conn,
                    snapshot_id=snapshot_id,
                    kind="rust_function_slice",
                    lang="rust",
                    content=content + "\nE0502 cannot borrow x\n",
                    meta=code_meta,
                )
            else:
                rel_file = "src/utils.rs"
                content = (spec.workspace_dir / rel_file).read_text(encoding="utf-8", errors="replace")
                code_meta = {
                    "file": rel_file,
                    "evidence_type": "code_slice",
                    "risk_tags": ["memcpy_memmove", "manual_mem", "raw_ptr"],
                    "constraint_tags": ["no_signature_change", "no_full_rewrite"],
                    "api_tags": ["copy_from_slice", "Vec", "Box"],
                    "symbol": "copy_buf",
                    "signature": "pub fn copy_buf(buf: &mut [u8])",
                    "calls": [],
                }
                code_chunk_id = _get_or_create_chunk(
                    conn,
                    snapshot_id=snapshot_id,
                    kind="rust_function_slice",
                    lang="rust",
                    content=content + "\nmemcpy memmove malloc free raw pointer\n",
                    meta=code_meta,
                )

            strategy_chunk_ids: list[int] = []
            strategy_chunk_ids.append(
                _get_or_create_chunk(
                    conn,
                    snapshot_id=snapshot_id,
                    kind="replacement_strategy",
                    lang="text",
                    content="memcpy/memmove -> copy_from_slice / safe slice copy\n",
                    meta={
                        "file": "evidence/strategies/memcpy_memmove.txt",
                        "evidence_type": "replacement_strategy",
                        "applies_to_risk": ["memcpy_memmove", "raw_ptr"],
                        "api_tags": ["copy_from_slice", "clone_from_slice"],
                        "constraint_tags": ["preserve_behavior", "minimal_patch"],
                        "strategy_id": "memcpy_safe_slice_copy",
                        "strategy_title": "Replace memcpy/memmove with safe slice copy",
                    },
                )
            )
            strategy_chunk_ids.append(
                _get_or_create_chunk(
                    conn,
                    snapshot_id=snapshot_id,
                    kind="interface_constraint",
                    lang="text",
                    content="Do not change public function signatures; keep changes minimal.\n",
                    meta={
                        "file": "src/lib.rs",
                        "evidence_type": "interface_constraint",
                        "constraint_tags": ["no_signature_change", "no_full_rewrite"],
                        "strategy_title": "Keep public API stable",
                    },
                )
            )
            strategy_chunk_ids.append(
                _get_or_create_chunk(
                    conn,
                    snapshot_id=snapshot_id,
                    kind="behavior_constraint",
                    lang="text",
                    content="Preserve observable behavior; do not break tests.\n",
                    meta={
                        "file": "src/lib.rs",
                        "evidence_type": "behavior_constraint",
                        "constraint_tags": ["preserve_behavior", "do_not_break_tests"],
                        "strategy_title": "Preserve external behavior and tests",
                    },
                )
            )

    ensure_embedding_model(model_id="stub-1536", provider_type="stub", dimension=1536, config={"seed": 1337, "dimension": 1536})
    embed_inputs = [Chunk(chunk_id=int(code_chunk_id), content=spec.query_text)]
    for cid in strategy_chunk_ids:
        embed_inputs.append(Chunk(chunk_id=int(cid), content=spec.query_text))
    batch_embed_and_upsert(chunks=embed_inputs, model_id="stub-1536", snapshot_id=int(snapshot_id))
    return int(snapshot_id)


def _run_one(client: httpx.Client, *, api_base: str, payload: dict) -> str:
    code, resp = _http_json(client, "POST", f"{api_base}/agent/run", payload)
    if code != 201 or "run_id" not in resp:
        raise SystemExit(f"agent_run_failed:{resp}")
    return str(resp["run_id"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.getenv("DEMO_API_URL", "http://localhost:8000"))
    ap.add_argument("--out", default="experiments.csv")
    args = ap.parse_args()

    api_base = args.api.rstrip("/")

    pilots = [
        PilotSpec(
            name="pilot-0",
            project="pilot0_demo",
            commit="pilot0_v1",
            workspace_dir=(_repo_root() / "pilot0_workspace").resolve(),
            query_text="E0502 cannot borrow x",
            baseline_env={"RUNNER_MODE": "mock", "MOCK_SCENARIO": "compile_fail"},
            enhanced_env={"RUNNER_MODE": "mock", "MOCK_SCENARIO": "compile_fail"},
        ),
        PilotSpec(
            name="pilot-1",
            project="pilot1_small",
            commit="pilot1_v1",
            workspace_dir=(_repo_root() / "pilot1_workspace").resolve(),
            query_text="memcpy memmove malloc free raw pointer",
            baseline_env={"RUNNER_MODE": "mock", "MOCK_SCENARIO": "compile_fail"},
            enhanced_env={"RUNNER_MODE": "mock", "MOCK_SCENARIO": "success"},
        ),
    ]

    dsn = _dsn()
    if not dsn:
        raise SystemExit("DATABASE_URL_not_set")

    for p in pilots:
        _prepare_snapshot_and_embeddings(spec=p)

    with httpx.Client(timeout=20, trust_env=False) as client:
        code, health = _http_json(client, "GET", f"{api_base}/health")
        if code != 200 or not health.get("ok"):
            raise SystemExit("api_not_ready")

        run_ids: list[str] = []
        for p in pilots:
            with psycopg.connect(dsn, connect_timeout=5) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        """
                        SELECT s.snapshot_id
                        FROM repo_snapshots s
                        JOIN projects pr ON pr.project_id = s.project_id
                        WHERE pr.name = %s AND s.commit_sha = %s
                        LIMIT 1;
                        """,
                        (p.project, p.commit),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise SystemExit(f"snapshot_missing:{p.project}:{p.commit}")
                    snapshot_id = int(row["snapshot_id"])

            baseline_payload = {
                "snapshot_id": snapshot_id,
                "workspace_path": str(p.workspace_dir),
                "task_description": f"{p.query_text} (baseline)",
                "mode": "baseline",
                "cmd": ["cargo", "test"],
                "timeout": 3,
                "env": p.baseline_env,
            }
            rid_base = _run_one(client, api_base=api_base, payload=baseline_payload)
            run_ids.append(rid_base)

            enhanced_payload = {
                "snapshot_id": snapshot_id,
                "workspace_path": str(p.workspace_dir),
                "task_description": p.query_text,
                "mode": "enhanced",
                "max_iters": 2,
                "no_progress_limit": 1,
                "filters": {"kind": ["rust_function_slice", "replacement_strategy", "interface_constraint", "behavior_constraint"]},
                "top_k": 10,
                "retrieval_model_id": "stub-1536",
                "patch_backend": "template_edit",
                "cmd": ["cargo", "test"],
                "timeout": 3,
                "env": p.enhanced_env,
            }
            rid_enh = _run_one(client, api_base=api_base, payload=enhanced_payload)
            run_ids.append(rid_enh)

        time.sleep(0.2)

    cmd = [
        "python",
        str((_repo_root() / "scripts" / "export_experiments_csv.py").resolve()),
        "--out",
        str(Path(args.out).resolve()),
    ]
    for rid in run_ids:
        cmd.extend(["--run-id", rid])

    import subprocess

    subprocess.run(cmd, check=True)
    print(json.dumps({"csv": str(Path(args.out).resolve()), "run_ids": run_ids}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
