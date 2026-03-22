import gzip
import json
import os
import random
import signal
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .cargo import run_cargo
from .types import RunCmdResult


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _log_dir() -> Path:
    override = os.getenv("RUNNER_LOG_DIR", "").strip()
    if override:
        p = Path(override)
    else:
        root = Path(__file__).resolve().parents[3]
        p = root / "logs" / "runner"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _cleanup_logs(dir_path: Path, *, keep_days: int = 7) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    for p in dir_path.glob("*.log.gz"):
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
            if mtime < cutoff:
                p.unlink(missing_ok=True)
        except Exception:
            continue


def _abs_str(p: Path) -> str:
    ap = p.resolve()
    s = str(ap)
    if os.name == "nt" and not s.startswith("\\\\?\\") and len(s) >= 240:
        return "\\\\?\\" + s
    return s


def _maybe_spill(stdout: str, stderr: str) -> tuple[str, str, str]:
    threshold = 10 * 1024
    if len(stdout.encode("utf-8")) < threshold and len(stderr.encode("utf-8")) < threshold:
        return stdout, stderr, ""

    log_dir = _log_dir()
    _cleanup_logs(log_dir)
    name = f"{_now_ts()}_{uuid.uuid4().hex}.log.gz"
    path = log_dir / name
    payload = {"stdout": stdout, "stderr": stderr}
    raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    with gzip.open(path, "wb") as f:
        f.write(raw)
    return "", "", _abs_str(path)


def _mock_fixture_path(scenario: str) -> Path:
    override = os.getenv("MOCK_FIXTURES_DIR", "").strip()
    if override:
        return Path(override) / f"mock_{scenario}.json"
    root = Path(__file__).resolve().parents[1]
    return root / "tests" / "fixtures" / f"mock_{scenario}.json"


def _run_mock(*, timeout: int, capture: bool, scenario: str | None = None) -> RunCmdResult:
    if scenario is None:
        scenario = os.getenv("MOCK_SCENARIO", "success")
    scenario = str(scenario).strip() or "success"
    fixture = _mock_fixture_path(scenario)
    data: dict[str, Any] = {"exit_code": 0, "stdout": "", "stderr": ""}
    if fixture.exists():
        data = json.loads(fixture.read_text(encoding="utf-8"))

    delay_max_ms = int(os.getenv("MOCK_DELAY_MAX_MS", "10"))
    delay_ms = random.randint(0, max(delay_max_ms, 0))

    t0 = time.perf_counter()
    if scenario == "timeout":
        time.sleep(min(max(timeout, 1) + 0.05, 2.0))
        stdout, stderr, log_path = _maybe_spill("", f"timeout after {timeout}s")
        return RunCmdResult(exit_code=124, stdout=stdout, stderr=stderr, duration_ms=int((time.perf_counter() - t0) * 1000), log_path=log_path)

    if delay_ms:
        time.sleep(delay_ms / 1000.0)

    stdout_raw = str(data.get("stdout", ""))
    stderr_raw = str(data.get("stderr", ""))
    if not capture:
        stdout_raw = ""
        stderr_raw = ""
    stdout, stderr, log_path = _maybe_spill(stdout_raw, stderr_raw)
    return RunCmdResult(
        exit_code=int(data.get("exit_code", 0)),
        stdout=stdout,
        stderr=stderr,
        duration_ms=int((time.perf_counter() - t0) * 1000),
        log_path=log_path,
    )


def _kill_process(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            try:
                subprocess.run(  # noqa: S603
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                proc.kill()
        else:
            try:
                killpg = getattr(os, "killpg", None)
                sig = getattr(signal, "SIGKILL", signal.SIGTERM)
                if killpg is not None:
                    killpg(proc.pid, sig)
                else:
                    proc.kill()
            except Exception:
                proc.kill()
    except Exception:
        pass


def _run_real(
    *,
    cmd: list[str],
    cwd: str,
    env: dict[str, str],
    timeout: int,
    capture: bool,
) -> RunCmdResult:
    t0 = time.perf_counter()
    proc_env = os.environ.copy()
    proc_env.update(env or {})

    popen_kwargs: dict[str, Any] = {"cwd": cwd, "env": proc_env}
    if capture:
        popen_kwargs["stdout"] = subprocess.PIPE
        popen_kwargs["stderr"] = subprocess.PIPE

    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **popen_kwargs)  # noqa: S603
    try:
        if capture:
            out_b, err_b = proc.communicate(timeout=timeout)
            stdout = out_b.decode("utf-8", errors="replace")
            stderr = err_b.decode("utf-8", errors="replace")
        else:
            proc.wait(timeout=timeout)
            stdout = ""
            stderr = ""
        exit_code = int(proc.returncode or 0)
        stdout, stderr, log_path = _maybe_spill(stdout, stderr)
        return RunCmdResult(exit_code=exit_code, stdout=stdout, stderr=stderr, duration_ms=int((time.perf_counter() - t0) * 1000), log_path=log_path)
    except subprocess.TimeoutExpired:
        _kill_process(proc)
        try:
            proc.wait(timeout=1)
        except Exception:
            pass
        stdout, stderr, log_path = _maybe_spill("", f"timeout after {timeout}s")
        return RunCmdResult(exit_code=124, stdout=stdout, stderr=stderr, duration_ms=int((time.perf_counter() - t0) * 1000), log_path=log_path)


def run_cmd(
    *,
    cmd: list[str],
    cwd: str,
    env: dict[str, str],
    timeout: int,
    capture: bool = True,
) -> RunCmdResult:
    mode = str((env or {}).get("RUNNER_MODE") or os.getenv("RUNNER_MODE", "mock")).lower()
    if mode == "mock":
        scenario = str((env or {}).get("MOCK_SCENARIO") or os.getenv("MOCK_SCENARIO", "success"))
        return _run_mock(timeout=timeout, capture=capture, scenario=scenario)

    if cmd and cmd[0] == "cargo":
        return run_cargo(cmd=cmd, cwd=cwd, env=env, timeout=timeout, capture=capture)

    return _run_real(cmd=cmd, cwd=cwd, env=env, timeout=timeout, capture=capture)
