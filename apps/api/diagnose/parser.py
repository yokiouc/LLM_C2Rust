import gzip
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


_LINE_RE = re.compile(
    r"(?P<file>[\w./-]+\.\w+):(?P<line>\d+):\d*(?:\s+\d+:\d+)?\s*(?P<error_code>\w+)?\s*:\s*(?P<summary>.*)"
)


@dataclass(frozen=True)
class ParsedIssue:
    error_code: str | None
    file: str | None
    line: int | None
    summary: str
    suggestion: str | None = None


ParserFn = Callable[[str], list[ParsedIssue]]


def _parse_generic(text: str) -> list[ParsedIssue]:
    out: list[ParsedIssue] = []
    match = _LINE_RE.match
    append = out.append
    for raw in text.splitlines():
        line = raw.strip("\r\n")
        if not line:
            continue
        m = match(line)
        if m:
            append(
                ParsedIssue(
                    error_code=m.group("error_code") or None,
                    file=m.group("file") or None,
                    line=int(m.group("line")) if m.group("line") else None,
                    summary=(m.group("summary") or "").strip(),
                )
            )
        else:
            append(ParsedIssue(error_code=None, file=None, line=None, summary=line))
    return out


def _parse_runner_log(text: str) -> list[ParsedIssue]:
    s = text.strip()
    if not s:
        return []
    try:
        obj = json.loads(s)
    except Exception:
        return []
    if not isinstance(obj, dict):
        return []
    stderr = str(obj.get("stderr", "") or "")
    stdout = str(obj.get("stdout", "") or "")
    payload = stderr if stderr.strip() else stdout
    if not payload.strip():
        return []
    return _parse_generic(payload)


def _read_input(input_: str | Path) -> str:
    if isinstance(input_, Path):
        p = input_
    else:
        s = str(input_)
        if not s:
            return ""
        if "\n" in s or "\r" in s:
            return s
        p = Path(s)
        if not p.exists():
            return s

    if p.suffix == ".gz":
        with gzip.open(p, "rb") as f:
            raw = f.read()
        try:
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return raw.decode(errors="replace")
    return p.read_text(encoding="utf-8", errors="replace")


def parse_diagnostics(input_: str | Path) -> list[dict[str, Any]]:
    text = _read_input(input_)
    chain: list[ParserFn] = [_parse_runner_log, _parse_generic]
    issues: list[ParsedIssue] = []
    for fn in chain:
        issues = fn(text)
        if issues:
            break
    return [
        {"error_code": i.error_code, "file": i.file, "line": i.line, "summary": i.summary, "suggestion": i.suggestion}
        for i in issues
    ]
