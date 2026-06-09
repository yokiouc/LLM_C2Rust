"""Prompt assembly for controlled patch generation.

Builds structured prompts from evidence packs, constraints, and boundaries.
"""

import json
from pathlib import Path
from typing import Any

from packages.core.constants import DEFAULT_PATCH_CONSTRAINTS, DEFAULT_FORBIDDEN_ACTIONS


def _fetch_chunk_content(chunk_id: Any) -> str:
    try:
        cid = int(chunk_id)
    except Exception:
        return ""
    try:
        from packages.core.db import connect

        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT content FROM code_chunks WHERE chunk_id = %s;", (cid,))
                row = cur.fetchone()
                return str(row[0] or "") if row else ""
    except Exception:
        return ""


def _augment_with_full_content(*, items: list[dict[str, Any]], target_file: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        if str(meta.get("file") or "") != target_file:
            continue
        content = _fetch_chunk_content(item.get("chunk_id"))
        if not content:
            continue
        out.append(
            {
                "chunk_id": item.get("chunk_id"),
                "kind": item.get("kind"),
                "file": target_file,
                "content": content,
                "line_count": len(content.splitlines()),
                "old_lines_must_match_exactly": content.splitlines(),
            }
        )
    return out[:5]


def _safe_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except Exception:
        return None


def _line_range(lines: list[str], start_line: int, end_line: int):
    lo = max(start_line, 1)
    hi = min(end_line, len(lines))
    for line_no in range(lo, hi + 1):
        yield line_no, lines[line_no - 1]


def _find_enclosing_unsafe_block(lines: list[str], call_line: int, start_line: int, end_line: int) -> tuple[int, int]:
    block_start = call_line
    while block_start > start_line and "unsafe" not in lines[block_start - 1]:
        block_start -= 1
    block_end = call_line
    while block_end <= end_line and "}" not in lines[block_end - 1]:
        block_end += 1
    if block_end > end_line:
        block_end = call_line
    if block_start > start_line and "SAFETY:" in lines[block_start - 2]:
        block_start -= 1
    return block_start, block_end


def _find_exact_replacement_block(*, lines: list[str], start_line: int, end_line: int) -> dict[str, Any]:
    """Select one small, high-priority old block inside the repair slice."""
    # 1. ptr copy / memcpy-style unsafe block
    for line_no, line in _line_range(lines, start_line, end_line):
        if "ptr::copy_nonoverlapping" in line or "ptr::copy(" in line:
            block_start, block_end = _find_enclosing_unsafe_block(lines, line_no, start_line, end_line)
            old_lines = lines[block_start - 1:block_end]
            return {
                "kind": "ptr_copy",
                "start_line": block_start,
                "end_line": block_end,
                "old_block": "\n".join(old_lines),
                "old_lines": old_lines,
            }

    # 2. pointer arithmetic / raw pointer walk
    for line_no, line in _line_range(lines, start_line, end_line):
        if ".add(" not in line and ".offset(" not in line:
            continue
        block_start = line_no
        for prev in range(line_no - 1, max(start_line, line_no - 6) - 1, -1):
            if ".as_ptr()" in lines[prev - 1] or ".as_mut_ptr()" in lines[prev - 1]:
                block_start = prev
                break
            if "let " in lines[prev - 1] and "base" in lines[prev - 1]:
                block_start = prev
                break
        if block_start == line_no:
            # Include a compact if/else expression when the unsafe op is nested in it.
            for prev in range(line_no - 1, max(start_line, line_no - 5) - 1, -1):
                if " else {" in lines[prev - 1] or lines[prev - 1].strip().endswith("else {"):
                    block_start = prev
                    break
        block_end = line_no
        while block_end < end_line and lines[block_end - 1].count("{") > lines[block_end - 1].count("}"):
            block_end += 1
        old_lines = lines[block_start - 1:block_end]
        return {
            "kind": "pointer_arithmetic",
            "start_line": block_start,
            "end_line": block_end,
            "old_block": "\n".join(old_lines),
            "old_lines": old_lines,
        }

    # 3. raw pointer dereference / unsafe block
    for line_no, line in _line_range(lines, start_line, end_line):
        if "unsafe" in line:
            block_start, block_end = _find_enclosing_unsafe_block(lines, line_no, start_line, end_line)
            old_lines = lines[block_start - 1:block_end]
            return {
                "kind": "unsafe_block",
                "start_line": block_start,
                "end_line": block_end,
                "old_block": "\n".join(old_lines),
                "old_lines": old_lines,
            }

    old_lines = lines[start_line - 1:end_line]
    return {
        "kind": "slice",
        "start_line": start_line,
        "end_line": end_line,
        "old_block": "\n".join(old_lines),
        "old_lines": old_lines,
    }


def _load_exact_slice_block(*, workspace_path: str | None, target_file: str, boundary: dict[str, Any]) -> dict[str, Any]:
    if not workspace_path or not target_file:
        return {}
    start_line = _safe_int(boundary.get("start_line"))
    end_line = _safe_int(boundary.get("end_line"))
    if not start_line or not end_line or end_line < start_line:
        return {}
    full_path = Path(workspace_path).resolve() / str(target_file).replace("\\", "/")
    if not full_path.exists():
        return {}
    lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return {}
    end_line = min(end_line, len(lines))
    if start_line > end_line:
        return {}
    selected = _find_exact_replacement_block(lines=lines, start_line=start_line, end_line=end_line)
    selected["target_file"] = target_file
    selected["slice_start"] = start_line
    selected["slice_end"] = end_line
    return selected


def build_repair_prompt(
    *,
    task_description: str,
    target_file: str,
    boundary: dict[str, Any],
    evidence_items: list[dict[str, Any]],
    strategies: list[dict[str, Any]] | None = None,
    diagnose_issues: list[dict[str, Any]] | None = None,
    constraints: list[str] | None = None,
    forbidden: list[str] | None = None,
    workspace_path: str | None = None,
) -> str:
    """Build the evidence JSON object used as context for patch generation."""
    constraints = constraints or list(DEFAULT_PATCH_CONSTRAINTS)
    forbidden = forbidden or list(DEFAULT_FORBIDDEN_ACTIONS)
    full_target_items = _augment_with_full_content(items=evidence_items, target_file=target_file)
    exact_replacement_block = _load_exact_slice_block(
        workspace_path=workspace_path,
        target_file=target_file,
        boundary=boundary,
    )

    evidence_obj = {
        "task_description": task_description,
        "recommended_boundary": {
            "file": target_file,
            "start_line": boundary.get("start_line"),
            "end_line": boundary.get("end_line"),
            "anchor_line": boundary.get("anchor_line"),
            "anchor_kind": boundary.get("anchor_kind"),
        },
        "target_file": target_file,
        "repair_slice_context": {
            "slice_start": boundary.get("start_line"),
            "slice_end": boundary.get("end_line"),
            "target_file": target_file,
            "signature_text": boundary.get("signature_text"),
            "signature_line": boundary.get("signature_line"),
            "forbidden_regions": boundary.get("forbidden_regions") or [],
            "full_target_items": full_target_items,
            "exact_replacement_block": exact_replacement_block,
            "instructions": [
                "Use exact old lines from full_target_items when constructing '-' hunk lines.",
                "If replacement-block mode is requested, replace only exact_replacement_block.old_block.",
                "The old hunk must match the target file byte-for-byte except line endings.",
                "Do not add unrelated marker lines such as _ptr_import_marker.",
                "Do not modify imports.",
                "Do not modify function signatures.",
                "Only replace the unsafe block or target unsafe statement inside the repair slice.",
            ],
        },
        "constraints": constraints,
        "forbidden": forbidden,
        "strategies": (strategies or [])[:10],
        "items": evidence_items,
        "diagnose": diagnose_issues or [],
    }
    return json.dumps(evidence_obj, ensure_ascii=False)
