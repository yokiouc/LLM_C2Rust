"""LLM provider implementations for patch generation.

Migrated from apps/api/patch/llm_provider.py — logic preserved exactly.
"""

import json
import os
import re
from abc import ABC, abstractmethod

import httpx


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str: ...


class TemplateProvider(LLMProvider):
    def generate(self, prompt: str) -> str:
        s = str(prompt or "")
        i = s.find("{")
        j = s.rfind("}")
        if i < 0 or j < i:
            return ""
        try:
            obj = json.loads(s[i : j + 1])
        except Exception:
            return ""

        path = str(obj.get("file") or "")
        line = str(obj.get("slice") or "")
        if not path or not line:
            items = obj.get("items")
            if isinstance(items, list) and items:
                first_item = items[0] if isinstance(items[0], dict) else {}
                meta = first_item.get("meta") if isinstance(first_item, dict) else {}
                if isinstance(meta, dict):
                    path = str(meta.get("file") or path)
                line = str(first_item.get("excerpt") or first_item.get("content") or line)

        path = path or "file.txt"
        line = line or "line1"
        first_line = line.splitlines()[0] if line.splitlines() else "line1"
        return (
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            "@@ -1,1 +1,1 @@\n"
            f"-{first_line}\n"
            f"+{first_line}\n"
        )


