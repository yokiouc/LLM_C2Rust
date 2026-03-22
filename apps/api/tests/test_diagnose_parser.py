import gzip
import json
import time
from pathlib import Path

from diagnose.parser import parse_diagnostics


def test_parse_rust_error_with_code():
    text = "src/lib.rs:10:5 E0425: cannot find value `x` in this scope\n"
    issues = parse_diagnostics(text)
    assert issues[0]["file"] == "src/lib.rs"
    assert issues[0]["line"] == 10
    assert issues[0]["error_code"] == "E0425"
    assert "cannot find value" in issues[0]["summary"]


def test_parse_rust_error_without_code():
    text = "src/main.rs:1:1: expected one of `!`, `.`, `::`, `;`, `?`, `{`, or an operator\n"
    issues = parse_diagnostics(text)
    assert issues[0]["file"] == "src/main.rs"
    assert issues[0]["line"] == 1
    assert issues[0]["error_code"] is None
    assert "expected one of" in issues[0]["summary"]


def test_parse_clippy_warning():
    text = "src/lib.rs:12:1 warning: you should consider using `clippy::foo`\n"
    issues = parse_diagnostics(text)
    assert issues[0]["file"] == "src/lib.rs"
    assert issues[0]["line"] == 12
    assert issues[0]["error_code"] == "warning"


def test_parse_test_failure_like_line():
    text = "src/lib.rs:3:5: assertion `left == right` failed\n"
    issues = parse_diagnostics(text)
    assert issues[0]["file"] == "src/lib.rs"
    assert issues[0]["line"] == 3
    assert issues[0]["error_code"] is None
    assert "assertion" in issues[0]["summary"]


def test_parse_unmatched_line_keeps_summary():
    text = "error: could not compile `demo` (lib) due to 1 previous error\n"
    issues = parse_diagnostics(text)
    assert issues[0]["file"] is None
    assert issues[0]["line"] is None
    assert issues[0]["error_code"] is None
    assert issues[0]["summary"] == text.strip()


def test_parse_runner_gz_log_extracts_stderr(tmp_path: Path):
    payload = {"stdout": "", "stderr": "src/lib.rs:2:1: E0001: bad\nunmatched line\n"}
    p = tmp_path / "r.log.gz"
    with gzip.open(p, "wb") as f:
        f.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    issues = parse_diagnostics(p)
    assert len(issues) == 2
    assert issues[0]["file"] == "src/lib.rs"
    assert issues[0]["line"] == 2
    assert issues[1]["summary"] == "unmatched line"


def test_parse_1mib_under_200ms():
    line = "src/lib.rs:1:1: E0001: bad\n"
    n = (1024 * 1024) // len(line) + 1
    text = line * n
    t0 = time.perf_counter()
    issues = parse_diagnostics(text)
    dt = time.perf_counter() - t0
    assert issues
    assert dt <= 0.2

