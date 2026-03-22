import json
from pathlib import Path

from patch.engine import ConvergenceConfig, run_converge
from patch.llm_provider import LLMProvider


class SeqProvider(LLMProvider):
    def __init__(self, outs: list[str]) -> None:
        self._outs = outs
        self._i = 0

    def generate(self, prompt: str) -> str:
        if self._i >= len(self._outs):
            return self._outs[-1] if self._outs else ""
        out = self._outs[self._i]
        self._i += 1
        return out


def _mk_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "lib.rs").write_text(
        "\n".join(
            [
                "pub fn f() {",
                "    unsafe {",
                "        let x = 1;",
                "    }",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    return root


def test_no_progress_triggers_rollback_and_final_state_is_best(tmp_path: Path):
    base_dir = _mk_workspace(tmp_path)
    out_dir = tmp_path / "metrics"

    diff_good = "\n".join(
        [
            "--- a/src/lib.rs",
            "+++ b/src/lib.rs",
            "@@ -1,5 +1,5 @@",
            " pub fn f() {",
            "-    unsafe {",
            "+    {",
            "         let x = 1;",
            "     }",
            " }",
            "",
        ]
    )
    diff_bad = "\n".join(
        [
            "--- a/src/lib.rs",
            "+++ b/src/lib.rs",
            "@@ -1,5 +1,5 @@",
            " pub fn f() {",
            "-    {",
            "+    unsafe {",
            "         let x = 1;",
            "     }",
            " }",
            "",
        ]
    )

    best, hist = run_converge(
        base_dir=base_dir,
        evidence=json.dumps({"file": "src/lib.rs", "slice": "unsafe {"}),
        target_function="f",
        prompt_template_path=Path(__file__).resolve().parents[1] / "patch" / "controlled_prompt.md",
        config=ConvergenceConfig(max_iters=3, no_progress_limit=1),
        config_hash="h",
        out_dir=out_dir,
        validate_cmd=None,
        provider=SeqProvider([diff_good, diff_bad, diff_bad]),
    )
    assert best.strip() == diff_good.strip()
    assert len(hist) == 3
    assert (out_dir / "converge.jsonl").exists()
    content = (base_dir / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "unsafe {" not in content


def test_max_iters_ends_with_empty_best_diff(tmp_path: Path):
    base_dir = _mk_workspace(tmp_path)
    out_dir = tmp_path / "metrics"

    best, hist = run_converge(
        base_dir=base_dir,
        evidence=json.dumps({"file": "src/lib.rs", "slice": "unsafe {"}),
        target_function="f",
        prompt_template_path=Path(__file__).resolve().parents[1] / "patch" / "controlled_prompt.md",
        config=ConvergenceConfig(max_iters=2, no_progress_limit=1),
        config_hash="h",
        out_dir=out_dir,
        validate_cmd=None,
        provider=SeqProvider(["", ""]),
    )
    assert best == ""
    assert len(hist) == 2


def test_apply_failure_is_not_selected_as_best(tmp_path: Path):
    base_dir = _mk_workspace(tmp_path)
    out_dir = tmp_path / "metrics"

    diff_missing_file = "\n".join(
        [
            "--- a/src/missing.rs",
            "+++ b/src/missing.rs",
            "@@ -1,1 +1,1 @@",
            "-x",
            "+y",
            "",
        ]
    )
    diff_good = "\n".join(
        [
            "--- a/src/lib.rs",
            "+++ b/src/lib.rs",
            "@@ -1,5 +1,5 @@",
            " pub fn f() {",
            "-    unsafe {",
            "+    {",
            "         let x = 1;",
            "     }",
            " }",
            "",
        ]
    )

    best, hist = run_converge(
        base_dir=base_dir,
        evidence=json.dumps({"file": "src/lib.rs", "slice": "unsafe {"}),
        target_function="f",
        prompt_template_path=Path(__file__).resolve().parents[1] / "patch" / "controlled_prompt.md",
        config=ConvergenceConfig(max_iters=2, no_progress_limit=1),
        config_hash="h",
        out_dir=out_dir,
        validate_cmd=None,
        provider=SeqProvider([diff_missing_file, diff_good]),
    )
    assert hist[0].apply_ok is False
    assert best.strip() == diff_good.strip()
