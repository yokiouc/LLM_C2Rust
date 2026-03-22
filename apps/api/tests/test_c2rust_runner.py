import gzip
import json
import shutil
import sys
from pathlib import Path

import pytest

from tools import c2rust_runner


def test_dir_content_hash_repeatable(tmp_path: Path):
    (tmp_path / "a").write_text("1", encoding="utf-8")
    (tmp_path / "b").write_text("2", encoding="utf-8")
    hs = [c2rust_runner._dir_content_hash(tmp_path) for _ in range(5)]
    assert len(set(hs)) == 1


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_commit_sha_detectable(tmp_path: Path, monkeypatch):
    import subprocess

    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True)  # noqa: S603
    (tmp_path / "a.c").write_text("int main() {return 0;}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True)  # noqa: S603
    subprocess.run(["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-m", "init"], cwd=str(tmp_path), check=True)  # noqa: S603
    sha = c2rust_runner._git_commit_sha(tmp_path)
    assert sha
    assert len(sha) >= 7


def test_run_writes_structured_log_and_manifest(tmp_path: Path, monkeypatch):
    c_project = tmp_path / "cproj"
    c_project.mkdir()
    (c_project / "a.c").write_text("int main() {return 0;}\n", encoding="utf-8")

    out_dir = tmp_path / "out"
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("RUNNER_MODE", "real")
    monkeypatch.setenv("C2RUST_LOG_DIR", str(log_dir))

    monkeypatch.setattr(c2rust_runner, "_detect_c2rust_version", lambda _: "c2rust 0.0.0")

    def build_cmd(*, c2rust_bin: str, c_project_path: Path, rust_workspace_dir: Path, extra_args: list[str]):
        script = (
            "from pathlib import Path; "
            f'root=Path(r"{rust_workspace_dir}"); '
            "root.mkdir(parents=True, exist_ok=True); "
            "(root/'src').mkdir(parents=True, exist_ok=True); "
            "(root/'src'/'lib.rs').write_text('fn f() {}\\n', encoding='utf-8')"
        )
        return [sys.executable, "-c", script]

    monkeypatch.setattr(c2rust_runner, "_build_transpile_cmd", build_cmd)

    r = c2rust_runner.run(c_project_path=c_project, output_dir=out_dir)
    assert r.exit_code == 0
    assert Path(r.manifest_path).exists()
    assert Path(r.log_path).exists()

    with gzip.open(r.log_path, "rb") as f:
        obj = json.loads(f.read().decode("utf-8", errors="replace"))
    assert obj["cwd"]
    assert obj["cmd"]
    assert isinstance(obj["exit_code"], int)
    assert "snapshot_version" in obj
    assert "c2rust_version" in obj
