"""Slice builder: constructs minimal repair slices from hotspots.

Each slice is bounded by function boundaries, carries interface constraints,
and explicitly marks forbidden edit regions (signatures, module-level items).
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packages.core.types import HotspotInfo, SliceInfo


# ---------------------------------------------------------------------------
# Tree-sitter helpers (reuse from chunker)
# ---------------------------------------------------------------------------

def _try_tree_sitter_rust() -> tuple[Any, Any] | None:
    try:
        from tree_sitter import Parser
    except Exception:
        return None
    try:
        from tree_sitter_languages import get_language
        lang = get_language("rust")
        parser = Parser()
        parser.set_language(lang)
        return parser, lang
    except Exception:
        try:
            from tree_sitter_rust import language as rust_language
            parser = Parser()
            parser.set_language(rust_language())
            return parser, rust_language()
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Function boundary detection
# ---------------------------------------------------------------------------

@dataclass
class _FuncBoundary:
    """Parsed function boundary from source."""
    name: str | None
    start_line: int  # 1-based
    end_line: int    # 1-based
    signature_line: int  # 1-based, the line with "fn ..."
    signature_text: str
    is_pub: bool
    is_unsafe: bool
    params: list[str] = field(default_factory=list)


_RE_FN_SIG = re.compile(
    r"^(\s*)(pub(?:\(crate\))?\s+)?(unsafe\s+)?fn\s+(\w+)"
)

_RE_VAR_BINDING = re.compile(r"\blet\s+(mut\s+)?(\w+)")
_RE_RAW_PTR = re.compile(r"(\*const\b|\*mut\b)")
_RE_UNSAFE_OP = re.compile(
    r"(\bunsafe\b|\*const|\*mut|\.offset\(|\.add\(|\.sub\(|"
    r"ptr::copy|ptr::read|ptr::write|transmute|forget|"
    r"malloc|free|calloc|realloc|memcpy|memmove|memset|"
    r"from_raw_parts|Box::from_raw|Box::into_raw)"
)


def _find_function_boundaries_regex(lines: list[str]) -> list[_FuncBoundary]:
    """Find function boundaries using regex (fallback)."""
    boundaries: list[_FuncBoundary] = []
    i = 0
    while i < len(lines):
        m = _RE_FN_SIG.match(lines[i])
        if m:
            sig_line = i + 1  # 1-based
            indent = m.group(1) or ""
            is_pub = bool(m.group(2))
            is_unsafe = bool(m.group(3))
            name = m.group(4)

            # Extract signature text (may span multiple lines)
            sig_text = lines[i].strip()

            # Find function end by brace matching
            brace_depth = 0
            start = i
            end = i
            for j in range(i, min(i + 500, len(lines))):
                brace_depth += lines[j].count("{") - lines[j].count("}")
                if brace_depth <= 0 and j > i:
                    end = j
                    break
            else:
                end = min(i + 50, len(lines) - 1)

            # Extract parameter names from signature
            params: list[str] = []
            sig_full = "\n".join(lines[i:min(i + 5, len(lines))])
            paren_match = re.search(r"\(([^)]*)\)", sig_full)
            if paren_match:
                for param in paren_match.group(1).split(","):
                    param = param.strip()
                    pname = param.split(":")[0].strip().replace("mut ", "").strip()
                    if pname and pname != "self" and pname != "&self" and pname != "&mut self":
                        params.append(pname)

            boundaries.append(_FuncBoundary(
                name=name,
                start_line=start + 1,  # 1-based
                end_line=end + 1,       # 1-based
                signature_line=sig_line,
                signature_text=sig_text,
                is_pub=is_pub,
                is_unsafe=is_unsafe,
                params=params,
            ))
            i = end + 1
        else:
            i += 1
    return boundaries


def _find_function_boundaries_ast(raw: bytes, parser: Any) -> list[_FuncBoundary]:
    """Find function boundaries using tree-sitter AST."""
    tree = parser.parse(raw)
    boundaries: list[_FuncBoundary] = []

    def walk(node: Any) -> None:
        if node.type == "function_item":
            name_node = node.child_by_field_name("name")
            name = raw[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace") if name_node else None
            sr = node.start_point[0] + 1
            er = node.end_point[0] + 1
            content = raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
            first_line = content.split("\n")[0].strip()

            is_pub = "pub " in first_line or "pub(" in first_line
            is_unsafe = "unsafe fn" in first_line

            # Extract params
            params_node = node.child_by_field_name("parameters")
            params: list[str] = []
            if params_node:
                for i in range(params_node.child_count):
                    p = params_node.child(i)
                    if p.type == "parameter":
                        pat_node = p.child_by_field_name("pattern")
                        if pat_node:
                            pname = raw[pat_node.start_byte:pat_node.end_byte].decode("utf-8", errors="replace")
                            pname = pname.replace("mut ", "").strip()
                            if pname:
                                params.append(pname)

            boundaries.append(_FuncBoundary(
                name=name,
                start_line=sr,
                end_line=er,
                signature_line=sr,
                signature_text=first_line,
                is_pub=is_pub,
                is_unsafe=is_unsafe,
                params=params,
            ))
            return  # Don't recurse into nested fns (rare in C2Rust output)
        for i in range(node.child_count):
            walk(node.child(i))

    walk(tree.root_node)
    return boundaries


# ---------------------------------------------------------------------------
# Slice construction
# ---------------------------------------------------------------------------

def _extract_related_vars(lines: list[str], start: int, end: int) -> list[str]:
    """Extract variable names from let bindings in the given line range (0-based)."""
    vars_found: list[str] = []
    for line in lines[start:end]:
        for m in _RE_VAR_BINDING.finditer(line):
            vname = m.group(2)
            if vname and vname not in vars_found:
                vars_found.append(vname)
    return vars_found


def _extract_related_unsafe_ops(lines: list[str], start: int, end: int) -> list[str]:
    """Extract unsafe operation patterns in the given line range (0-based)."""
    ops: list[str] = []
    for line in lines[start:end]:
        for m in _RE_UNSAFE_OP.finditer(line):
            op = m.group(0).strip()
            if op and op not in ops:
                ops.append(op)
    return ops


def build_slices_for_hotspots(
    workspace_path: Path,
    hotspots: list[HotspotInfo],
    *,
    context_lines: int = 5,
) -> list[SliceInfo]:
    """Build repair slices from discovered hotspots.

    Strategy:
    1. Find function boundary containing each hotspot
    2. Use function boundary as the primary slice boundary
    3. If hotspot is outside any function, use hotspot ± context_lines
    4. Mark signature lines as forbidden edit regions
    5. Extract related variables and unsafe operations
    """
    workspace_path = workspace_path.resolve()
    backend = _try_tree_sitter_rust()
    max_bytes = int(os.getenv("TREE_SITTER_MAX_BYTES", "1048576"))

    # Cache file -> function boundaries
    file_cache: dict[str, tuple[list[str], list[_FuncBoundary]]] = {}

    def _get_file_info(file_rel: str) -> tuple[list[str], list[_FuncBoundary]]:
        if file_rel in file_cache:
            return file_cache[file_rel]
        full_path = workspace_path / file_rel
        if not full_path.exists():
            file_cache[file_rel] = ([], [])
            return [], []

        text = full_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        if backend is not None:
            raw = full_path.read_bytes()
            if len(raw) <= max_bytes:
                parser, _lang = backend
                boundaries = _find_function_boundaries_ast(raw, parser)
            else:
                boundaries = _find_function_boundaries_regex(lines)
        else:
            boundaries = _find_function_boundaries_regex(lines)

        file_cache[file_rel] = (lines, boundaries)
        return lines, boundaries

    slices: list[SliceInfo] = []
    seen_keys: set[tuple[str, int, int]] = set()  # dedup by (file, start, end)

    for hotspot in hotspots:
        lines, boundaries = _get_file_info(hotspot.file)
        if not lines:
            continue

        n_lines = len(lines)

        # Find enclosing function
        enclosing: _FuncBoundary | None = None
        for fb in boundaries:
            if fb.start_line <= hotspot.line_start and hotspot.line_end <= fb.end_line:
                enclosing = fb
                break

        if enclosing:
            slice_start = enclosing.start_line
            slice_end = enclosing.end_line
            anchor_line = hotspot.line_start
            symbol = enclosing.name
            signature_text = enclosing.signature_text
            signature_line = enclosing.signature_line

            # Build forbidden regions: the signature line itself
            forbidden_regions: list[dict[str, Any]] = []
            if enclosing.is_pub or True:  # Always protect signatures
                forbidden_regions.append({
                    "start": enclosing.signature_line,
                    "end": enclosing.signature_line,
                    "reason": "function_signature",
                })

            # Extract related info from slice range (0-based for array indexing)
            s0 = max(slice_start - 1, 0)
            e0 = min(slice_end, n_lines)
            related_vars = _extract_related_vars(lines, s0, e0)
            related_unsafe_ops = _extract_related_unsafe_ops(lines, s0, e0)

            content = "\n".join(lines[s0:e0])
        else:
            # No enclosing function — use hotspot with context
            slice_start = max(1, hotspot.line_start - context_lines)
            slice_end = min(n_lines, hotspot.line_end + context_lines)
            anchor_line = hotspot.line_start
            symbol = hotspot.symbol
            signature_text = None
            signature_line = None
            forbidden_regions = []

            s0 = max(slice_start - 1, 0)
            e0 = min(slice_end, n_lines)
            related_vars = _extract_related_vars(lines, s0, e0)
            related_unsafe_ops = _extract_related_unsafe_ops(lines, s0, e0)
            content = "\n".join(lines[s0:e0])

        # Dedup
        key = (hotspot.file, slice_start, slice_end)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        slices.append(SliceInfo(
            file=hotspot.file,
            start_line=slice_start,
            end_line=slice_end,
            anchor_line=anchor_line,
            symbol=symbol,
            content=content,
            signature_text=signature_text,
            signature_line=signature_line,
            keep_signature=True,
            no_global_rename=True,
            min_patch=True,
            forbidden_regions=forbidden_regions,
            related_vars=related_vars,
            related_unsafe_ops=related_unsafe_ops,
        ))

    return slices


def build_and_persist_slices(
    workspace_path: Path,
    hotspots: list[HotspotInfo],
    hotspot_ids: list[int],
    *,
    conn: Any,
    run_id: str | None = None,
) -> list[int]:
    """Build slices from hotspots and persist them to the database.

    Returns list of created slice IDs.
    Requires hotspot_ids to be aligned 1:1 with hotspots.
    """
    from packages.evidence.repository import create_slice

    slices = build_slices_for_hotspots(workspace_path, hotspots)

    # Map slices back to hotspot_ids via file+line overlap
    hotspot_lookup: list[tuple[HotspotInfo, int]] = list(zip(hotspots, hotspot_ids))

    slice_ids: list[int] = []
    for sl in slices:
        # Find best matching hotspot for this slice
        best_hid = hotspot_ids[0] if hotspot_ids else 0
        for h, hid in hotspot_lookup:
            if h.file == sl.file and sl.start_line <= h.line_start and h.line_end <= sl.end_line:
                best_hid = hid
                break

        sid = create_slice(
            conn,
            hotspot_id=best_hid,
            run_id=run_id,
            file_path=sl.file,
            symbol=sl.symbol,
            slice_start=sl.start_line,
            slice_end=sl.end_line,
            anchor_line=sl.anchor_line,
            signature_text=sl.signature_text,
            signature_line=sl.signature_line,
            content=sl.content,
            keep_signature=sl.keep_signature,
            no_global_rename=sl.no_global_rename,
            min_patch=sl.min_patch,
            forbidden_regions=sl.forbidden_regions,
            related_vars=sl.related_vars,
            related_unsafe_ops=sl.related_unsafe_ops,
        )
        slice_ids.append(sid)
    return slice_ids
