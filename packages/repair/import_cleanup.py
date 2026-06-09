"""Conservative lint-driven clippy cleanup."""

import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CleanupResult:
    ok: bool
    changed: bool
    diff: str
    error: str | None = None
    validation_results: list[Any] | None = None


_UNUSED_IMPORT_RE = re.compile(
    r"unused import: `(?P<import>[^`]+)`.*?-->\s+(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+)",
    re.DOTALL,
)
_UNUSED_VARIABLE_RE = re.compile(
    r"unused variable: `(?P<name>[^`]+)`.*?-->\s+(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+)",
    re.DOTALL,
)
_UNNECESSARY_MUT_RE = re.compile(
    r"variable does not need to be mutable.*?-->\s+(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+)",
    re.DOTALL,
)
_UNNECESSARY_UNSAFE_RE = re.compile(
    r"unnecessary `unsafe` block.*?-->\s+(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+)",
    re.DOTALL,
)
_SINGLE_USE_RE = re.compile(r"^\s*use\s+[^{}*;]+;\s*$")
_LOW_RISK_UNUSED_LET_RE = re.compile(r"^\s*let\s+(?:mut\s+)?(?P<name>\w+)\s*=\s*(?P<rhs>[^;]+);\s*$")


def _norm_path(path: str) -> str:
    return str(path or "").strip().replace("\\", "/").lstrip("./")


def find_unused_import_diagnostics(diagnostics: str, *, target_file: str) -> list[dict[str, Any]]:
    target = _norm_path(target_file)
    out: list[dict[str, Any]] = []
    for m in _UNUSED_IMPORT_RE.finditer(str(diagnostics or "")):
        file_path = _norm_path(m.group("file"))
        if file_path != target:
            continue
        out.append(
            {
                "file": file_path,
                "line": int(m.group("line")),
                "column": int(m.group("col")),
                "import": str(m.group("import")),
            }
        )
    return out


def _find_line_diagnostics(pattern: re.Pattern, diagnostics: str, *, target_file: str, kind: str) -> list[dict[str, Any]]:
    target = _norm_path(target_file)
    out: list[dict[str, Any]] = []
    for m in pattern.finditer(str(diagnostics or "")):
        file_path = _norm_path(m.group("file"))
        if file_path != target:
            continue
        item = {
            "kind": kind,
            "file": file_path,
            "line": int(m.group("line")),
            "column": int(m.group("col")),
        }
        if "name" in m.groupdict():
            item["name"] = str(m.group("name"))
        out.append(item)
    return out


def _is_safe_single_import_line(line: str, import_name: str) -> bool:
    stripped = line.strip()
    if not _SINGLE_USE_RE.match(line):
        return False
    if stripped.startswith("pub use "):
        return False
    if "*" in stripped or "{" in stripped or "}" in stripped:
        return False
    return stripped == f"use {import_name};"


def cleanup_unused_imports_from_diagnostics(
    *,
    workspace_path: Path,
    target_file: str,
    diagnostics: str,
) -> CleanupResult:
    target = _norm_path(target_file)
    full_path = workspace_path / target
    if not full_path.exists():
        return CleanupResult(False, False, "", "target_file_missing")

    findings = find_unused_import_diagnostics(diagnostics, target_file=target)
    if not findings:
        return CleanupResult(True, False, "")

    lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
    remove_lines: dict[int, str] = {}
    for finding in findings:
        line_no = int(finding["line"])
        if line_no < 1 or line_no > len(lines):
            return CleanupResult(False, False, "", "diagnostic_line_out_of_range")
        line = lines[line_no - 1]
        if not _is_safe_single_import_line(line, str(finding["import"])):
            return CleanupResult(False, False, "", "unsupported_import_cleanup")
        remove_lines[line_no] = line

    if not remove_lines:
        return CleanupResult(True, False, "")

    new_lines = [line for idx, line in enumerate(lines, start=1) if idx not in remove_lines]
    full_path.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8", newline="\n")

    diff_parts = [f"--- a/{target}", f"+++ b/{target}"]
    for line_no in sorted(remove_lines):
        diff_parts.append(f"@@ -{line_no},1 +{line_no},0 @@")
        diff_parts.append(f"-{remove_lines[line_no]}")
    return CleanupResult(True, True, "\n".join(diff_parts) + "\n")


def _is_low_risk_unused_let(line: str, name: str) -> bool:
    m = _LOW_RISK_UNUSED_LET_RE.match(line)
    if not m or m.group("name") != name:
        return False
    rhs = m.group("rhs").strip()
    return ".as_ptr()" in rhs or ".as_mut_ptr()" in rhs


def _remove_unnecessary_mut(line: str) -> str | None:
    if "let mut " not in line:
        return None
    return line.replace("let mut ", "let ", 1)


def _remove_single_line_unsafe(line: str) -> str | None:
    if "unsafe" not in line or "{" not in line or "}" not in line:
        return None
    replaced = re.sub(r"unsafe\s*\{\s*(.*?)\s*\}", r"\1", line, count=1)
    return replaced if replaced != line else None


