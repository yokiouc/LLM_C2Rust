from dataclasses import dataclass
import json
from pathlib import Path
import re

from .llm_provider import LLMProvider, provider_from_env


@dataclass(frozen=True)
class FileContent:
    path: str
    content: str


@dataclass(frozen=True)
class NormalizedDiff:
    diff: str
    error: str | None = None
    normalized_diff: bool = False
    raw_output_had_code_fence: bool = False


_LAST_GENERATION_INFO: dict[str, object] = {}


def get_last_generation_info() -> dict[str, object]:
    return dict(_LAST_GENERATION_INFO)


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


def _strip_code_fences(text: str) -> tuple[str, bool]:
    lines = str(text or "").strip().splitlines()
    had_fence = False
    out: list[str] = []
    for line in lines:
        marker = line.strip().lower()
        if marker in {"```", "```diff"}:
            had_fence = True
            continue
        out.append(line)
    return "\n".join(out), had_fence


def _canonical_target_path(path: str) -> str:
    return str(path or "").strip().replace("\\", "/").lstrip("/")


def _diff_header_path(line: str, prefix: str) -> str | None:
    if not line.startswith(prefix):
        return None
    path = line[len(prefix) :].strip().replace("\\", "/")
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return path.lstrip("/")


def _extract_diff_block(text: str) -> str:
    lines = str(text or "").splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("--- ")), None)
    if start is None:
        return ""
    out: list[str] = []
    for line in lines[start:]:
        if out and not _is_diff_line(line):
            break
        out.append(line)
    return "\n".join(out)


_HUNK_HEADER_RE = re.compile(r"^(@@\s+-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@)(?:\s+.*)?$")


def normalize_llm_unified_diff(raw_text: str, target_file: str) -> NormalizedDiff:
    target = _canonical_target_path(target_file)
    without_fences, had_fence = _strip_code_fences(raw_text)
    block = _extract_diff_block(without_fences)
    if not block or "@@ " not in block:
        return NormalizedDiff("", "openai_invalid_diff", raw_output_had_code_fence=had_fence)

    lines = block.splitlines()
    if len(lines) < 3 or not lines[0].startswith("--- ") or not lines[1].startswith("+++ "):
        return NormalizedDiff("", "openai_invalid_diff", raw_output_had_code_fence=had_fence)

    old_path = _diff_header_path(lines[0], "--- ")
    new_path = _diff_header_path(lines[1], "+++ ")
    if not old_path or not new_path or old_path != target or new_path != target:
        return NormalizedDiff("", "openai_invalid_diff", raw_output_had_code_fence=had_fence)

    normalized_lines = list(lines)
    normalized_lines[0] = f"--- a/{target}"
    normalized_lines[1] = f"+++ b/{target}"
    in_hunk = False
    for idx, line in enumerate(normalized_lines[2:], start=2):
        if line.startswith("@@"):
            match = _HUNK_HEADER_RE.match(line)
            if not match:
                return NormalizedDiff("", "openai_invalid_diff", True, had_fence)
            normalized_lines[idx] = match.group(1)
            in_hunk = True
            continue
        if in_hunk and line == "":
            normalized_lines[idx] = " "
            continue
        if line.startswith("+") and not line.startswith("+++ ") and "_ptr_import_marker" in line:
            return NormalizedDiff("", "openai_invalid_diff", True, had_fence)
    diff = "\n".join(normalized_lines).strip() + "\n"
    normalized = diff != (str(raw_text or "").strip() + "\n")
    if not _validate_unified_diff(diff):
        return NormalizedDiff("", "openai_invalid_diff", normalized, had_fence)
    return NormalizedDiff(diff, None, normalized, had_fence)


def _extract_first_file_path_from_diff(diff: str) -> str | None:
    for line in (diff or "").splitlines():
        if line.startswith("--- a/") or line.startswith("+++ b/"):
            p = line.split("/", 1)[1].strip()
            if p:
                return p
    return None


def generate_controlled_patch(*, evidence: str, target_function: str, provider: LLMProvider | None = None) -> str:
    global _LAST_GENERATION_INFO
    _LAST_GENERATION_INFO = {
        "normalized_diff": False,
        "raw_output_had_code_fence": False,
        "error": None,
    }
    rendered = _render_controlled_prompt(evidence=evidence, target_function=target_function)
    _assert_prompt_constraints(rendered)

    provider = provider or provider_from_env()
    raw_diff = provider.generate(rendered)
    if not raw_diff:
        return ""
    normalized = normalize_llm_unified_diff(raw_diff, target_function)
    _LAST_GENERATION_INFO = {
        "normalized_diff": normalized.normalized_diff,
        "raw_output_had_code_fence": normalized.raw_output_had_code_fence,
        "error": normalized.error,
    }
    if normalized.error:
        return ""
    diff = normalized.diff
    if not _validate_unified_diff(diff):
        _LAST_GENERATION_INFO["error"] = "openai_invalid_diff"
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
