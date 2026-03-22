import os
import json
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
        lines = line.splitlines() or ["line1"]
        target_idx = 0
        for i, ln in enumerate(lines):
            s0 = ln.strip()
            if not s0:
                continue
            if "fn " in s0:
                continue
            target_idx = i
            break
        target_line = lines[target_idx]
        patched = target_line + " // patched"
        return (
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            f"@@ -{target_idx+1},1 +{target_idx+1},1 @@\n"
            f"-{target_line}\n"
            f"+{patched}\n"
        )


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
