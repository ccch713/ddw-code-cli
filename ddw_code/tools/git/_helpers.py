"""Shared helpers for the Git tools.

All Git tools ultimately wrap `git <subcommand>` invocations. Centralising
the spawn logic keeps each individual tool small and consistent.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

# Hard cap to prevent runaway git commands (clone of a huge repo, etc.).
MAX_TIMEOUT = 120  # seconds
MAX_OUTPUT_BYTES = 50_000


class GitError(RuntimeError):
    """Raised when a git subcommand fails or git itself is unavailable."""


async def _run_git(
    args: list[str],
    cwd: str | None = None,
    timeout: int = 30,
    *,
    check: bool = False,
) -> tuple[int, str, str]:
    """Run a git subcommand and return (returncode, stdout, stderr).

    Args:
        args: Git subcommand and arguments (without the leading `git`).
        cwd: Working directory. Defaults to current working directory.
        timeout: Max seconds to wait.
        check: If True, raise GitError on non-zero exit.

    Returns:
        Tuple of (returncode, stdout_text, stderr_text).

    Raises:
        GitError: When git is not installed, the timeout elapses, or `check` is True and the command fails.
    """
    capped_timeout = min(int(timeout), MAX_TIMEOUT)
    full = ["git", *args]
    try:
        proc = await asyncio.create_subprocess_exec(
            *full,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "LC_ALL": "C.UTF-8"},
        )
    except FileNotFoundError as e:
        raise GitError("git executable not found in PATH") from e
    except Exception as e:
        raise GitError(f"failed to spawn git: {e}") from e
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=capped_timeout)
    except asyncio.TimeoutError as e:
        try:
            proc.kill()
        finally:
            raise GitError(f"git command timed out after {capped_timeout}s") from e
    out = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
    err = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
    if len(out) > MAX_OUTPUT_BYTES:
        out = out[:MAX_OUTPUT_BYTES] + f"\n... [truncated {len(out) - MAX_OUTPUT_BYTES} bytes]"
    rc = proc.returncode or 0
    if check and rc != 0:
        raise GitError(f"git {' '.join(args)} failed (rc={rc}): {err.strip() or out.strip()}")
    return rc, out, err


def _resolve_cwd(path: str | None) -> str | None:
    """Resolve a user-supplied path; return None if not given.

    The returned path is normalised but not required to exist — git itself
    will report a useful error.
    """
    if path is None or path == "":
        return None
    try:
        return str(Path(path).expanduser().resolve())
    except (OSError, RuntimeError):
        return str(path)


__all__ = ["GitError", "_run_git", "_resolve_cwd", "MAX_TIMEOUT", "MAX_OUTPUT_BYTES"]
