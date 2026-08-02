"""Shared helpers for the test/lint/typecheck/format/coverage tools.

All five tools ultimately spawn a subprocess (pytest, ruff, mypy, …). The
spawn logic is centralised here so each tool stays small.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any

# Hard cap so a misbehaving test run can't hang the agent forever.
MAX_TIMEOUT = 300  # 5 minutes
MAX_OUTPUT_BYTES = 50_000


class ToolNotFoundError(RuntimeError):
    """Raised when a required CLI tool is not available on PATH."""


async def _run(
    cmd: list[str],
    cwd: str | None = None,
    timeout: int = 120,
) -> tuple[int, str, str]:
    """Run `cmd` and return (returncode, stdout, stderr).

    Args:
        cmd: Full command including the executable.
        cwd: Working directory.
        timeout: Max seconds (capped at MAX_TIMEOUT).

    Returns:
        Tuple of (returncode, stdout, stderr).

    Raises:
        ToolNotFoundError: If the executable is not on PATH.
    """
    if not cmd:
        raise ValueError("cmd must not be empty")
    exe = shutil.which(cmd[0])
    if exe is None:
        raise ToolNotFoundError(f"{cmd[0]!r} executable not found in PATH")
    capped = min(int(timeout), MAX_TIMEOUT)
    full = [exe, *cmd[1:]]
    try:
        proc = await asyncio.create_subprocess_exec(
            *full,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "LC_ALL": "C.UTF-8"},
        )
    except Exception as e:
        raise ToolNotFoundError(f"failed to spawn {exe}: {e}") from e
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=capped)
    except asyncio.TimeoutError as e:
        try:
            proc.kill()
        finally:
            raise TimeoutError(f"{cmd[0]} timed out after {capped}s") from e
    out = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
    err = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
    if len(out) > MAX_OUTPUT_BYTES:
        out = out[:MAX_OUTPUT_BYTES] + f"\n... [truncated {len(out) - MAX_OUTPUT_BYTES} bytes]"
    return proc.returncode or 0, out, err


def _resolve_cwd(path: str | None) -> str | None:
    """Resolve a user-supplied path; return None if not given."""
    if path is None or path == "":
        return None
    try:
        return str(Path(path).expanduser().resolve())
    except (OSError, RuntimeError):
        return str(path)


__all__ = [
    "_run",
    "_resolve_cwd",
    "ToolNotFoundError",
    "MAX_TIMEOUT",
    "MAX_OUTPUT_BYTES",
]