class TemplateEditProvider(LLMProvider):
    @staticmethod
    def _load_evidence(prompt: str) -> dict:
        s = str(prompt or "")
        i = s.find("{")
        j = s.rfind("}")
        if i < 0 or j < i:
            return {}
        try:
            obj = json.loads(s[i : j + 1])
        except Exception:
            return {}
        return obj if isinstance(obj, dict) else {}

    @staticmethod
    def _chunk_content(item: dict) -> str:
        chunk_id = item.get("chunk_id")
        if not chunk_id:
            return ""
        dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN") or ""
        if not dsn:
            return ""
        try:
            import psycopg

            with psycopg.connect(dsn, connect_timeout=3) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT content FROM code_chunks WHERE chunk_id = %s;", (int(chunk_id),))
                    row = cur.fetchone()
                    return str(row[0] or "") if row else ""
        except Exception:
            return ""

    @classmethod
    def _target_code(cls, obj: dict, path: str) -> str:
        items = obj.get("items")
        if not isinstance(items, list):
            return ""
        fallback = ""
        for item in items:
            if not isinstance(item, dict):
                continue
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            item_path = str(meta.get("file") or "")
            text = cls._chunk_content(item) or str(item.get("excerpt") or item.get("content") or "")
            if not text:
                continue
            if not fallback and item_path == path:
                fallback = text
            if item_path == path and str(item.get("kind") or "") == "rust_function_slice":
                return text
        return fallback

    @staticmethod
    def _make_diff(path: str, start: int, old_lines: list[str], new_lines: list[str]) -> str:
        return (
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            f"@@ -{start},{len(old_lines)} +{start},{len(new_lines)} @@\n"
            + "".join(f"-{line}\n" for line in old_lines)
            + "".join(f"+{line}\n" for line in new_lines)
        )

    @staticmethod
    def _line_range(lines: list[str], start_line: int, end_line: int):
        lo = max(start_line, 1)
        hi = min(end_line, len(lines))
        for line_no in range(lo, hi + 1):
            yield line_no, lines[line_no - 1]

    @classmethod
    def _patch_pointer_arithmetic(cls, path: str, lines: list[str], start_line: int, end_line: int) -> str:
        for line_no, line in cls._line_range(lines, start_line, end_line):
            m = re.search(r"\blet\s+(\w+)\s*=\s*(\w+)\.as_ptr\(\);", line)
            if not m:
                continue
            ptr_name, slice_name = m.group(1), m.group(2)
            stop = min(end_line, line_no + 5, len(lines))
            for unsafe_no in range(line_no + 1, stop + 1):
                unsafe_line = lines[unsafe_no - 1]
                pat = rf"unsafe\s*\{{\s*Some\(\*{re.escape(ptr_name)}\.(?:add|offset)\((\w+)\)\)\s*\}}"
                m2 = re.search(pat, unsafe_line)
                if not m2:
                    continue
                index_name = m2.group(1)
                old = lines[line_no - 1 : unsafe_no]
                new = [f"{line[: len(line) - len(line.lstrip())]}{slice_name}.get({index_name}).copied()"]
                return cls._make_diff(path, line_no, old, new)
        return ""

    @classmethod
    def _patch_raw_deref(cls, path: str, lines: list[str], start_line: int, end_line: int) -> str:
        for line_no, line in cls._line_range(lines, start_line, end_line):
            m = re.search(r"\blet\s+(\w+)\s*=\s*(\w+)\.as_ptr\(\);", line)
            if not m:
                continue
            ptr_name, slice_name = m.group(1), m.group(2)
            stop = min(end_line, line_no + 5, len(lines))
            for unsafe_no in range(line_no + 1, stop + 1):
                unsafe_line = lines[unsafe_no - 1]
                pat = rf"unsafe\s*\{{\s*Some\(\*{re.escape(ptr_name)}\)\s*\}}"
                if not re.search(pat, unsafe_line):
                    continue
                old = lines[line_no - 1 : unsafe_no]
                new = [f"{line[: len(line) - len(line.lstrip())]}{slice_name}.first().copied()"]
                return cls._make_diff(path, line_no, old, new)
        return ""

    @classmethod
    def _patch_ptr_copy(cls, path: str, lines: list[str], start_line: int, end_line: int) -> str:
        for call_no, line in cls._line_range(lines, start_line, end_line):
            m = re.search(
                r"(?:std::)?ptr::copy(?:_nonoverlapping)?\((\w+)\.as_ptr\(\),\s*(\w+)\.as_mut_ptr\(\),\s*([^)]+)\);",
                line.strip(),
            )
            if not m:
                continue
            src, dst, count = m.group(1), m.group(2), m.group(3).strip()
            block_start = call_no
            while block_start > start_line and "unsafe" not in lines[block_start - 1]:
                block_start -= 1
            block_end = call_no
            while block_end <= end_line and "}" not in lines[block_end - 1]:
                block_end += 1
            if block_end > end_line:
                continue
            indent = lines[block_start - 1][: len(lines[block_start - 1]) - len(lines[block_start - 1].lstrip())]
            if count == f"{src}.len()":
                replacement = f"{indent}{dst}[..{src}.len()].copy_from_slice({src});"
                marker_expr = src
            else:
                replacement = f"{indent}{dst}[..{count}].copy_from_slice(&{src}[..{count}]);"
                marker_expr = count
            new = []
            old_region = lines[block_start - 1 : block_end]
            text_outside_region = "\n".join(lines[: block_start - 1] + lines[block_end:])
            if "use std::ptr;" in "\n".join(lines) and "ptr::" not in text_outside_region:
                new.append(f"{indent}let _ptr_import_marker = ptr::addr_of!({marker_expr});")
            new.append(replacement)
            return cls._make_diff(path, block_start, old_region, new)
        return ""

    @classmethod
    def _patch_buffer_walk(cls, path: str, lines: list[str], start_line: int, end_line: int) -> str:
        for line_no, line in cls._line_range(lines, start_line, end_line):
            m = re.search(r"\blet\s+(\w+)\s*=\s*(\w+)\.as_ptr\(\);", line)
            if not m:
                continue
            ptr_name, slice_name = m.group(1), m.group(2)
            stop = min(end_line, line_no + 6, len(lines))
            for unsafe_no in range(line_no + 1, stop + 1):
                unsafe_line = lines[unsafe_no - 1]
                if f"*{ptr_name}.add(" not in unsafe_line:
                    continue
                old = lines[line_no - 1 : unsafe_no]
                indent = line[: len(line) - len(line.lstrip())]
                return cls._make_diff(path, line_no, old, [f"{indent}for &byte in {slice_name} {{"])
        return ""

    def generate(self, prompt: str) -> str:
        obj = self._load_evidence(prompt)
        boundary = obj.get("recommended_boundary") if isinstance(obj.get("recommended_boundary"), dict) else {}
        path = str(boundary.get("file") or obj.get("file") or "").strip()
        start_line = int(boundary.get("start_line") or obj.get("start_line") or 1)
        end_line = int(boundary.get("end_line") or obj.get("end_line") or start_line)
        code = self._target_code(obj, path) or str(obj.get("slice") or "")
        if not path or not code:
            return ""

        lines = code.splitlines()
        if not lines:
            return ""
        end_line = min(max(end_line, start_line), len(lines))

        for builder in (
            self._patch_pointer_arithmetic,
            self._patch_raw_deref,
            self._patch_ptr_copy,
            self._patch_buffer_walk,
        ):
            diff = builder(path, lines, start_line, end_line)
            if diff:
                return diff
        return ""


class OpenAIProvider(LLMProvider):
    def __init__(self) -> None:
        self._api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self._base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self._model = os.getenv("OPENAI_PATCH_MODEL", "gpt-4o-mini").strip()
        self._timeout_s = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "60"))

    def generate(self, prompt: str) -> str:
        if not self._api_key:
            return ""

        headers = {"Authorization": f"Bearer {self._api_key}"}
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        with httpx.Client(timeout=self._timeout_s) as client:
            r = client.post(f"{self._base_url}/chat/completions", headers=headers, json=payload)
            if r.status_code != 200:
                return ""
            data = r.json()
        try:
            return str(data["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            return ""


def provider_from_env() -> LLMProvider:
    backend = os.getenv("PATCH_BACKEND", "template").strip().lower()
    if backend in {"template_edit", "demo"}:
        return TemplateEditProvider()
    if backend == "openai":
        return OpenAIProvider()
    return TemplateProvider()
