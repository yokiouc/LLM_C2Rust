"""Runner result types.

Migrated from apps/api/runner/types.py — preserved exactly.
Re-exports from packages.core.types for new code.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RunCmdResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    log_path: str
