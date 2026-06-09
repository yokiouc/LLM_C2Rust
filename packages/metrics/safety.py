"""Safety metrics computation for Rust source files.

Computes before/after safety metrics for thesis evaluation.
"""

import re
from pathlib import Path

from packages.core.types import SafetyMetrics


_RE_UNSAFE_BLOCK = re.compile(r"\bunsafe\s*\{")
_RE_RAW_PTR = re.compile(r"(\*const\b|\*mut\b|\bas\s+\*const\b|\bas\s+\*mut\b)")
_RE_UNSAFE_API = re.compile(r"\b(std::ptr::\w+|core::ptr::\w+|slice::from_raw_parts|transmute|forget)\b")
_RE_MANUAL_MEM = re.compile(r"\b(malloc|calloc|realloc|free|alloc::alloc|alloc::dealloc|memcpy|memmove|memset)\b")


def compute_safety_metrics(root: Path) -> SafetyMetrics:
    """Scan all .rs files under root and compute safety metrics."""
    unsafe_block_count = 0
    raw_ptr_count = 0
    unsafe_api_count = 0
    manual_mem_call_count = 0
    unsafe_lines = 0
    total_lines = 0

    for p in sorted(root.rglob("*.rs"), key=lambda x: x.as_posix().lower()):
        txt = p.read_text(encoding="utf-8", errors="replace")
        unsafe_block_count += len(_RE_UNSAFE_BLOCK.findall(txt))
        raw_ptr_count += len(_RE_RAW_PTR.findall(txt))
        unsafe_api_count += len(_RE_UNSAFE_API.findall(txt))
        manual_mem_call_count += len(_RE_MANUAL_MEM.findall(txt))

        lines = txt.splitlines()
        total_lines += len(lines)
        for line in lines:
            if "unsafe" in line:
                unsafe_lines += 1

    unsafe_line_pct = (unsafe_lines / total_lines * 100.0) if total_lines else 0.0

    return SafetyMetrics(
        unsafe_block_count=unsafe_block_count,
        raw_ptr_count=raw_ptr_count,
        unsafe_api_count=unsafe_api_count,
        manual_mem_call_count=manual_mem_call_count,
        unsafe_line_pct=round(unsafe_line_pct, 2),
        total_lines=total_lines,
    )


def compute_rust_metrics_in_dir(root: Path) -> dict:
    """Backward-compatible wrapper returning dict format used by engine.py."""
    m = compute_safety_metrics(root)
    return {
        "unsafe_blocks": m.unsafe_block_count,
        "unsafe_line_pct": m.unsafe_line_pct,
        "raw_ptr_count": m.raw_ptr_count,
        "unsafe_api_count": m.unsafe_api_count,
        "manual_mem_call_count": m.manual_mem_call_count,
    }