def _diff_for_line_changes(target: str, changes: dict[int, tuple[str, str | None]]) -> str:
    parts = [f"--- a/{target}", f"+++ b/{target}"]
    for line_no in sorted(changes):
        old, new = changes[line_no]
        if new is None:
            parts.append(f"@@ -{line_no},1 +{line_no},0 @@")
            parts.append(f"-{old}")
        else:
            parts.append(f"@@ -{line_no},1 +{line_no},1 @@")
            parts.append(f"-{old}")
            parts.append(f"+{new}")
    return "\n".join(parts) + "\n"


def cleanup_clippy_diagnostics_from_diagnostics(
    *,
    workspace_path: Path,
    target_file: str,
    diagnostics: str,
) -> CleanupResult:
    target = _norm_path(target_file)
    full_path = workspace_path / target
    if not full_path.exists():
        return CleanupResult(False, False, "", "target_file_missing")

    lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
    changes: dict[int, tuple[str, str | None]] = {}

    def _line(line_no: int) -> str | None:
        if line_no < 1 or line_no > len(lines):
            return None
        return lines[line_no - 1]

    for finding in find_unused_import_diagnostics(diagnostics, target_file=target):
        line_no = int(finding["line"])
        line = _line(line_no)
        if line is None:
            return CleanupResult(False, False, "", "diagnostic_line_out_of_range")
        if not _is_safe_single_import_line(line, str(finding["import"])):
            return CleanupResult(False, False, "", "unsupported_import_cleanup")
        changes[line_no] = (line, None)

    for finding in _find_line_diagnostics(_UNUSED_VARIABLE_RE, diagnostics, target_file=target, kind="unused_variable"):
        line_no = int(finding["line"])
        line = _line(line_no)
        if line is None:
            return CleanupResult(False, False, "", "diagnostic_line_out_of_range")
        if not _is_low_risk_unused_let(line, str(finding["name"])):
            return CleanupResult(False, False, "", "unsupported_unused_variable_cleanup")
        if line_no in changes:
            return CleanupResult(False, False, "", "overlapping_cleanup")
        changes[line_no] = (line, None)

    for finding in _find_line_diagnostics(_UNNECESSARY_MUT_RE, diagnostics, target_file=target, kind="unused_mut"):
        line_no = int(finding["line"])
        line = _line(line_no)
        if line is None:
            return CleanupResult(False, False, "", "diagnostic_line_out_of_range")
        new_line = _remove_unnecessary_mut(line)
        if new_line is None:
            return CleanupResult(False, False, "", "unsupported_mut_cleanup")
        if line_no in changes:
            return CleanupResult(False, False, "", "overlapping_cleanup")
        changes[line_no] = (line, new_line)

    for finding in _find_line_diagnostics(_UNNECESSARY_UNSAFE_RE, diagnostics, target_file=target, kind="unnecessary_unsafe"):
        line_no = int(finding["line"])
        line = _line(line_no)
        if line is None:
            return CleanupResult(False, False, "", "diagnostic_line_out_of_range")
        new_line = _remove_single_line_unsafe(line)
        if new_line is None:
            return CleanupResult(False, False, "", "unsupported_unsafe_cleanup")
        if line_no in changes:
            return CleanupResult(False, False, "", "overlapping_cleanup")
        changes[line_no] = (line, new_line)

    if not changes:
        return CleanupResult(True, False, "")

    new_lines: list[str] = []
    for idx, line in enumerate(lines, start=1):
        if idx not in changes:
            new_lines.append(line)
            continue
        _old, new = changes[idx]
        if new is not None:
            new_lines.append(new)

    full_path.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8", newline="\n")
    return CleanupResult(True, True, _diff_for_line_changes(target, changes))


def cleanup_unused_imports_and_validate(
    *,
    workspace_path: Path,
    target_file: str,
    diagnostics: str,
    env: dict[str, str] | None = None,
    timeout: int = 120,
) -> CleanupResult:
    backup_dir = Path(tempfile.mkdtemp(prefix="unused_import_cleanup_"))
    target = _norm_path(target_file)
    src = workspace_path / target
    dst = backup_dir / target
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    cleanup = cleanup_clippy_diagnostics_from_diagnostics(
        workspace_path=workspace_path,
        target_file=target,
        diagnostics=diagnostics,
    )
    if not cleanup.ok or not cleanup.changed:
        return cleanup

    from packages.runner.validator import run_validation_phase

    results = []
    for stage in ("build", "test", "clippy"):
        result = run_validation_phase(
            stage=stage,
            workspace_path=workspace_path,
            env=env or {},
            timeout=timeout,
        )
        results.append(result)
        if not result.ok:
            if dst.exists():
                shutil.copy2(dst, src)
            return CleanupResult(False, True, cleanup.diff, f"{stage}_failed", results)

    return CleanupResult(True, True, cleanup.diff, None, results)


def cleanup_clippy_diagnostics_and_validate(
    *,
    workspace_path: Path,
    target_file: str,
    diagnostics: str,
    env: dict[str, str] | None = None,
    timeout: int = 120,
) -> CleanupResult:
    return cleanup_unused_imports_and_validate(
        workspace_path=workspace_path,
        target_file=target_file,
        diagnostics=diagnostics,
        env=env,
        timeout=timeout,
    )
