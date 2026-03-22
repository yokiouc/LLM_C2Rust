import gzip
import json
from pathlib import Path

from runner.cmd import run_cmd


def test_mock_runner_success(monkeypatch):
    monkeypatch.setenv("RUNNER_MODE", "mock")
    monkeypatch.setenv("MOCK_SCENARIO", "success")
    r = run_cmd(cmd=["cargo", "test"], cwd=".", env={}, timeout=5, capture=True)
    assert r.exit_code == 0
    assert "ok" in r.stdout
    assert r.duration_ms >= 0


def test_mock_runner_compile_fail(monkeypatch):
    monkeypatch.setenv("RUNNER_MODE", "mock")
    monkeypatch.setenv("MOCK_SCENARIO", "compile_fail")
    r = run_cmd(cmd=["cargo", "check"], cwd=".", env={}, timeout=5, capture=True)
    assert r.exit_code != 0
    assert "src/lib.rs" in (r.stderr or r.stdout)


def test_mock_runner_test_fail(monkeypatch):
    monkeypatch.setenv("RUNNER_MODE", "mock")
    monkeypatch.setenv("MOCK_SCENARIO", "test_fail")
    r = run_cmd(cmd=["cargo", "test"], cwd=".", env={}, timeout=5, capture=True)
    assert r.exit_code != 0
    assert "test" in (r.stderr or r.stdout).lower()


def test_mock_runner_clippy_warn(monkeypatch):
    monkeypatch.setenv("RUNNER_MODE", "mock")
    monkeypatch.setenv("MOCK_SCENARIO", "clippy_warn")
    r = run_cmd(cmd=["cargo", "clippy"], cwd=".", env={}, timeout=5, capture=True)
    assert r.exit_code == 0
    assert "warning" in (r.stderr or r.stdout).lower()


def test_mock_runner_timeout(monkeypatch):
    monkeypatch.setenv("RUNNER_MODE", "mock")
    monkeypatch.setenv("MOCK_SCENARIO", "timeout")
    r = run_cmd(cmd=["cargo", "test"], cwd=".", env={}, timeout=1, capture=True)
    assert r.exit_code == 124


def test_mock_runner_spills_large_output(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RUNNER_MODE", "mock")
    monkeypatch.setenv("MOCK_SCENARIO", "big")
    monkeypatch.setenv("MOCK_DELAY_MAX_MS", "0")
    monkeypatch.setenv("MOCK_FIXTURES_DIR", str(tmp_path))
    monkeypatch.setenv("RUNNER_LOG_DIR", str(tmp_path / "runner_logs"))

    big = "x" * (12 * 1024)
    (tmp_path / "mock_big.json").write_text(json.dumps({"exit_code": 0, "stdout": big, "stderr": ""}), encoding="utf-8")

    r = run_cmd(cmd=["cargo", "test"], cwd=".", env={}, timeout=5, capture=True)
    assert r.exit_code == 0
    assert r.log_path
    assert r.stdout == ""
    p = Path(r.log_path)
    assert p.exists()
    with gzip.open(p, "rb") as f:
        raw = f.read().decode("utf-8", errors="replace")
    obj = json.loads(raw)
    assert len(obj["stdout"]) >= 10 * 1024
