from dataclasses import dataclass


@dataclass(frozen=True)
class RunCmdResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    log_path: str

