from dataclasses import dataclass
import json
from pathlib import Path

from .llm_provider import LLMProvider, provider_from_env


@dataclass(frozen=True)
class FileContent:
    path: str
    content: str


def _prompt_path() -> Path:
    return Path(__file__).resolve().parent / "controlled_prompt.md"


def _read_controlled_prompt_template() -> str:
    return _prompt_path().read_text(encoding="utf-8", errors="replace")


def _render_controlled_prompt(*, evidence: str, target_function: str) -> str:
    tmpl = _read_controlled_prompt_template()
    return tmpl.replace("{evidence}", evidence).replace("{target_function}", target_function)


def _required_instructions() -> list[str]:
    return [
        "1. 接口签名保持完全不变",
        "2. 仅允许最小化语义补丁，禁止全文件重写",
        "3. 必须引用 Evidence Pack 中的具体条目（行号、函数名、切片）",
        "4. 输出格式必须为统一 diff（unified diff），且只包含 `@@` 块",
        "5. 若无法生成符合上述约束的补丁，返回空 diff 并给出原因",
    ]


def _assert_prompt_constraints(rendered: str) -> None:
    idx = 0
    for s in _required_instructions():
        j = rendered.find(s, idx)
        if j < 0:
            raise ValueError("controlled_prompt_missing_required_instructions")
        idx = j + len(s)


def _is_diff_line(line: str) -> bool:
    if not line:
        return True
    return (
        line.startswith("--- ")
        or line.startswith("+++ ")
        or line.startswith("@@ ")
        or line.startswith("+")
        or line.startswith("-")
        or line.startswith(" ")
    )


def _validate_unified_diff(diff: str) -> bool:
    s = (diff or "").strip("\r\n")
    if not s:
        return True
    if "@@ " not in s:
        return False
    for line in s.splitlines():
        if not _is_diff_line(line):
            return False
    return True


def _extract_first_file_path_from_diff(diff: str) -> str | None:
    for line in (diff or "").splitlines():
        if line.startswith("--- a/") or line.startswith("+++ b/"):
            p = line.split("/", 1)[1].strip()
            if p:
                return p
    return None


def generate_controlled_patch(*, evidence: str, target_function: str, provider: LLMProvider | None = None) -> str:
    rendered = _render_controlled_prompt(evidence=evidence, target_function=target_function)
    _assert_prompt_constraints(rendered)

    provider = provider or provider_from_env()
    diff = provider.generate(rendered)
    if not diff:
        return ""
    if not _validate_unified_diff(diff):
        return ""
    diff = diff.strip() + "\n"
    fp = _extract_first_file_path_from_diff(diff)
    if not fp:
        return ""
    if str(target_function).strip() and fp != str(target_function).strip():
        return ""
    return diff


def generate_patch(old_files: list[FileContent], new_files: list[FileContent]) -> str:
    if not old_files:
        path = "file.txt"
        line = "line1"
    else:
        path = old_files[0].path
        lines = old_files[0].content.splitlines()
        line = lines[0] if lines else "line1"

    evidence = json.dumps({"file": path, "start_line": 1, "end_line": 1, "slice": line}, ensure_ascii=False)
    return generate_controlled_patch(evidence=evidence, target_function=str(path))
