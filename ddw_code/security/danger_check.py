"""Danger detection for shell commands and file paths.

Two responsibilities:
- `is_dangerous_command` flags known destructive shell patterns.
- `is_forbidden_path` flags reads outside the agent's allowed scope.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..config import FORBIDDEN_PATH_PREFIXES

# Patterns that always require extra confirmation.
_DANGEROUS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)?/\s*$"),  # rm -rf /
    re.compile(r"\brm\s+-[a-zA-Z]*[rf][a-zA-Z]*\b.*\*"),  # rm -rf with glob
    re.compile(r"\bgit\s+push\s+(-f|--force(-with-lease)?)?"),  # any force push
    re.compile(r"\bgit\s+reset\s+--hard\b"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bdd\s+if=.*of=/dev/(sd|hd|nvme|disk)"),  # disk wipe
    re.compile(r":\(\)\s*\{.*\};:"),  # fork bomb
    re.compile(r"\bmkfs(\.[a-z0-9]+)?\b"),  # format filesystem
    re.compile(r"\b(shutdown|reboot|halt|poweroff)\b"),
    re.compile(r"\bchmod\s+(-R\s+)?777\s+/\s*$"),
    re.compile(r"\bcurl\s+.*\|\s*(sudo\s+)?(sh|bash)\b"),  # curl|sh
    re.compile(r"\b(>\s*/dev/sd[a-z]|>\s*/dev/nvme)"),  # raw disk redirect
    re.compile(r"\beval\s+.*\$\((curl|wget)"),  # remote code eval
)

# Safe prefixes / commands that bypass the heuristic.
_SAFE_PREFIXES: tuple[str, ...] = (
    "ls ",
    "pwd",
    "echo ",
    "cat ",
    "head ",
    "tail ",
    "grep ",
    "rg ",
    "find ",
    "wc ",
    "git status",
    "git log",
    "git diff",
    "git show",
    "git branch",
)


def is_dangerous_command(command: str) -> bool:
    """Return True if `command` matches a known destructive pattern.

    Read-only / reversible commands return False.
    """
    cmd = command.strip()
    if not cmd:
        return False
    for safe in _SAFE_PREFIXES:
        if cmd.startswith(safe):
            return False
    for pat in _DANGEROUS_PATTERNS:
        if pat.search(cmd):
            return True
    return False


def is_forbidden_path(path: str | Path) -> bool:
    """Return True if `path` resolves to a sensitive location we should never read.

    The check is purely on the absolute path — it does not validate that
    the file exists.
    """
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        return True
    resolved_str = str(resolved)
    for prefix in FORBIDDEN_PATH_PREFIXES:
        # Allow skipping the check if the prefix itself doesn't exist.
        if not prefix:
            continue
        # Use commonpath to avoid `~/.ssh2` matching `~/.ssh`.
        try:
            if resolved == Path(prefix).resolve() or resolved.is_relative_to(
                Path(prefix).resolve()
            ):
                return True
        except (OSError, ValueError):
            # Fall back to string-prefix check.
            if resolved_str.startswith(prefix.rstrip("/") + "/") or resolved_str == prefix:
                return True
    return False


def find_ripgrep() -> str | None:
    """Return the path to `rg` if available, else None."""
    return shutil.which("rg")
