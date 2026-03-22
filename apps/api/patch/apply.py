import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApplyResult:
    ok: bool
    status: str
    file_paths: list[str]
    backup_dir: str | None
    error_msg: str | None


_RE_FILE_HEADERS = re.compile(r"^(---|\+\+\+) (a|b)/(.+)$", re.MULTILINE)
_RE_HUNK = re.compile(r"^@@ -(\d+),(\d+) \+(\d+),(\d+) @@\s*$", re.MULTILINE)


def _extract_paths(unified_diff: str) -> list[str]:
    paths: list[str] = []
    for _kind, _ab, p in _RE_FILE_HEADERS.findall(unified_diff):
        if p not in paths:
            paths.append(p)
    return paths


def _backup_files(base_dir: Path, rel_paths: list[str], backup_dir: Path) -> None:
    for rel in rel_paths:
        src = base_dir / rel
        if not src.exists():
            continue
        dst = backup_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def rollback(base_dir: Path, backup_dir: Path) -> None:
    if not backup_dir.exists():
        return
    for root, _dirs, files in os.walk(backup_dir):
        for fn in files:
            src = Path(root) / fn
            rel = src.relative_to(backup_dir)
            dst = base_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def apply_patch(base_dir: Path, unified_diff: str) -> ApplyResult:
    file_paths = _extract_paths(unified_diff)
    backup_dir = Path(tempfile.mkdtemp(prefix="patch_backup_"))
    try:
        _backup_files(base_dir, file_paths, backup_dir)
        if not file_paths:
            raise ValueError("diff_missing_file_headers")

        target_rel = file_paths[0]
        target = base_dir / target_rel
        if not target.exists():
            raise FileNotFoundError(target_rel)

        m = _RE_HUNK.search(unified_diff)
        if not m:
            raise ValueError("diff_missing_hunk_header")

        old_start = int(m.group(1))
        hunk_body = unified_diff[m.end() :].splitlines()
        old_lines = target.read_text(encoding="utf-8").splitlines(keepends=False)

        idx = old_start - 1
        i = 0
        while i < len(hunk_body):
            line = hunk_body[i]
            if line.startswith("--- ") or line.startswith("+++ ") or line.startswith("@@ "):
                break
            if not line:
                i += 1
                continue
            tag = line[0]
            text = line[1:]
            if tag == " ":
                if idx >= len(old_lines) or old_lines[idx] != text:
                    raise ValueError("context_mismatch")
                idx += 1
            elif tag == "-":
                if idx >= len(old_lines) or old_lines[idx] != text:
                    raise ValueError("remove_mismatch")
                del old_lines[idx]
            elif tag == "+":
                old_lines.insert(idx, text)
                idx += 1
            else:
                raise ValueError("invalid_hunk_line")
            i += 1

        target.write_text("\n".join(old_lines) + ("\n" if old_lines else ""), encoding="utf-8", newline="\n")
        return ApplyResult(ok=True, status="applied", file_paths=file_paths, backup_dir=str(backup_dir), error_msg=None)
    except Exception as e:
        rollback(base_dir, backup_dir)
        return ApplyResult(ok=False, status="rolled_back", file_paths=file_paths, backup_dir=str(backup_dir), error_msg=str(e))
