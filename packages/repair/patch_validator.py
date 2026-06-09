"""Patch constraint validation.

Extracted from apps/api/agent/fsm.py — validates that generated patches
conform to the controlled repair constraints.
"""

import re
from typing import Any

_HUNK_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")


def validate_patch_constraints(
    *,
    diff: str,
    target_file: str,
    signature_text: str | None,
    boundary: dict[str, Any],
    max_changed_pairs: int = 20,
    max_total_lines: int = 120,
) -> tuple[bool, dict[str, Any] | None]:
    """Validate a generated patch against controlled repair constraints.

    Returns (True, None) if valid, or (False, violation_detail) if invalid.
    """
    lines = (diff or "").splitlines()
    if len(lines) > max_total_lines:
        return False, {"code": "too_large", "detail": {"max_total_lines": max_total_lines, "actual_lines": len(lines)}}

    file_paths: set[str] = set()
    hunk_headers = 0
    changed = 0
    old_start: int | None = None

    for ln in lines:
        if ln.startswith("--- a/") or ln.startswith("+++ b/"):
            p = ln.split("/", 1)[1].strip()
            if p:
                file_paths.add(p)
            continue

        if ln.startswith("@@"):
            hunk_headers += 1
            if old_start is None:
                m = _HUNK_RE.match(ln)
                if m:
                    old_start = int(m.group(1))
            continue

        if ln.startswith(("+", "-")) and not ln.startswith(("+++ ", "--- ")):
            changed += 1
            if signature_text and signature_text.strip() and signature_text.strip() in ln[1:]:
                return False, {"code": "signature_changed", "detail": {"signature": signature_text.strip()}}

    if not file_paths:
        return False, {"code": "missing_file_header", "detail": {}}
    if len(file_paths) != 1:
        return False, {"code": "multi_file_patch", "detail": {"files": sorted(file_paths)}}
    only_file = next(iter(file_paths))
    if only_file != target_file:
        return False, {"code": "target_file_mismatch", "detail": {"expected": target_file, "actual": only_file}}
    if hunk_headers != 1:
        return False, {"code": "multi_hunk", "detail": {"hunks": hunk_headers}}
    if changed == 0:
        return False, {"code": "no_changes", "detail": {}}
    if changed > max_changed_pairs * 2:
        return False, {"code": "too_many_changes", "detail": {"max_changed_pairs": max_changed_pairs, "actual_change_lines": changed}}
    if old_start is None:
        return False, {"code": "missing_hunk_header", "detail": {}}

    start_line = boundary.get("start_line")
    end_line = boundary.get("end_line")
    if isinstance(start_line, int) and isinstance(end_line, int):
        if not (start_line <= old_start <= end_line):
            return False, {"code": "outside_boundary", "detail": {"old_start": old_start, "boundary": {"start_line": start_line, "end_line": end_line}}}

    return True, None


def validate_diff_only_hunks(diff: str) -> bool:
    """Validate that diff contains only valid hunk lines."""
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
