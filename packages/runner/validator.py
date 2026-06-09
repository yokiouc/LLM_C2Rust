"""Phased validation runner: build / test / clippy / fmt.

Each phase runs a cargo command, captures output, parses issues,
and returns a structured ValidationResult.
"""

import time
from pathlib import Path
from typing import Any

from packages.core.types import ValidationResult
from packages.repair.diagnose import parse_diagnostics
from packages.runner.cmd import run_cmd


# ---------------------------------------------------------------------------
# Phase definitions
# ---------------------------------------------------------------------------

PHASE_COMMANDS: dict[str, list[str]] = {
    "build":  ["cargo", "build"],
    "test":   ["cargo", "test"],
    "clippy": ["cargo", "clippy", "--", "-D", "warnings"],
    "fmt":    ["cargo", "fmt", "--check"],
}

VALID_STAGES = {"build", "test", "clippy", "fmt"}


# ---------------------------------------------------------------------------
# Single phase execution
# ---------------------------------------------------------------------------

def run_validation_phase(
    *,
    stage: str,
    workspace_path: Path,
    env: dict[str, str] | None = None,
    timeout: int = 120,
) -> ValidationResult:
    """Run a single validation phase and return a structured result.

    Args:
        stage: One of 'build', 'test', 'clippy', 'fmt'
        workspace_path: Path to the Rust workspace root
        env: Additional environment variables (e.g. RUNNER_MODE=mock)
        timeout: Timeout in seconds
    """
    if stage not in VALID_STAGES:
        raise ValueError(f"Invalid stage: {stage}. Must be one of {VALID_STAGES}")

    cmd = PHASE_COMMANDS[stage]
    env = env or {}
    cwd = str(workspace_path.resolve())

    result = run_cmd(
        cmd=cmd,
        cwd=cwd,
        env=env,
        timeout=timeout,
        capture=True,
    )

    ok = result.exit_code == 0
    status = "pass" if ok else "fail"
    if result.exit_code == 124:
        status = "error"  # timeout

    # Parse issues from output
    raw_text = result.stderr if result.stderr.strip() else result.stdout
    parsed_issues: list[dict[str, Any]] = []
    issue_kind: str | None = None
    if not ok and raw_text.strip():
        parsed_issues = parse_diagnostics(raw_text)
        # Classify the primary issue kind
        if parsed_issues:
            first = parsed_issues[0]
            code = str(first.get("error_code") or "")
            if code.startswith("E"):
                issue_kind = "compile_error"
            elif "warning" in str(first.get("summary") or "").lower():
                issue_kind = "lint_warning"
            elif "test" in stage:
                issue_kind = "test_failure"
            else:
                issue_kind = "unknown"

    return ValidationResult(
        phase=stage,
        ok=ok,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        stdout=result.stdout,
        stderr=result.stderr,
        log_path=result.log_path,
        parsed_issues=parsed_issues,
        issue_count=len(parsed_issues),
    )


# ---------------------------------------------------------------------------
# Full validation pipeline
# ---------------------------------------------------------------------------

def run_full_validation(
    *,
    workspace_path: Path,
    stages: list[str] | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 120,
    stop_on_failure: bool = True,
) -> list[ValidationResult]:
    """Run multiple validation phases in sequence.

    Args:
        workspace_path: Path to the Rust workspace root
        stages: List of stages to run. Defaults to ['build', 'test', 'clippy', 'fmt']
        env: Additional environment variables
        timeout: Timeout per phase in seconds
        stop_on_failure: If True, stop after the first failing phase

    Returns:
        List of ValidationResult, one per phase attempted.
    """
    if stages is None:
        stages = ["build", "test", "clippy", "fmt"]

    results: list[ValidationResult] = []
    for stage in stages:
        if stage not in VALID_STAGES:
            results.append(ValidationResult(
                phase=stage, ok=False, exit_code=-1, duration_ms=0,
                parsed_issues=[{"summary": f"Invalid stage: {stage}"}],
                issue_count=1,
            ))
            if stop_on_failure:
                break
            continue

        vr = run_validation_phase(
            stage=stage,
            workspace_path=workspace_path,
            env=env,
            timeout=timeout,
        )
        results.append(vr)

        if not vr.ok and stop_on_failure:
            # Mark remaining stages as skipped
            for remaining in stages[stages.index(stage) + 1:]:
                results.append(ValidationResult(
                    phase=remaining, ok=False, exit_code=-1, duration_ms=0,
                    parsed_issues=[], issue_count=0,
                ))
            break

    return results


def persist_validation_results(
    results: list[ValidationResult],
    *,
    conn: Any,
    run_id: str,
    patch_id: str | None = None,
) -> list[int]:
    """Persist validation results to the database.

    Returns list of created validation_result IDs.
    """
    from packages.repair.repository import create_validation_result

    ids: list[int] = []
    for vr in results:
        status = "pass" if vr.ok else "fail"
        if vr.exit_code == -1:
            status = "skip"
        elif vr.exit_code == 124:
            status = "error"

        # Determine issue_kind
        issue_kind = None
        if vr.parsed_issues:
            first = vr.parsed_issues[0]
            code = str(first.get("error_code") or "")
            if code.startswith("E"):
                issue_kind = "compile_error"
            elif "warning" in str(first.get("summary") or "").lower():
                issue_kind = "lint_warning"
            elif vr.phase == "test":
                issue_kind = "test_failure"

        vid = create_validation_result(
            conn,
            run_id=run_id,
            patch_id=patch_id,
            stage=vr.phase,
            status=status,
            exit_code=vr.exit_code if vr.exit_code >= 0 else None,
            duration_ms=vr.duration_ms,
            issue_count=vr.issue_count,
            issue_kind=issue_kind,
            parsed_issues=vr.parsed_issues,
            stdout_path=vr.log_path if vr.log_path else None,
            stderr_path=None,
            output={"stdout_len": len(vr.stdout), "stderr_len": len(vr.stderr)},
        )
        ids.append(vid)
    return ids
