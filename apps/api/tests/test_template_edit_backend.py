import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from packages.repair.llm_provider import TemplateEditProvider
from packages.repair.patch_engine import apply_patch
from packages.repair.patch_validator import validate_patch_constraints


ROOT = Path(__file__).resolve().parents[3]


def _prompt(*, rel: str, start: int, end: int) -> str:
    ws = ROOT / rel
    code = (ws / "src" / "lib.rs").read_text(encoding="utf-8")
    evidence = {
        "recommended_boundary": {
            "file": "src/lib.rs",
            "start_line": start,
            "end_line": end,
            "anchor_line": start,
            "anchor_kind": "hotspot",
        },
        "items": [
            {
                "kind": "rust_function_slice",
                "excerpt": code,
                "meta": {"file": "src/lib.rs", "evidence_type": "code_slice"},
            }
        ],
    }
    return json.dumps(evidence)


def _old_start(diff: str) -> int:
    m = re.search(r"^@@ -(\d+),", diff, flags=re.MULTILINE)
    assert m
    return int(m.group(1))


def _signature(rel: str) -> str:
    for line in (ROOT / rel / "src" / "lib.rs").read_text(encoding="utf-8").splitlines():
        if line.startswith("pub fn "):
            return line
    return ""


def _assert_valid(diff: str, *, rel: str, start: int, end: int) -> None:
    assert diff
    assert "// patched" not in diff
    assert start <= _old_start(diff) <= end
    ok, violation = validate_patch_constraints(
        diff=diff,
        target_file="src/lib.rs",
        signature_text=_signature(rel),
        boundary={"start_line": start, "end_line": end},
    )
    assert ok, violation


def test_template_edit_generates_real_raw_pointer_patch():
    rel = "experiments/workspaces/CF-01_raw_ptr_deref_fixture"
    diff = TemplateEditProvider().generate(_prompt(rel=rel, start=1, end=9))
    _assert_valid(diff, rel=rel, start=1, end=9)
    assert "values.first().copied()" in diff


def test_template_edit_generates_pointer_arithmetic_patch():
    rel = "experiments/workspaces/CF-02_ptr_arithmetic_fixture"
    diff = TemplateEditProvider().generate(_prompt(rel=rel, start=1, end=9))
    _assert_valid(diff, rel=rel, start=1, end=9)
    assert "values.get(index).copied()" in diff


def test_template_edit_generates_ptr_copy_patch_inside_boundary():
    rel = "experiments/workspaces/CF-03_ptr_copy_fixture"
    diff = TemplateEditProvider().generate(_prompt(rel=rel, start=3, end=13))
    _assert_valid(diff, rel=rel, start=3, end=13)
    assert "copy_from_slice" in diff
    assert "copy_nonoverlapping" not in "\n".join(line for line in diff.splitlines() if line.startswith("+"))


def test_patch_validator_still_rejects_outside_boundary():
    diff = "\n".join(
        [
            "--- a/src/lib.rs",
            "+++ b/src/lib.rs",
            "@@ -1,1 +1,1 @@",
            "-use std::ptr;",
            "+use std::ptr;",
        ]
    )
    ok, violation = validate_patch_constraints(
        diff=diff,
        target_file="src/lib.rs",
        signature_text=None,
        boundary={"start_line": 3, "end_line": 13},
    )
    assert not ok
    assert violation and violation["code"] == "outside_boundary"


@pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo not available")
@pytest.mark.parametrize(
    ("rel", "start", "end"),
    [
        ("experiments/workspaces/CF-01_raw_ptr_deref_fixture", 1, 9),
        ("experiments/workspaces/CF-02_ptr_arithmetic_fixture", 1, 9),
        ("experiments/workspaces/CF-03_ptr_copy_fixture", 3, 13),
    ],
)
def test_generated_fixture_patches_build_test_and_lint(tmp_path, rel, start, end):
    src = ROOT / rel
    dst = tmp_path / src.name
    shutil.copytree(src, dst)

    diff = TemplateEditProvider().generate(_prompt(rel=rel, start=start, end=end))
    result = apply_patch(dst, diff)
    assert result.ok, result.error_msg

    for cmd in (["cargo", "build"], ["cargo", "test"], ["cargo", "clippy", "--", "-D", "warnings"]):
        completed = subprocess.run(cmd, cwd=dst, text=True, capture_output=True, timeout=120)
        assert completed.returncode == 0, completed.stdout + completed.stderr

