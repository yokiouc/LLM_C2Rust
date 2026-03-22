import os
import time
from pathlib import Path

import pytest

from patch.engine import ConvergenceConfig, run_converge
from patch.llm_provider import LLMProvider


class ConstantProvider(LLMProvider):
    def __init__(self, out: str) -> None:
        self._out = out

    def generate(self, prompt: str) -> str:
        return self._out


@pytest.mark.skipif(os.getenv("PERF_TESTS", "") != "1", reason="set PERF_TESTS=1 to enable")
def test_converge_under_10_min_no_tests(tmp_path: Path):
    base_dir = tmp_path / "ws"
    (base_dir / "src").mkdir(parents=True, exist_ok=True)
    (base_dir / "src" / "lib.rs").write_text("pub fn f() { unsafe { } }\n", encoding="utf-8", newline="\n")

    diff = "\n".join(
        [
            "--- a/src/lib.rs",
            "+++ b/src/lib.rs",
            "@@ -1,1 +1,1 @@",
            "-pub fn f() { unsafe { } }",
            "+pub fn f() { { } }",
            "",
        ]
    )
    t0 = time.perf_counter()
    run_converge(
        base_dir=base_dir,
        evidence='{"file":"src/lib.rs","slice":"unsafe {"}',
        target_function="f",
        prompt_template_path=Path(__file__).resolve().parents[1] / "patch" / "controlled_prompt.md",
        config=ConvergenceConfig(max_iters=20, no_progress_limit=5),
        config_hash="h",
        out_dir=tmp_path / "metrics",
        validate_cmd=None,
        provider=ConstantProvider(diff),
    )
    assert time.perf_counter() - t0 <= 600

