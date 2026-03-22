import shutil
import sys
from pathlib import Path

import pytest

from runner.cargo import _build_cargo_cmd
from runner.cmd import run_cmd


def test_real_runner_timeout_kills(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RUNNER_MODE", "real")
    monkeypatch.setenv("RUNNER_LOG_DIR", str(tmp_path / "runner_logs"))
    r = run_cmd(cmd=[sys.executable, "-c", "import time; time.sleep(2)"], cwd=str(tmp_path), env={}, timeout=1, capture=True)
    assert r.exit_code == 124
    assert "timeout" in (r.stderr or "").lower()


def test_build_cargo_cmd_uses_rustup_when_toolchain_present(tmp_path: Path, monkeypatch):
    (tmp_path / "rust-toolchain.toml").write_text('[toolchain]\nchannel = "stable"\n', encoding="utf-8")
    monkeypatch.setattr("runner.cargo.shutil.which", lambda _: "rustup")
    cmd = _build_cargo_cmd(cmd=["cargo", "check"], cwd=str(tmp_path))
    assert cmd[:4] == ["rustup", "run", "stable", "cargo"]


@pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo not installed")
def test_real_cargo_check_build_test(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RUNNER_MODE", "real")
    monkeypatch.setenv("RUNNER_LOG_DIR", str(tmp_path / "runner_logs"))

    project_dir = tmp_path / "demo"
    (project_dir / "src").mkdir(parents=True, exist_ok=True)
    (project_dir / "Cargo.toml").write_text(
        '\n'.join(
            [
                "[package]",
                'name = "demo"',
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
    )
    (project_dir / "src" / "lib.rs").write_text(
        "\n".join(
            [
                "pub fn add(a: i32, b: i32) -> i32 {",
                "    a + b",
                "}",
                "",
                "#[cfg(test)]",
                "mod tests {",
                "    use super::*;",
                "",
                "    #[test]",
                "    fn it_works() {",
                "        assert_eq!(add(1, 2), 3);",
                "    }",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )

    env = {"CARGO_TARGET_DIR": str(tmp_path / "target")}
    r1 = run_cmd(cmd=["cargo", "check", "--quiet"], cwd=str(project_dir), env=env, timeout=120, capture=True)
    assert r1.exit_code == 0
    r2 = run_cmd(cmd=["cargo", "build", "--quiet"], cwd=str(project_dir), env=env, timeout=120, capture=True)
    assert r2.exit_code == 0
    r3 = run_cmd(cmd=["cargo", "test", "--quiet"], cwd=str(project_dir), env=env, timeout=120, capture=True)
    assert r3.exit_code == 0

