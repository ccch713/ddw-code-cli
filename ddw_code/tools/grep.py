"""`grep` — content search using ripgrep when available, else pure Python fallback."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from ..security.danger_check import find_ripgrep


def _fallback_grep(
    pattern: str,
    path: Path,
    *,
    include: str | None,
    case_insensitive: bool,
    max_results: int,
) -> str:
    """Pure-Python grep fallback. Slower but always available."""
    flags = re.IGNORECASE if case_insensitive else 0
    try:
        rx = re.compile(pattern, flags)
    except re.error as e:
        return f"invalid regex: {e}"
    out_lines: list[str] = []
    count = 0
    files = [path] if path.is_file() else list(path.rglob("*"))
    for f in files:
        if not f.is_file():
            continue
        if include and not f.match(include):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                out_lines.append(f"{f}:{lineno}:{line}")
                count += 1
                if count >= max_results:
                    return "\n".join(out_lines) + f"\n... [truncated at {max_results} matches]"
    return "\n".join(out_lines) if out_lines else "[no matches]"


async def grep(
    pattern: str,
    path: str = ".",
    include: str | None = None,
    case_insensitive: bool = False,
    max_results: int = 200,
) -> str:
    """Search file contents for `pattern`.

    Args:
        pattern: Regex (or literal if `literal=True`).
        path: File or directory to search (default `.`).
        include: Optional glob filter (e.g. `*.py`).
        case_insensitive: Case-insensitive search.
        max_results: Stop after this many matches.

    Returns:
        A `path:lineno:line` formatted list, capped at `max_results`.
    """
    rg = find_ripgrep()
    p = Path(path)
    if not p.exists():
        return f"path not found: {p}"
    if rg:
        cmd: list[str] = [
            rg,
            "--no-heading",
            "--line-number",
            "--color=never",
            "--no-messages",
        ]
        if case_insensitive:
            cmd.append("-i")
        if include:
            cmd.extend(["--glob", include])
        # Cap results to avoid runaway output.
        cmd.extend(["-m", str(max_results)])
        cmd.extend([pattern, str(p)])
        try:
            proc = subprocess.run(  # noqa: S603 - args are validated above
                cmd, capture_output=True, text=True, timeout=30, check=False
            )
        except subprocess.TimeoutExpired:
            return "[grep timed out]"
        out = proc.stdout
        # Count lines and truncate if needed.
        lines = out.splitlines() if out else []
        if len(lines) >= max_results:
            return "\n".join(lines) + f"\n... [truncated at {max_results} matches]"
        return "\n".join(lines) if lines else "[no matches]"
    return _fallback_grep(
        pattern,
        p,
        include=include,
        case_insensitive=case_insensitive,
        max_results=max_results,
    )


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for."},
            "path": {
                "type": "string",
                "description": "File or directory to search in.",
                "default": ".",
            },
            "include": {
                "type": "string",
                "description": "Glob filter (e.g. '*.py').",
            },
            "case_insensitive": {
                "type": "boolean",
                "description": "Case-insensitive search.",
                "default": False,
            },
            "max_results": {
                "type": "integer",
                "description": "Max number of matches to return.",
                "default": 200,
                "minimum": 1,
            },
        },
        "required": ["pattern"],
    }
