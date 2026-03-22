import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from metrics.export import export_metrics
from patch.apply import apply_patch
from runner.cmd import run_cmd

from .llm_provider import LLMProvider, provider_from_env


@dataclass(frozen=True)
class ConvergenceConfig:
    max_iters: int
    no_progress_limit: int


@dataclass(frozen=True)
class IterationResult:
    iteration: int
    diff: str
    apply_ok: bool
    apply_status: str
    apply_error: str | None
    metrics: dict[str, Any]
    score: tuple
    runner_exit_code: int | None
    runner_stdout: str | None
    runner_stderr: str | None


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-untyped]

    obj = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    return dict(obj) if isinstance(obj, dict) else {}


def load_config(*, path: Path, overrides: dict[str, Any] | None = None) -> tuple[ConvergenceConfig, str]:
    raw = _load_yaml(path) if path.exists() else {}
    if overrides:
        raw.update({k: v for k, v in overrides.items() if v is not None})
    max_iters = int(raw.get("max_iters") or 20)
    no_progress_limit = int(raw.get("no_progress_limit") or 5)
    if max_iters < 1:
        max_iters = 1
    if no_progress_limit < 1:
        no_progress_limit = 1
    config_hash = _sha256_text(json.dumps({"max_iters": max_iters, "no_progress_limit": no_progress_limit}, sort_keys=True))
    return ConvergenceConfig(max_iters=max_iters, no_progress_limit=no_progress_limit), config_hash


_RE_UNSAFE_BLOCK = re.compile(r"\bunsafe\s*\{")
_RE_RAW_PTR = re.compile(r"(\*const\b|\*mut\b|\bas\s+\*const\b|\bas\s+\*mut\b)")


def compute_rust_metrics_in_dir(root: Path) -> dict[str, Any]:
    unsafe_blocks = 0
    unsafe_lines = 0
    total_lines = 0
    raw_ptr_count = 0

    for p in sorted(root.rglob("*.rs"), key=lambda x: x.as_posix().lower()):
        txt = p.read_text(encoding="utf-8", errors="replace")
        unsafe_blocks += len(_RE_UNSAFE_BLOCK.findall(txt))
        raw_ptr_count += len(_RE_RAW_PTR.findall(txt))

        lines = txt.splitlines()
        total_lines += len(lines)
        for line in lines:
            if "unsafe" in line:
                unsafe_lines += 1

    unsafe_line_pct = (unsafe_lines / total_lines * 100.0) if total_lines else 0.0
    return {
        "unsafe_blocks": int(unsafe_blocks),
        "unsafe_line_pct": float(unsafe_line_pct),
        "raw_ptr_count": int(raw_ptr_count),
    }


def _score(metrics: dict[str, Any]) -> tuple:
    return (
        int(metrics.get("unsafe_blocks") or 0),
        float(metrics.get("unsafe_line_pct") or 0.0),
        int(metrics.get("raw_ptr_count") or 0),
        -float(metrics.get("test_pass_rate") or 0.0),
    )


def _score_failed() -> tuple:
    return (10**9, 10**9, 10**9, 0.0)


def _parse_test_pass_rate(stdout: str, stderr: str, exit_code: int) -> tuple[int, int]:
    out = (stdout or "") + "\n" + (stderr or "")
    m = re.search(r"test result:\s*(ok|FAILED)\.\s*(\d+)\s+passed;\s+(\d+)\s+failed;", out, flags=re.IGNORECASE)
    if m:
        passed = int(m.group(2))
        failed = int(m.group(3))
        return passed, passed + failed

    m = re.search(r"running\s+(\d+)\s+tests", out, flags=re.IGNORECASE)
    if m:
        total = int(m.group(1))
        if exit_code == 0:
            return total, total
        return 0, total

    if exit_code == 0:
        return 1, 1
    return 0, 1


