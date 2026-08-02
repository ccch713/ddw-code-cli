"""`bash` — execute a shell command, capture output, enforce timeout."""
from __future__ import annotations

import asyncio
import os
import shlex
from typing import Any

from ..security.danger_check import is_dangerous_command

# Hard cap to prevent runaway commands.
MAX_TIMEOUT = 600  # 10 minutes
MAX_OUTPUT_BYTES = 50_000  # truncate overlong output


class BashError(RuntimeError):
    """Raised when a shell command exits non-zero or times out."""


async def bash(command: str, timeout: int = 60) -> str:
    """Run `command` in a subshell and return combined output.

    Args:
        command: Shell command string.
        timeout: Max seconds to wait. Capped at 600.

    Returns:
        Combined stdout+stderr. Non-zero exit codes do not raise; the exit
        code is appended to the output. The caller can decide what to do.

    Raises:
        BashError: only for timeout or dangerous command refusal.
    """
    if is_dangerous_command(command):
        raise BashError(
            f"refused to run dangerous command: {command[:120]!r}\n"
            "If this is intentional, run it manually outside the agent."
        )
    capped_timeout = min(int(timeout), MAX_TIMEOUT)
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "LC_ALL": "C.UTF-8"},
        )
    except Exception as e:
        raise BashError(f"failed to spawn: {e}") from e
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=capped_timeout)
    except asyncio.TimeoutError as e:
        try:
            proc.kill()
        finally:
            raise BashError(f"command timed out after {capped_timeout}s") from e
    text = stdout.decode("utf-8", errors="replace") if stdout else ""
    if len(text) > MAX_OUTPUT_BYTES:
        text = text[:MAX_OUTPUT_BYTES] + f"\n... [truncated {len(text) - MAX_OUTPUT_BYTES} bytes]"
    rc = proc.returncode
    if rc != 0:
        text = f"{text}\n[exit code {rc}]"
    return text or "[no output]"


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute."},
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (max 600).",
                "default": 60,
                "minimum": 1,
                "maximum": 600,
            },
        },
        "required": ["command"],
    }


# Re-export shlex so tests can use it without re-importing.
__all__ = ["bash", "BashError", "schema", "shlex"]
