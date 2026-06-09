from pathlib import Path

from packages.repair.import_cleanup import (
    cleanup_clippy_diagnostics_from_diagnostics,
    cleanup_unused_imports_and_validate,
    cleanup_unused_imports_from_diagnostics,
    find_unused_import_diagnostics,
)
from packages.repair.patch_validator import validate_patch_constraints


UNUSED_PTR = """error: unused import: `std::ptr`
 --> src\\lib.rs:1:5
  |
1 | use std::ptr;
  |     ^^^^^^^^
  |
  = note: `-D unused-imports` implied by `-D warnings`
"""

UNUSED_BASE = """error: unused variable: `base`
 --> src\\lib.rs:3:9
  |
3 |     let base = bytes.as_ptr();
  |         ^^^^ help: if this is intentional, prefix it with an underscore: `_base`
"""

UNNECESSARY_MUT = """error: variable does not need to be mutable
 --> src\\lib.rs:2:9
  |
2 |     let mut total = 0_u32;
  |         ----^^^^^
"""

UNNECESSARY_UNSAFE = """error: unnecessary `unsafe` block
 --> src\\lib.rs:2:16
  |
2 |     let byte = unsafe { bytes[0] };
  |                ^^^^^^ unnecessary `unsafe` block
"""


def write_lib(tmp_path: Path, first_line: str = "use std::ptr;") -> Path:
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.rs").write_text(
        "\n".join(
            [
                first_line,
                "",
                "pub fn copy_prefix(src: &[u8], dst: &mut [u8], count: usize) -> bool {",
                "    if count > src.len() || count > dst.len() {",
                "        return false;",
                "    }",
                "    dst[..count].copy_from_slice(&src[..count]);",
                "    true",
                "}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return ws


def test_clippy_unused_import_diagnostic_locates_single_use():
    findings = find_unused_import_diagnostics(UNUSED_PTR, target_file="src/lib.rs")

    assert findings == [{"file": "src/lib.rs", "line": 1, "column": 5, "import": "std::ptr"}]


def test_cleanup_deletes_only_reported_import_line(tmp_path):
    ws = write_lib(tmp_path)

    result = cleanup_unused_imports_from_diagnostics(
        workspace_path=ws,
        target_file="src/lib.rs",
        diagnostics=UNUSED_PTR,
    )

    assert result.ok is True
    assert result.changed is True
    assert "-use std::ptr;" in result.diff
    text = (ws / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "use std::ptr;" not in text
    assert "pub fn copy_prefix" in text


def test_cleanup_does_not_delete_pub_use(tmp_path):
    ws = write_lib(tmp_path, "pub use std::ptr;")

    result = cleanup_unused_imports_from_diagnostics(
        workspace_path=ws,
        target_file="src/lib.rs",
        diagnostics=UNUSED_PTR,
    )

    assert result.ok is False
    assert result.error == "unsupported_import_cleanup"
    assert "pub use std::ptr;" in (ws / "src" / "lib.rs").read_text(encoding="utf-8")


def test_cleanup_does_not_handle_group_import(tmp_path):
    ws = write_lib(tmp_path, "use std::{ptr, mem};")

    result = cleanup_unused_imports_from_diagnostics(
        workspace_path=ws,
        target_file="src/lib.rs",
        diagnostics=UNUSED_PTR,
    )

    assert result.ok is False
    assert result.error == "unsupported_import_cleanup"
    assert "use std::{ptr, mem};" in (ws / "src" / "lib.rs").read_text(encoding="utf-8")


def test_non_unused_import_diagnostic_does_not_trigger_cleanup(tmp_path):
    ws = write_lib(tmp_path)

    result = cleanup_unused_imports_from_diagnostics(
        workspace_path=ws,
        target_file="src/lib.rs",
        diagnostics="error[E0425]: cannot find value `x` in this scope\n --> src\\lib.rs:1:1\n",
    )

    assert result.ok is True
    assert result.changed is False
    assert "use std::ptr;" in (ws / "src" / "lib.rs").read_text(encoding="utf-8")


def test_cleanup_reruns_build_test_lint(monkeypatch, tmp_path):
    ws = write_lib(tmp_path)
    calls = []

    class Result:
        def __init__(self, phase: str) -> None:
            self.phase = phase
            self.ok = True
            self.exit_code = 0
            self.duration_ms = 1
            self.stdout = ""
            self.stderr = ""
            self.log_path = ""
            self.parsed_issues = []
            self.issue_count = 0

    def fake_run_validation_phase(*, stage, workspace_path, env=None, timeout=120):
        calls.append(stage)
        return Result(stage)

    monkeypatch.setattr("packages.runner.validator.run_validation_phase", fake_run_validation_phase)

    result = cleanup_unused_imports_and_validate(
        workspace_path=ws,
        target_file="src/lib.rs",
        diagnostics=UNUSED_PTR,
        env={"RUNNER_MODE": "real"},
        timeout=10,
    )

    assert result.ok is True
    assert calls == ["build", "test", "clippy"]


def test_cleanup_does_not_affect_main_validator_outside_boundary_rejection():
    diff = """--- a/src/lib.rs
+++ b/src/lib.rs
@@ -1,1 +1,0 @@
-use std::ptr;
"""

    ok, violation = validate_patch_constraints(
        diff=diff,
        target_file="src/lib.rs",
        signature_text="pub fn copy_prefix(src: &[u8], dst: &mut [u8], count: usize) -> bool {",
        boundary={"start_line": 3, "end_line": 13},
    )

    assert ok is False
    assert violation["code"] == "outside_boundary"


def test_cleanup_unused_variable_removes_low_risk_as_ptr_binding(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.rs").write_text(
        "pub fn demo(bytes: &[u8]) -> usize {\n"
        "    let total = bytes.len();\n"
        "    let base = bytes.as_ptr();\n"
        "    total\n"
        "}\n",
        encoding="utf-8",
    )

    result = cleanup_clippy_diagnostics_from_diagnostics(
        workspace_path=ws,
        target_file="src/lib.rs",
        diagnostics=UNUSED_BASE,
    )

    assert result.ok is True
    assert result.changed is True
    assert "let base" not in (ws / "src" / "lib.rs").read_text(encoding="utf-8")


def test_cleanup_unnecessary_mut_removes_only_mut_keyword(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.rs").write_text(
        "pub fn demo() -> u32 {\n"
        "    let mut total = 0_u32;\n"
        "    total\n"
        "}\n",
        encoding="utf-8",
    )

    result = cleanup_clippy_diagnostics_from_diagnostics(
        workspace_path=ws,
        target_file="src/lib.rs",
        diagnostics=UNNECESSARY_MUT,
    )

    assert result.ok is True
    assert "let total = 0_u32;" in (ws / "src" / "lib.rs").read_text(encoding="utf-8")


def test_cleanup_unnecessary_unsafe_single_line(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.rs").write_text(
        "pub fn demo(bytes: &[u8]) -> u8 {\n"
        "    let byte = unsafe { bytes[0] };\n"
        "    byte\n"
        "}\n",
        encoding="utf-8",
    )

    result = cleanup_clippy_diagnostics_from_diagnostics(
        workspace_path=ws,
        target_file="src/lib.rs",
        diagnostics=UNNECESSARY_UNSAFE,
    )

    assert result.ok is True
    assert "let byte = bytes[0];" in (ws / "src" / "lib.rs").read_text(encoding="utf-8")


def test_cleanup_validation_failure_rolls_back(monkeypatch, tmp_path):
    ws = write_lib(tmp_path)

    class Result:
        def __init__(self, ok: bool, phase: str) -> None:
            self.phase = phase
            self.ok = ok
            self.exit_code = 0 if ok else 1
            self.duration_ms = 1
            self.stdout = ""
            self.stderr = "failed"
            self.log_path = ""
            self.parsed_issues = []
            self.issue_count = 0 if ok else 1

    def fake_run_validation_phase(*, stage, workspace_path, env=None, timeout=120):
        return Result(stage != "test", stage)

    monkeypatch.setattr("packages.runner.validator.run_validation_phase", fake_run_validation_phase)

    result = cleanup_unused_imports_and_validate(
        workspace_path=ws,
        target_file="src/lib.rs",
        diagnostics=UNUSED_PTR,
    )

    assert result.ok is False
    assert result.error == "test_failed"
    assert "use std::ptr;" in (ws / "src" / "lib.rs").read_text(encoding="utf-8")
