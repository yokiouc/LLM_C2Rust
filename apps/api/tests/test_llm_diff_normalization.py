import json

from packages.repair.patch_engine import apply_patch
from packages.repair.generator import (
    LLMProvider,
    build_replacement_block_diff,
    generate_controlled_patch,
    get_last_generation_info,
    normalize_llm_unified_diff,
)
from packages.repair.llm_provider import TemplateEditProvider
from packages.repair.patch_validator import validate_patch_constraints


class StaticProvider(LLMProvider):
    def __init__(self, text: str) -> None:
        self.text = text

    def generate(self, prompt: str) -> str:
        return self.text


def test_fenced_diff_is_unwrapped():
    raw = """```diff
--- a/src/lib.rs
+++ b/src/lib.rs
@@ -3,1 +3,1 @@
-    unsafe { Some(*ptr) }
+    values.first().copied()
```"""

    result = normalize_llm_unified_diff(raw, "src/lib.rs")

    assert result.error is None
    assert result.raw_output_had_code_fence is True
    assert result.diff.startswith("--- a/src/lib.rs\n+++ b/src/lib.rs\n")
    assert "```" not in result.diff


def test_plain_relative_headers_are_standardized_to_ab_paths():
    raw = """--- src/lib.rs
+++ src/lib.rs
@@ -3,1 +3,1 @@
-    unsafe { Some(*ptr) }
+    values.first().copied()
"""

    result = normalize_llm_unified_diff(raw, "src/lib.rs")

    assert result.error is None
    assert result.normalized_diff is True
    assert result.diff.startswith("--- a/src/lib.rs\n+++ b/src/lib.rs\n")


def test_explanation_before_diff_is_removed():
    raw = """Here is the patch:
--- src/lib.rs
+++ src/lib.rs
@@ -3,1 +3,1 @@
-    unsafe { Some(*ptr) }
+    values.first().copied()
Done."""

    result = normalize_llm_unified_diff(raw, "src/lib.rs")

    assert result.error is None
    assert result.diff == """--- a/src/lib.rs
+++ b/src/lib.rs
@@ -3,1 +3,1 @@
-    unsafe { Some(*ptr) }
+    values.first().copied()
"""


def test_missing_hunk_is_rejected_with_openai_invalid_diff():
    raw = """--- src/lib.rs
+++ src/lib.rs
-old
+new
"""

    result = normalize_llm_unified_diff(raw, "src/lib.rs")

    assert result.error == "openai_invalid_diff"
    assert result.diff == ""


def test_other_file_path_is_rejected():
    raw = """--- src/other.rs
+++ src/other.rs
@@ -1,1 +1,1 @@
-old
+new
"""

    result = normalize_llm_unified_diff(raw, "src/lib.rs")

    assert result.error == "openai_invalid_diff"
    assert result.diff == ""


def test_normalized_diff_still_goes_through_strict_validator():
    raw = """--- src/lib.rs
+++ src/lib.rs
@@ -50,1 +50,1 @@
-    unsafe { Some(*ptr) }
+    values.first().copied()
"""

    result = normalize_llm_unified_diff(raw, "src/lib.rs")
    assert result.error is None

    ok, violation = validate_patch_constraints(
        diff=result.diff,
        target_file="src/lib.rs",
        signature_text=None,
        boundary={"start_line": 1, "end_line": 10},
    )

    assert ok is False
    assert violation["code"] == "outside_boundary"


def test_generate_controlled_patch_records_invalid_openai_diff():
    diff = generate_controlled_patch(
        evidence='{"file":"src/lib.rs","slice":"line1"}',
        target_function="src/lib.rs",
        provider=StaticProvider("```diff\n--- src/lib.rs\n+++ src/lib.rs\n-old\n+new\n```"),
    )

    assert diff == ""
    assert get_last_generation_info()["error"] == "openai_invalid_diff"


def test_template_edit_provider_is_unchanged_by_normalization():
    evidence = {
        "recommended_boundary": {"file": "src/lib.rs", "start_line": 1, "end_line": 4},
        "items": [
            {
                "kind": "rust_function_slice",
                "excerpt": "\n".join(
                    [
                        "pub fn demo(values: &[i32]) -> Option<i32> {",
                        "    let ptr = values.as_ptr();",
                        "    unsafe { Some(*ptr) }",
                        "}",
                    ]
                ),
                "meta": {"file": "src/lib.rs"},
            }
        ],
    }

    diff = generate_controlled_patch(
        evidence=json.dumps(evidence),
        target_function="src/lib.rs",
        provider=TemplateEditProvider(),
    )

    assert diff.startswith("--- a/src/lib.rs\n+++ b/src/lib.rs\n")
    assert "+    values.first().copied()" in diff
    assert get_last_generation_info()["normalized_diff"] is False