def _write_event(log_path: Path, event: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _validate_diff_only_hunks(diff: str) -> bool:
    s = (diff or "").strip("\r\n")
    if not s:
        return True
    if "@@ " not in s:
        return False
    for line in s.splitlines():
        if not line:
            continue
        if line.startswith(("--- ", "+++ ", "@@ ", "+", "-", " ")):
            continue
        return False
    return True


def run_converge(
    *,
    base_dir: Path,
    evidence: str,
    target_function: str,
    prompt_template_path: Path,
    config: ConvergenceConfig,
    config_hash: str,
    out_dir: Path,
    validate_cmd: list[str] | None = None,
    provider: LLMProvider | None = None,
    now_utc: Callable[[], str] | None = None,
) -> tuple[str, list[IterationResult]]:
    base_dir = base_dir.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    provider = provider or provider_from_env()
    validate_cmd = [str(x) for x in validate_cmd] if validate_cmd is not None else None
    now_utc = now_utc or (lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    tmpl = prompt_template_path.read_text(encoding="utf-8", errors="replace")
    rendered = tmpl.replace("{evidence}", evidence).replace("{target_function}", target_function)

    baseline_files: dict[Path, str] = {}
    for p in sorted(base_dir.rglob("*.rs"), key=lambda x: x.as_posix().lower()):
        baseline_files[p] = p.read_text(encoding="utf-8", errors="replace")

    best_diff = ""
    best_score: tuple | None = None
    no_progress = 0
    history: list[IterationResult] = []

    converge_log = out_dir / "converge.jsonl"

    for i in range(1, config.max_iters + 1):
        out = provider.generate(rendered).strip()
        diff = out + "\n" if out else ""
        if not _validate_diff_only_hunks(diff):
            diff = ""

        apply_ok = True
        apply_status = "skipped"
        apply_error = None
        if diff:
            r_apply = apply_patch(base_dir, diff)
            apply_ok = bool(r_apply.ok)
            apply_status = str(r_apply.status)
            apply_error = r_apply.error_msg

        code_metrics = compute_rust_metrics_in_dir(base_dir)

        runner_exit_code = None
        runner_stdout = None
        runner_stderr = None
        passed = 0
        total = 0
        if validate_cmd:
            r = run_cmd(cmd=validate_cmd, cwd=str(base_dir), env={}, timeout=int(os.getenv("PATCH_VALIDATE_TIMEOUT", "300")), capture=True)
            runner_exit_code = int(r.exit_code)
            runner_stdout = r.stdout
            runner_stderr = r.stderr
            passed, total = _parse_test_pass_rate(r.stdout, r.stderr, r.exit_code)
        test_pass_rate = (passed / total * 100.0) if total else 0.0
        code_metrics["test_pass_rate"] = float(test_pass_rate)

        sc = _score(code_metrics) if apply_ok else _score_failed()
        export_metrics(i, {**code_metrics, "meta": {"timestamp_utc": now_utc(), "commit": "", "config_hash": config_hash}}, out_dir)
        history.append(
            IterationResult(
                iteration=i,
                diff=diff,
                apply_ok=apply_ok,
                apply_status=apply_status,
                apply_error=apply_error,
                metrics=code_metrics,
                score=sc,
                runner_exit_code=runner_exit_code,
                runner_stdout=runner_stdout,
                runner_stderr=runner_stderr,
            )
        )

        improved = best_score is None or sc < best_score
        if improved:
            best_score = sc
            best_diff = diff
            no_progress = 0
        else:
            no_progress += 1

        if no_progress >= config.no_progress_limit:
            _write_event(converge_log, {"event": "rollback", "iteration": i, "best_score": best_score, "no_progress": no_progress})
            for p, txt in baseline_files.items():
                p.write_text(txt, encoding="utf-8", newline="\n")
            if best_diff:
                apply_patch(base_dir, best_diff)
            no_progress = 0

    for p, txt in baseline_files.items():
        p.write_text(txt, encoding="utf-8", newline="\n")
    if best_diff:
        apply_patch(base_dir, best_diff)

    return best_diff, history
