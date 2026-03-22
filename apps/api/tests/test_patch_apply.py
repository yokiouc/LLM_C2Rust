from pathlib import Path

from patch.apply import apply_patch, rollback
from patch.generator import FileContent, generate_patch


def test_apply_patch_success_no_change(tmp_path: Path):
    p = tmp_path / "file.txt"
    p.write_text("line1\nline2\nline3\n", encoding="utf-8", newline="\n")

    old = FileContent(path="file.txt", content=p.read_text(encoding="utf-8"))
    diff = generate_patch([old], [old])
    r = apply_patch(tmp_path, diff)
    assert r.ok is True
    assert r.status == "applied"
    assert p.read_text(encoding="utf-8") == "line1\nline2\nline3\n"


def test_apply_patch_failure_rolls_back(tmp_path: Path):
    p = tmp_path / "file.txt"
    p.write_text("line1\nline2\nline3\n", encoding="utf-8", newline="\n")

    bad = "not a diff\n"
    r = apply_patch(tmp_path, bad)
    assert r.ok is False
    assert r.status == "rolled_back"
    assert p.read_text(encoding="utf-8") == "line1\nline2\nline3\n"

    assert r.backup_dir
    rollback(tmp_path, Path(r.backup_dir))
    assert p.read_text(encoding="utf-8") == "line1\nline2\nline3\n"