def test_cf03_copy_nonoverlapping_exact_hunk_normalizes_and_validates():
    raw = """--- src/lib.rs
+++ src/lib.rs
@@ -9,3 +9,1 @@
-    unsafe {
-        ptr::copy_nonoverlapping(src.as_ptr(), dst.as_mut_ptr(), count);
-    }
+    dst[..count].copy_from_slice(&src[..count]);
"""

    result = normalize_llm_unified_diff(raw, "src/lib.rs")
    assert result.error is None

    ok, violation = validate_patch_constraints(
        diff=result.diff,
        target_file="src/lib.rs",
        signature_text="pub fn copy_prefix(src: &[u8], dst: &mut [u8], count: usize) -> bool {",
        boundary={"start_line": 3, "end_line": 13},
    )

    assert ok is True
    assert violation is None


def test_hunk_header_function_context_is_trimmed_for_apply_engine():
    raw = """--- src/lib.rs
+++ src/lib.rs
@@ -6,9 +6,9 @@ pub fn copy_prefix(src: &[u8], dst: &mut [u8], count: usize) -> bool {
-    unsafe {
-        ptr::copy_nonoverlapping(src.as_ptr(), dst.as_mut_ptr(), count);
-    }
+    dst[..count].copy_from_slice(&src[..count]);
"""

    result = normalize_llm_unified_diff(raw, "src/lib.rs")

    assert result.error is None
    assert "@@ -6,9 +6,9 @@\n" in result.diff
    assert "copy_prefix" not in result.diff.splitlines()[2]


