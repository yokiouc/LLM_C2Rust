import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FunctionSlice:
    name: str | None
    file_rel: str
    start_row: int
    start_col: int
    end_row: int
    end_col: int
    content: str
    degraded: bool
    degrade_reason: str | None


def _read_bytes(p: Path) -> bytes:
    return p.read_bytes()


def _fallback_window(*, rs_file: Path, file_rel: str, window_lines: int, reason: str) -> list[FunctionSlice]:
    txt = rs_file.read_text(encoding="utf-8", errors="replace")
    lines = txt.splitlines(keepends=True)
    out: list[FunctionSlice] = []
    n = max(int(window_lines), 1)
    for i in range(0, len(lines), n):
        chunk = "".join(lines[i : i + n])
        if not chunk.strip():
            continue
        start_row = i
        end_row = min(i + n, len(lines))
        out.append(
            FunctionSlice(
                name=None,
                file_rel=file_rel,
                start_row=start_row,
                start_col=0,
                end_row=end_row,
                end_col=0,
                content=chunk,
                degraded=True,
                degrade_reason=reason,
            )
        )
    return out


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


def _has_error_node(node: Any) -> bool:
    if getattr(node, "type", "") == "ERROR":
        return True
    for i in range(int(getattr(node, "child_count", 0))):
        if _has_error_node(node.child(i)):
            return True
    return False


def _extract_functions(*, rs_file: Path, file_rel: str, window_lines: int) -> list[FunctionSlice]:
    backend = _try_tree_sitter_rust()
    if backend is None:
        return _fallback_window(rs_file=rs_file, file_rel=file_rel, window_lines=window_lines, reason="tree_sitter_unavailable")

    max_bytes = int(os.getenv("TREE_SITTER_MAX_BYTES", "1048576"))
    raw = _read_bytes(rs_file)
    if len(raw) > max_bytes:
        return _fallback_window(rs_file=rs_file, file_rel=file_rel, window_lines=window_lines, reason="file_too_large")

    parser, _lang = backend
    tree = parser.parse(raw)
    root = tree.root_node
    if _has_error_node(root):
        return _fallback_window(rs_file=rs_file, file_rel=file_rel, window_lines=window_lines, reason="tree_sitter_error_nodes")

    out: list[FunctionSlice] = []

    def walk(node: Any) -> None:
        if node.type == "function_item":
            name_node = node.child_by_field_name("name")
            name = None
            if name_node is not None:
                name = raw[name_node.start_byte : name_node.end_byte].decode("utf-8", errors="replace")
            content = raw[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
            (sr, sc) = node.start_point
            (er, ec) = node.end_point
            out.append(
                FunctionSlice(
                    name=name,
                    file_rel=file_rel,
                    start_row=int(sr),
                    start_col=int(sc),
                    end_row=int(er),
                    end_col=int(ec),
                    content=content,
                    degraded=False,
                    degrade_reason=None,
                )
            )
            return
        for i in range(node.child_count):
            walk(node.child(i))

    walk(root)
    if not out:
        return _fallback_window(rs_file=rs_file, file_rel=file_rel, window_lines=window_lines, reason="no_functions_found")
    return out


def chunk(rs_file: Path) -> list[FunctionSlice]:
    rs_file = rs_file.resolve()
    window_lines = int(os.getenv("FALLBACK_WINDOW_LINES", "50"))
    root_override = os.getenv("RUST_WORKSPACE_ROOT", "").strip()
    root = Path(root_override).resolve() if root_override else None
    if root is None:
        cur = rs_file.parent
        for _ in range(10):
            if (cur / "Cargo.toml").exists():
                root = cur
                break
            if cur.parent == cur:
                break
            cur = cur.parent
    if root is not None:
        try:
            file_rel = rs_file.relative_to(root).as_posix()
        except Exception:
            file_rel = rs_file.name
    else:
        file_rel = rs_file.name
    if os.getenv("SKIP_TREE_SITTER", "").strip().lower() in {"1", "true", "yes"}:
        return _fallback_window(rs_file=rs_file, file_rel=file_rel, window_lines=window_lines, reason="skip_tree_sitter")
    return _extract_functions(rs_file=rs_file, file_rel=file_rel, window_lines=window_lines)
