"""Hotspot discovery: identifies high-risk unsafe code locations.

Uses a two-layer approach:
  1. Tree-sitter AST analysis (when available) for structural detection
  2. Regex-based rules as fallback and supplement

Each hotspot is scored and classified by kind, with risk_tags for downstream use.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packages.core.constants import HotspotKind, RISK_WEIGHTS
from packages.core.types import HotspotInfo


# ---------------------------------------------------------------------------
# Regex patterns for fallback / supplement detection
# ---------------------------------------------------------------------------

_RE_UNSAFE_BLOCK = re.compile(r"\bunsafe\s*\{")
_RE_UNSAFE_FN = re.compile(r"\b(pub\s+)?(unsafe\s+fn)\s+(\w+)")
_RE_RAW_PTR_DEREF = re.compile(r"\*(?:const|mut)\s+\w+|as\s+\*(?:const|mut)")
_RE_PTR_ARITH = re.compile(r"\.(add|sub|offset|wrapping_add|wrapping_sub|wrapping_offset)\s*\(")
_RE_MANUAL_MEM = re.compile(r"\b(malloc|calloc|realloc|free|alloc::alloc|alloc::dealloc)\b")
_RE_MEMCPY = re.compile(r"\b(memcpy|memmove|memset|ptr::copy|ptr::copy_nonoverlapping|ptr::write|ptr::read)\b")
_RE_EXTERN_CALL = re.compile(r'\bextern\s+"C"\s*\{')
_RE_CROSS_FUNC_RESOURCE = re.compile(
    r"\b(Box::into_raw|Box::from_raw|ManuallyDrop|forget|transmute|from_raw_parts)\b"
)

# Map from regex pattern to (hotspot_kind, primary_risk_tag)
_REGEX_RULES: list[tuple[re.Pattern, HotspotKind, str]] = [
    (_RE_UNSAFE_BLOCK,          HotspotKind.UNSAFE_BLOCK,       "unsafe"),
    (_RE_UNSAFE_FN,             HotspotKind.UNSAFE_FN_DECL,     "unsafe_fn"),
    (_RE_RAW_PTR_DEREF,         HotspotKind.RAW_PTR_DEREF,      "raw_ptr"),
    (_RE_PTR_ARITH,             HotspotKind.PTR_ARITHMETIC,      "ptr_arith"),
    (_RE_MANUAL_MEM,            HotspotKind.MANUAL_MEM_API,      "manual_mem"),
    (_RE_MEMCPY,                HotspotKind.MEMCPY_MEMMOVE,      "memcpy_memmove"),
    (_RE_EXTERN_CALL,           HotspotKind.EXTERN_CALL,         "extern_call"),
    (_RE_CROSS_FUNC_RESOURCE,   HotspotKind.CROSS_FUNC_RESOURCE, "cross_func_resource"),
]


# ---------------------------------------------------------------------------
# Tree-sitter integration
# ---------------------------------------------------------------------------

def _try_tree_sitter_rust() -> tuple[Any, Any] | None:
    """Try to load tree-sitter Rust parser. Returns (parser, language) or None."""
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


@dataclass
class _ASTHotspot:
    """Internal intermediate hotspot from AST analysis."""
    kind: HotspotKind
    start_line: int  # 1-based
    end_line: int    # 1-based
    symbol: str | None = None
    risk_tags: list[str] = field(default_factory=list)
    unsafe_count: int = 0
    raw_ptr_count: int = 0
    content: str = ""


def _walk_ast_for_hotspots(node: Any, raw: bytes, results: list[_ASTHotspot]) -> None:
    """Recursively walk AST to find hotspot-bearing nodes."""
    ntype = getattr(node, "type", "")

    # unsafe block: unsafe { ... }
    if ntype == "unsafe_block":
        sr = node.start_point[0] + 1
        er = node.end_point[0] + 1
        content = raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        # Count sub-risks within the unsafe block
        unsafe_count = 1
        raw_ptr_count = len(_RE_RAW_PTR_DEREF.findall(content))
        tags = ["unsafe"]
        if raw_ptr_count > 0:
            tags.append("raw_ptr")
        if _RE_PTR_ARITH.search(content):
            tags.append("ptr_arith")
        if _RE_MANUAL_MEM.search(content):
            tags.append("manual_mem")
        if _RE_MEMCPY.search(content):
            tags.append("memcpy_memmove")

        # Find enclosing function name
        symbol = _find_enclosing_fn_name(node, raw)

        results.append(_ASTHotspot(
            kind=HotspotKind.UNSAFE_BLOCK,
            start_line=sr, end_line=er,
            symbol=symbol,
            risk_tags=tags,
            unsafe_count=unsafe_count,
            raw_ptr_count=raw_ptr_count,
            content=content,
        ))
        return  # Don't recurse into children — already captured

    # function_item with "unsafe" qualifier
    if ntype == "function_item":
        # Check for unsafe fn
        content = raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        if _RE_UNSAFE_FN.search(content.split("{")[0] if "{" in content else content):
            name_node = node.child_by_field_name("name")
            symbol = raw[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace") if name_node else None
            sr = node.start_point[0] + 1
            er = node.end_point[0] + 1
            raw_ptr_count = len(_RE_RAW_PTR_DEREF.findall(content))
            tags = ["unsafe_fn"]
            if raw_ptr_count > 0:
                tags.append("raw_ptr")
            results.append(_ASTHotspot(
                kind=HotspotKind.UNSAFE_FN_DECL,
                start_line=sr, end_line=er,
                symbol=symbol,
                risk_tags=tags,
                unsafe_count=1,
                raw_ptr_count=raw_ptr_count,
                content=content,
            ))
            # Still recurse — unsafe fn may contain unsafe blocks
        # Also check for cross-function resource patterns inside any fn
        if _RE_CROSS_FUNC_RESOURCE.search(content):
            name_node = node.child_by_field_name("name")
            symbol = raw[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace") if name_node else None
            sr = node.start_point[0] + 1
            er = node.end_point[0] + 1
            results.append(_ASTHotspot(
                kind=HotspotKind.CROSS_FUNC_RESOURCE,
                start_line=sr, end_line=er,
                symbol=symbol,
                risk_tags=["cross_func_resource"],
                content=content,
            ))

    # extern "C" block
    if ntype == "extern_block":
        sr = node.start_point[0] + 1
        er = node.end_point[0] + 1
        content = raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        results.append(_ASTHotspot(
            kind=HotspotKind.EXTERN_CALL,
            start_line=sr, end_line=er,
            risk_tags=["extern_call"],
            content=content,
        ))

    # Recurse
    for i in range(getattr(node, "child_count", 0)):
        _walk_ast_for_hotspots(node.child(i), raw, results)


def _find_enclosing_fn_name(node: Any, raw: bytes) -> str | None:
    """Walk up the AST to find the enclosing function name."""
    cur = getattr(node, "parent", None)
    while cur is not None:
        if getattr(cur, "type", "") == "function_item":
            name_node = cur.child_by_field_name("name")
            if name_node is not None:
                return raw[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
            return None
        cur = getattr(cur, "parent", None)
    return None


# ---------------------------------------------------------------------------
# Regex-based fallback hotspot detection
# ---------------------------------------------------------------------------

def _regex_scan_file(file_path: Path, file_rel: str) -> list[_ASTHotspot]:
    """Scan file using regex patterns when tree-sitter is unavailable."""
    text = file_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    results: list[_ASTHotspot] = []

    for line_idx, line in enumerate(lines):
        line_no = line_idx + 1
        for pattern, kind, tag in _REGEX_RULES:
            if pattern.search(line):
                # Determine a reasonable end_line (extend to closing brace or +5)
                end_line = min(line_no + 5, len(lines))
                # Try to find matching brace for blocks
                if kind in (HotspotKind.UNSAFE_BLOCK, HotspotKind.UNSAFE_FN_DECL, HotspotKind.EXTERN_CALL):
                    brace_depth = 0
                    for j in range(line_idx, min(line_idx + 100, len(lines))):
                        brace_depth += lines[j].count("{") - lines[j].count("}")
                        if brace_depth <= 0 and j > line_idx:
                            end_line = j + 1
                            break

                content_lines = lines[line_idx:end_line]
                content = "\n".join(content_lines)
                raw_ptr_count = len(_RE_RAW_PTR_DEREF.findall(content))
                unsafe_count = len(_RE_UNSAFE_BLOCK.findall(content))

                tags = [tag]
                if raw_ptr_count > 0 and "raw_ptr" not in tags:
                    tags.append("raw_ptr")
                if _RE_PTR_ARITH.search(content) and "ptr_arith" not in tags:
                    tags.append("ptr_arith")
                if _RE_MANUAL_MEM.search(content) and "manual_mem" not in tags:
                    tags.append("manual_mem")

                results.append(_ASTHotspot(
                    kind=kind,
                    start_line=line_no,
                    end_line=end_line,
                    risk_tags=tags,
                    unsafe_count=max(unsafe_count, 1) if kind == HotspotKind.UNSAFE_BLOCK else unsafe_count,
                    raw_ptr_count=raw_ptr_count,
                    content=content,
                ))

    return results


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _compute_risk_score(tags: list[str]) -> float:
    """Compute risk score from risk tags using RISK_WEIGHTS."""
    score = 0.0
    for tag in tags:
        score += RISK_WEIGHTS.get(tag, 0)
    return score


def _classify_risk_level(score: float) -> str:
    """Classify risk score into low/medium/high."""
    if score >= 5:
        return "high"
    elif score >= 3:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _deduplicate_hotspots(hotspots: list[_ASTHotspot]) -> list[_ASTHotspot]:
    """Deduplicate hotspots that overlap in the same file region."""
    if not hotspots:
        return []

    # Sort by start_line, then by higher priority kinds first
    kind_priority = {
        HotspotKind.UNSAFE_BLOCK: 0,
        HotspotKind.UNSAFE_FN_DECL: 1,
        HotspotKind.MANUAL_MEM_API: 2,
        HotspotKind.MEMCPY_MEMMOVE: 3,
        HotspotKind.RAW_PTR_DEREF: 4,
        HotspotKind.PTR_ARITHMETIC: 5,
        HotspotKind.CROSS_FUNC_RESOURCE: 6,
        HotspotKind.EXTERN_CALL: 7,
    }
    hotspots.sort(key=lambda h: (h.start_line, kind_priority.get(h.kind, 99)))

    result: list[_ASTHotspot] = []
    seen_ranges: set[tuple[int, int, str]] = set()
    for h in hotspots:
        key = (h.start_line, h.end_line, h.kind.value)
        if key not in seen_ranges:
            seen_ranges.add(key)
            result.append(h)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def discover_hotspots(
    workspace_path: Path,
    *,
    file_filter: str = "**/*.rs",
) -> list[HotspotInfo]:
    """Discover unsafe hotspots in a Rust workspace.

    Uses tree-sitter AST when available, falls back to regex scanning.
    Returns a list of HotspotInfo sorted by risk_score descending.
    """
    workspace_path = workspace_path.resolve()
    rs_files = sorted(workspace_path.glob(file_filter), key=lambda p: p.as_posix().lower())

    if not rs_files:
        return []

    backend = _try_tree_sitter_rust()
    max_bytes = int(os.getenv("TREE_SITTER_MAX_BYTES", "1048576"))

    all_raw: list[tuple[str, list[_ASTHotspot]]] = []

    for rs_file in rs_files:
        try:
            file_rel = rs_file.relative_to(workspace_path).as_posix()
        except ValueError:
            file_rel = rs_file.name

        raw_hotspots: list[_ASTHotspot] = []

        if backend is not None:
            raw_bytes = rs_file.read_bytes()
            if len(raw_bytes) <= max_bytes:
                parser, _lang = backend
                tree = parser.parse(raw_bytes)
                _walk_ast_for_hotspots(tree.root_node, raw_bytes, raw_hotspots)
            else:
                raw_hotspots = _regex_scan_file(rs_file, file_rel)
        else:
            raw_hotspots = _regex_scan_file(rs_file, file_rel)

        # Supplement: regex patterns that AST may miss (ptr arith, memcpy inside safe code)
        if backend is not None:
            text = rs_file.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            ast_covered_lines: set[int] = set()
            for h in raw_hotspots:
                for ln in range(h.start_line, h.end_line + 1):
                    ast_covered_lines.add(ln)

            for line_idx, line in enumerate(lines):
                line_no = line_idx + 1
                if line_no in ast_covered_lines:
                    continue
                for pattern, kind, tag in _REGEX_RULES:
                    # Only supplement non-block patterns (ptr arith, memcpy, manual mem)
                    if kind in (HotspotKind.UNSAFE_BLOCK, HotspotKind.UNSAFE_FN_DECL, HotspotKind.EXTERN_CALL):
                        continue
                    if pattern.search(line):
                        raw_hotspots.append(_ASTHotspot(
                            kind=kind,
                            start_line=line_no,
                            end_line=min(line_no + 3, len(lines)),
                            risk_tags=[tag],
                            content=line,
                        ))

        all_raw.append((file_rel, raw_hotspots))

    # Build HotspotInfo list
    result: list[HotspotInfo] = []
    for file_rel, raw_hotspots in all_raw:
        deduped = _deduplicate_hotspots(raw_hotspots)
        for h in deduped:
            score = _compute_risk_score(h.risk_tags)
            level = _classify_risk_level(score)
            result.append(HotspotInfo(
                file=file_rel,
                symbol=h.symbol,
                line_start=h.start_line,
                line_end=h.end_line,
                hotspot_kind=h.kind.value,
                risk_score=int(score),
                risk_tags=h.risk_tags,
                content=h.content,
                supporting_evidence=[],
            ))

    # Sort by risk score descending
    result.sort(key=lambda h: (-h.risk_score, h.file, h.line_start))
    return result


def discover_and_persist_hotspots(
    workspace_path: Path,
    *,
    conn: Any,
    run_id: str | None = None,
    snapshot_id: int | None = None,
) -> list[int]:
    """Discover hotspots and persist them to the database.

    Returns list of created hotspot IDs.
    """
    from packages.evidence.repository import create_hotspot

    hotspots = discover_hotspots(workspace_path)
    ids: list[int] = []
    for h in hotspots:
        hid = create_hotspot(
            conn,
            run_id=run_id,
            snapshot_id=snapshot_id,
            file_path=h.file,
            symbol=h.symbol,
            start_line=h.line_start,
            end_line=h.line_end,
            hotspot_kind=h.hotspot_kind,
            risk_score=h.risk_score,
            risk_level=_classify_risk_level(h.risk_score),
            risk_tags=h.risk_tags,
            unsafe_count=len([t for t in h.risk_tags if t == "unsafe"]),
            raw_ptr_count=len([t for t in h.risk_tags if t == "raw_ptr"]),
            content=h.content,
        )
        ids.append(hid)
    return ids