def test_empty_context_line_in_hunk_is_normalized_for_apply_engine(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.rs").write_text(
        "\n".join(
            [
                "use std::ptr;",
                "",
                "pub fn copy_prefix(src: &[u8], dst: &mut [u8], count: usize) -> bool {",
                "    if count > src.len() || count > dst.len() {",
                "        return false;",
                "    }",
                "",
                "    // SAFETY: src and dst are valid for count bytes and come from distinct borrows.",
                "    unsafe {",
                "        ptr::copy_nonoverlapping(src.as_ptr(), dst.as_mut_ptr(), count);",
                "    }",
                "    true",
                "}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    raw = """--- src/lib.rs
+++ src/lib.rs
@@ -7,7 +7,5 @@ pub fn copy_prefix(src: &[u8], dst: &mut [u8], count: usize) -> bool {

     // SAFETY: src and dst are valid for count bytes and come from distinct borrows.
     unsafe {
-        ptr::copy_nonoverlapping(src.as_ptr(), dst.as_mut_ptr(), count);
+        dst[..count].copy_from_slice(&src[..count]);
     }
     true
"""

    result = normalize_llm_unified_diff(raw, "src/lib.rs")

    assert result.error is None
    assert "\n \n" in result.diff
    applied = apply_patch(ws, result.diff)
    assert applied.ok is True


def test_unrelated_marker_added_by_llm_is_rejected():
    raw = """--- a/src/lib.rs
+++ b/src/lib.rs
@@ -9,3 +9,2 @@
-    unsafe {
-        ptr::copy_nonoverlapping(src.as_ptr(), dst.as_mut_ptr(), count);
-    }
+    let _ptr_import_marker = ptr::addr_of!(count);
+    dst[..count].copy_from_slice(&src[..count]);
"""

    result = normalize_llm_unified_diff(raw, "src/lib.rs")

    assert result.error == "openai_invalid_diff"
    assert result.diff == ""


def test_old_hunk_mismatch_fails_apply(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.rs").write_text(
        "\n".join(
            [
                "use std::ptr;",
                "",
                "pub fn copy_prefix(src: &[u8], dst: &mut [u8], count: usize) -> bool {",
                "    if count > src.len() || count > dst.len() {",
                "        return false;",
                "    }",
                "",
                "    // SAFETY: src and dst are valid for count bytes and come from distinct borrows.",
                "    unsafe {",
                "        ptr::copy_nonoverlapping(src.as_ptr(), dst.as_mut_ptr(), count);",
                "    }",
                "    true",
                "}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    diff = """--- a/src/lib.rs
+++ b/src/lib.rs
@@ -9,3 +9,1 @@
-    unsafe {
-        ptr::copy_nonoverlapping(src.as_ptr(), dst.as_mut_ptr(), count)
-    }
+    dst[..count].copy_from_slice(&src[..count]);
"""

    result = apply_patch(ws, diff)

    assert result.ok is False
    assert result.error_msg == "remove_mismatch"


def test_cf03_copy_from_slice_patch_applies_after_normalize_and_validate(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.rs").write_text(
        "\n".join(
            [
                "use std::ptr;",
                "",
                "pub fn copy_prefix(src: &[u8], dst: &mut [u8], count: usize) -> bool {",
                "    if count > src.len() || count > dst.len() {",
                "        return false;",
                "    }",
                "",
                "    // SAFETY: src and dst are valid for count bytes and come from distinct borrows.",
                "    unsafe {",
                "        ptr::copy_nonoverlapping(src.as_ptr(), dst.as_mut_ptr(), count);",
                "    }",
                "    true",
                "}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    raw = """```diff
--- src/lib.rs
+++ src/lib.rs
@@ -9,3 +9,1 @@
-    unsafe {
-        ptr::copy_nonoverlapping(src.as_ptr(), dst.as_mut_ptr(), count);
-    }
+    dst[..count].copy_from_slice(&src[..count]);
```"""

    normalized = normalize_llm_unified_diff(raw, "src/lib.rs")
    assert normalized.error is None
    ok, violation = validate_patch_constraints(
        diff=normalized.diff,
        target_file="src/lib.rs",
        signature_text="pub fn copy_prefix(src: &[u8], dst: &mut [u8], count: usize) -> bool {",
        boundary={"start_line": 3, "end_line": 13},
    )
    assert ok is True
    assert violation is None

    applied = apply_patch(ws, normalized.diff)

    assert applied.ok is True
    assert "copy_from_slice" in (ws / "src" / "lib.rs").read_text(encoding="utf-8")


def test_cf03_outside_boundary_is_still_rejected():
    raw = """--- a/src/lib.rs
+++ b/src/lib.rs
@@ -1,1 +1,1 @@
-use std::ptr;
+use core::ptr;
"""

    result = normalize_llm_unified_diff(raw, "src/lib.rs")
    assert result.error is None
    ok, violation = validate_patch_constraints(
        diff=result.diff,
        target_file="src/lib.rs",
        signature_text="pub fn copy_prefix(src: &[u8], dst: &mut [u8], count: usize) -> bool {",
        boundary={"start_line": 3, "end_line": 13},
    )

    assert ok is False
    assert violation["code"] == "outside_boundary"


def test_replacement_block_constructs_unified_diff_from_exact_old_lines():
    evidence = {
        "repair_slice_context": {
            "signature_text": "pub fn checksum(buf: &[u8]) -> u32 {",
            "signature_line": 3,
            "exact_replacement_block": {
                "target_file": "src/lib.rs",
                "start_line": 5,
                "end_line": 9,
                "old_block": "\n".join(
                    [
                        "    let base = buf.as_ptr();",
                        "",
                        "    for i in 0..buf.len() {",
                        "        // SAFETY: bounded.",
                        "        let byte = unsafe { *base.add(i) };",
                    ]
                ),
            },
        }
    }

    result = build_replacement_block_diff(
        evidence=json.dumps(evidence),
        target_file="src/lib.rs",
        raw_replacement="    for &byte in buf {",
    )

    assert result.error is None
    assert result.diff.startswith("--- a/src/lib.rs\n+++ b/src/lib.rs\n@@ -5,5 +5,1 @@\n")
    assert "-    let base = buf.as_ptr();" in result.diff
    assert "+    for &byte in buf {" in result.diff


def test_replacement_block_aligns_unindented_replacement_to_old_block():
    evidence = {
        "repair_slice_context": {
            "exact_replacement_block": {
                "target_file": "src/lib.rs",
                "start_line": 10,
                "end_line": 12,
                "old_block": "    unsafe {\n        ptr::copy_nonoverlapping(src.as_ptr(), dst.as_mut_ptr(), src.len());\n    }",
            },
        }
    }

    result = build_replacement_block_diff(
        evidence=json.dumps(evidence),
        target_file="src/lib.rs",
        raw_replacement="dst[..src.len()].copy_from_slice(src);",
    )

    assert result.error is None
    assert "+    dst[..src.len()].copy_from_slice(src);" in result.diff


def test_replacement_block_rejects_signature_change():
    evidence = {
        "repair_slice_context": {
            "signature_text": "pub fn checksum(buf: &[u8]) -> u32 {",
            "signature_line": 3,
            "exact_replacement_block": {
                "target_file": "src/lib.rs",
                "start_line": 3,
                "end_line": 4,
                "old_block": "pub fn checksum(buf: &[u8]) -> u32 {\n    let total = 0;",
            },
        }
    }

    result = build_replacement_block_diff(
        evidence=json.dumps(evidence),
        target_file="src/lib.rs",
        raw_replacement="pub fn checksum(buf: &[u8]) -> u64 {\n    let total = 0;",
    )

    assert result.error == "replacement_block_signature_changed"


def test_replacement_block_boundary_still_uses_validator():
    evidence = {
        "repair_slice_context": {
            "exact_replacement_block": {
                "target_file": "src/lib.rs",
                "start_line": 1,
                "end_line": 1,
                "old_block": "use std::ptr;",
            },
        }
    }

    result = build_replacement_block_diff(
        evidence=json.dumps(evidence),
        target_file="src/lib.rs",
        raw_replacement="",
    )
    assert result.error == "replacement_block_empty"

    result = build_replacement_block_diff(
        evidence=json.dumps(evidence),
        target_file="src/lib.rs",
        raw_replacement="// removed",
    )
    ok, violation = validate_patch_constraints(
        diff=result.diff,
        target_file="src/lib.rs",
        signature_text="pub fn demo() {",
        boundary={"start_line": 3, "end_line": 10},
    )
    assert ok is False
    assert violation["code"] == "outside_boundary"
