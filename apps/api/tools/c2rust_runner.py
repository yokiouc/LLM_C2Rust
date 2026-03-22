import gzip
import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from runner.cmd import run_cmd


@dataclass(frozen=True)
class RustTranspileResult:
    c_project_path: str
    rust_workspace_dir: str
    snapshot_version: str
    c2rust_version: str | None
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    log_path: str
    manifest_path: str


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _abs_str(p: Path) -> str:
    ap = p.resolve()
    s = str(ap)
    if os.name == "nt" and not s.startswith("\\\\?\\") and len(s) >= 240:
        return "\\\\?\\" + s
    return s


def _cleanup_logs(dir_path: Path, *, keep_days: int = 7) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    for p in dir_path.glob("*.json.gz"):
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
            if mtime < cutoff:
                p.unlink(missing_ok=True)
        except Exception:
            continue


def _log_dir() -> Path:
    override = os.getenv("C2RUST_LOG_DIR", "").strip()
    if override:
        p = Path(override)
    else:
        root = Path(__file__).resolve().parents[3]
        p = root / "logs" / "c2rust"
    p.mkdir(parents=True, exist_ok=True)
    _cleanup_logs(p)
    return p


def _read_tool_config() -> dict[str, Any]:
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


def _dir_content_hash(dir_path: Path) -> str:
    root = dir_path.resolve()
    h = hashlib.sha256()
    for p in sorted(root.rglob("*"), key=lambda x: str(x).lower()):
        if p.is_dir():
            continue
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".git/"):
            continue
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        try:
            h.update(p.read_bytes())
        except Exception:
            h.update(b"<unreadable>")
        h.update(b"\x00")
    return h.hexdigest()


def _git_commit_sha(repo_dir: Path) -> str | None:
    if not (repo_dir / ".git").exists():
        return None
    if shutil.which("git") is None:
        return None
    mode_prev = os.getenv("RUNNER_MODE")
    os.environ["RUNNER_MODE"] = os.getenv("C2RUST_RUNNER_MODE", "real")
    try:
        r = run_cmd(cmd=["git", "rev-parse", "HEAD"], cwd=str(repo_dir), env={}, timeout=30, capture=True)
    finally:
        if mode_prev is None:
            os.environ.pop("RUNNER_MODE", None)
        else:
            os.environ["RUNNER_MODE"] = mode_prev
    if r.exit_code != 0:
        return None
    sha = (r.stdout or "").strip()
    return sha or None


def _detect_c2rust_version(c2rust_bin: str) -> str | None:
    mode_prev = os.getenv("RUNNER_MODE")
    os.environ["RUNNER_MODE"] = os.getenv("C2RUST_RUNNER_MODE", "real")
    try:
        r = run_cmd(cmd=[c2rust_bin, "--version"], cwd=".", env={}, timeout=30, capture=True)
    finally:
        if mode_prev is None:
            os.environ.pop("RUNNER_MODE", None)
        else:
            os.environ["RUNNER_MODE"] = mode_prev
    if r.exit_code != 0:
        return None
    s = (r.stdout or r.stderr or "").strip()
    return s or None


def _build_transpile_cmd(*, c2rust_bin: str, c_project_path: Path, rust_workspace_dir: Path, extra_args: list[str]) -> list[str]:
    return [c2rust_bin, "transpile", "--output-dir", str(rust_workspace_dir), str(c_project_path), *extra_args]


def run(*, c_project_path: Path, output_dir: Path) -> RustTranspileResult:
    started = time.perf_counter()

    cfg = _read_tool_config()
    c2rust_bin = str(cfg.get("c2rust_bin") or os.getenv("C2RUST_BIN") or "c2rust")
    extra_args = list(cfg.get("extra_args") or [])
    if not isinstance(extra_args, list):
        extra_args = []
    extra_args = [str(x) for x in extra_args]

    c_project_path = c_project_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    sha = _git_commit_sha(c_project_path)
    if sha:
        snapshot_version = sha
    else:
        snapshot_version = f"{_abs_str(c_project_path)}|sha256:{_dir_content_hash(c_project_path)}"

    c2rust_version = _detect_c2rust_version(c2rust_bin)
    cmd = _build_transpile_cmd(
        c2rust_bin=c2rust_bin, c_project_path=c_project_path, rust_workspace_dir=output_dir, extra_args=extra_args
    )

    env: dict[str, str] = {}
    timeout = int(cfg.get("timeout_seconds") or os.getenv("C2RUST_TIMEOUT_SECONDS") or 600)
    mode_prev = os.getenv("RUNNER_MODE")
    os.environ["RUNNER_MODE"] = os.getenv("C2RUST_RUNNER_MODE", "real")
    try:
        r = run_cmd(cmd=cmd, cwd=str(c_project_path), env=env, timeout=timeout, capture=True)
    finally:
        if mode_prev is None:
            os.environ.pop("RUNNER_MODE", None)
        else:
            os.environ["RUNNER_MODE"] = mode_prev
    duration_ms = int((time.perf_counter() - started) * 1000)

    stdout_full = r.stdout
    stderr_full = r.stderr
    if r.log_path:
        try:
            p = Path(r.log_path)
            with gzip.open(p, "rb") as f:
                obj = json.loads(f.read().decode("utf-8", errors="replace"))
            stdout_full = str(obj.get("stdout", stdout_full) or stdout_full)
            stderr_full = str(obj.get("stderr", stderr_full) or stderr_full)
        except Exception:
            stdout_full = r.stdout
            stderr_full = r.stderr

    log_dir = _log_dir()
    log_path = log_dir / f"{_now_ts()}_{uuid.uuid4().hex}.json.gz"
    payload = {
        "cmd": " ".join(cmd),
        "cmd_argv": cmd,
        "cwd": _abs_str(c_project_path),
        "exit_code": r.exit_code,
        "stdout": stdout_full,
        "stderr": stderr_full,
        "duration_ms": r.duration_ms,
        "runner_log_path": r.log_path,
        "snapshot_version": snapshot_version,
        "c2rust_version": c2rust_version,
        "rust_workspace_dir": _abs_str(output_dir),
    }
    with gzip.open(log_path, "wb") as f:
        f.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))

    manifest = {
        "snapshot_version": snapshot_version,
        "c2rust_version": c2rust_version,
        "c_project_path": _abs_str(c_project_path),
        "rust_workspace_dir": _abs_str(output_dir),
        "c2rust_log_path": _abs_str(log_path),
    }
    manifest_path = output_dir / ".c2rust_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return RustTranspileResult(
        c_project_path=_abs_str(c_project_path),
        rust_workspace_dir=_abs_str(output_dir),
        snapshot_version=snapshot_version,
        c2rust_version=c2rust_version,
        exit_code=r.exit_code,
        stdout=r.stdout,
        stderr=r.stderr,
        duration_ms=duration_ms,
        log_path=_abs_str(log_path),
        manifest_path=_abs_str(manifest_path),
    )
