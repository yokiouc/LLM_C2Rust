from pathlib import Path

import pytest

from ingest import treesitter_chunker


def test_chunk_forced_fallback_window(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_TREE_SITTER", "1")
    monkeypatch.setenv("FALLBACK_WINDOW_LINES", "2")
    monkeypatch.setenv("RUST_WORKSPACE_ROOT", str(tmp_path))

    p = tmp_path / "src" / "lib.rs"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8", newline="\n")

    out = treesitter_chunker.chunk(p)
    assert len(out) == 2
    assert all(x.degraded for x in out)
    assert all(x.degrade_reason for x in out)
    assert out[0].file_rel == "src/lib.rs"


def test_chunk_huge_file_degrades(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SKIP_TREE_SITTER", raising=False)
    monkeypatch.setenv("FALLBACK_WINDOW_LINES", "50")
    monkeypatch.setenv("RUST_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("TREE_SITTER_MAX_BYTES", "10")

    p = tmp_path / "src" / "big.rs"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("fn f() {}\n" * 200, encoding="utf-8", newline="\n")

    out = treesitter_chunker.chunk(p)
    assert out
    assert all(x.degraded for x in out)

    backend = treesitter_chunker._try_tree_sitter_rust()
    if backend is None:
        assert any(x.degrade_reason == "tree_sitter_unavailable" for x in out)
    else:
        assert any(x.degrade_reason == "file_too_large" for x in out)


def test_chunk_invalid_syntax_degrades_when_tree_sitter_available(tmp_path: Path, monkeypatch):
    backend = treesitter_chunker._try_tree_sitter_rust()
    if backend is None:
        pytest.skip("tree-sitter backend not available")

    monkeypatch.delenv("SKIP_TREE_SITTER", raising=False)
    monkeypatch.setenv("FALLBACK_WINDOW_LINES", "50")
    monkeypatch.setenv("RUST_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("TREE_SITTER_MAX_BYTES", str(1024 * 1024))

    p = tmp_path / "src" / "bad.rs"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("fn f( { \n", encoding="utf-8", newline="\n")

    out = treesitter_chunker.chunk(p)
    assert out
    assert all(x.degraded for x in out)
    assert any(x.degrade_reason == "tree_sitter_error_nodes" for x in out)
