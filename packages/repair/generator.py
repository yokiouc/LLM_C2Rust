"""Controlled patch generation.

Migrated from apps/api/patch/generator.py — logic preserved exactly.
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

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


@dataclass(frozen=True)
class ReplacementBlockDiff:
    diff: str
    error: str | None = None
    replacement_block: str = ""
    raw_output_had_code_fence: bool = False


_LAST_GENERATION_INFO: dict[str, object] = {}


def get_last_generation_info() -> dict[str, object]:
    return dict(_LAST_GENERATION_INFO)


def _prompt_path() -> Path:
    """Locate the controlled_prompt.md template.

    Works from both packages/repair/ and apps/api/patch/ locations.
    """
    # Try packages-relative path first
    pkg_path = Path(__file__).resolve().parent.parent.parent / "apps" / "api" / "patch" / "controlled_prompt.md"
    if pkg_path.exists():
        return pkg_path
    # Fallback for when running from apps/api context
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


def _strip_wrapping_code_fence(text: str) -> tuple[str, bool]:
    lines = str(text or "").strip().splitlines()
    if len(lines) >= 2 and lines[0].strip().lower() in {"```", "```rust", "```text"} and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip("\n"), True
    return str(text or "").strip("\n"), False


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


def _load_evidence_obj(evidence: str) -> dict:
    s = str(evidence or "")
    i = s.find("{")
    j = s.rfind("}")
    if i < 0 or j < i:
        return {}
    try:
        obj = json.loads(s[i:j + 1])
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _make_unified_diff(path: str, start_line: int, old_lines: list[str], new_lines: list[str]) -> str:
    return (
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -{start_line},{len(old_lines)} +{start_line},{len(new_lines)} @@\n"
        + "".join(f"-{line}\n" for line in old_lines)
        + "".join(f"+{line}\n" for line in new_lines)
    )


def _first_nonempty(lines: list[str]) -> str:
    for line in lines:
        if line.strip():
            return line.strip()
    return ""


def _leading_indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _align_replacement_indentation(old_lines: list[str], new_lines: list[str]) -> list[str]:
    old_indent = ""
    for line in old_lines:
        if line.strip():
            old_indent = _leading_indent(line)
            break
    if not old_indent:
        return new_lines
    aligned: list[str] = []
    for line in new_lines:
        if line.strip() and not line.startswith((" ", "\t")):
            aligned.append(old_indent + line)
        else:
            aligned.append(line)
    return aligned


def _replacement_changes_signature(
    *,
    old_lines: list[str],
    new_lines: list[str],
    block_start_line: int,
    signature_line: int | None,
    signature_text: str | None,
) -> bool:
    if not signature_line or not signature_text:
        return False
    rel = signature_line - block_start_line
    if rel < 0 or rel >= len(old_lines):
        return False
    if rel >= len(new_lines):
        return True
    return new_lines[rel].strip() != str(signature_text).strip()


def _render_replacement_block_prompt(*, evidence_obj: dict, target_file: str) -> str:
    ctx = evidence_obj.get("repair_slice_context") if isinstance(evidence_obj.get("repair_slice_context"), dict) else {}
    block = ctx.get("exact_replacement_block") if isinstance(ctx.get("exact_replacement_block"), dict) else {}
    payload = {
        "task": "Return ONLY replacement Rust code for exact_old_block. Do not output unified diff.",
        "target_file": target_file,
        "slice_start": ctx.get("slice_start"),
        "slice_end": ctx.get("slice_end"),
        "block_kind": block.get("kind"),
        "old_block_start": block.get("start_line"),
        "old_block_end": block.get("end_line"),
        "exact_old_block": block.get("old_block"),
        "constraints": evidence_obj.get("constraints"),
        "forbidden": evidence_obj.get("forbidden"),
        "rules": [
            "Output replacement code only.",
            "Do not use Markdown fences.",
            "Do not explain.",
            "Do not modify public API or function signatures.",
            "Do not modify code outside exact_old_block.",
            "Preserve indentation expected at the replacement location.",
            "Prefer safe slice APIs such as get, indexing after existing bounds checks, and copy_from_slice.",
        ],
        "strategies": evidence_obj.get("strategies"),
        "diagnose": evidence_obj.get("diagnose"),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_replacement_block_diff(*, evidence: str, target_file: str, raw_replacement: str) -> ReplacementBlockDiff:
    obj = _load_evidence_obj(evidence)
    ctx = obj.get("repair_slice_context") if isinstance(obj.get("repair_slice_context"), dict) else {}
    block = ctx.get("exact_replacement_block") if isinstance(ctx.get("exact_replacement_block"), dict) else {}
    target = _canonical_target_path(target_file)
    block_target = _canonical_target_path(str(block.get("target_file") or target))
    if not target or block_target != target:
        return ReplacementBlockDiff("", "replacement_block_missing_target")

    start_line = int(block.get("start_line") or 0)
    old_block = str(block.get("old_block") or "")
    old_lines = old_block.splitlines()
    if start_line <= 0 or not old_lines:
        return ReplacementBlockDiff("", "replacement_block_missing_old_lines")

    cleaned, had_fence = _strip_wrapping_code_fence(raw_replacement)
    replacement = cleaned.strip("\n")
    if not replacement.strip():
        return ReplacementBlockDiff("", "replacement_block_empty", raw_output_had_code_fence=had_fence)
    if any(line.startswith(("--- ", "+++ ", "@@ ")) for line in replacement.splitlines()):
        return ReplacementBlockDiff("", "replacement_block_was_diff", replacement, had_fence)
    if "```" in replacement:
        return ReplacementBlockDiff("", "replacement_block_invalid_markdown", replacement, had_fence)

    new_lines = _align_replacement_indentation(old_lines, replacement.splitlines())
    signature_line = ctx.get("signature_line")
    try:
        sig_line_int = int(signature_line) if signature_line is not None else None
    except Exception:
        sig_line_int = None
    if _replacement_changes_signature(
        old_lines=old_lines,
        new_lines=new_lines,
        block_start_line=start_line,
        signature_line=sig_line_int,
        signature_text=str(ctx.get("signature_text") or ""),
    ):
        return ReplacementBlockDiff("", "replacement_block_signature_changed", replacement, had_fence)

    if _first_nonempty(old_lines).startswith(("pub fn ", "fn ")) and _first_nonempty(new_lines) != _first_nonempty(old_lines):
        return ReplacementBlockDiff("", "replacement_block_signature_changed", replacement, had_fence)

    return ReplacementBlockDiff(
        _make_unified_diff(target, start_line, old_lines, new_lines),
        None,
        replacement,
        had_fence,
    )


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
        "replacement_block_mode": False,
        "replacement_block": "",
        "raw_output_had_code_fence": False,
        "error": None,
    }
    rendered = _render_controlled_prompt(evidence=evidence, target_function=target_function)
    _assert_prompt_constraints(rendered)

    provider = provider or provider_from_env()
    if os.getenv("PATCH_LLM_MODE", "").strip().lower() == "replacement_block":
        obj = _load_evidence_obj(evidence)
        raw_replacement = provider.generate(_render_replacement_block_prompt(evidence_obj=obj, target_file=target_function))
        result = build_replacement_block_diff(
            evidence=evidence,
            target_file=target_function,
            raw_replacement=raw_replacement,
        )
        _LAST_GENERATION_INFO = {
            "normalized_diff": False,
            "replacement_block_mode": True,
            "replacement_block": result.replacement_block,
            "raw_output_had_code_fence": result.raw_output_had_code_fence,
            "error": result.error,
        }
        if result.error:
            return ""
        return result.diff

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
