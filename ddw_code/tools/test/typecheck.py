"""`typecheck` — run mypy over a file or directory."""
from __future__ import annotations

import re
from typing import Any

from ._helpers import ToolNotFoundError, _resolve_cwd, _run


# mypy prints lines like "file.py:12: error: Name 'x' is not defined [name-defined]".
_ERROR_LINE = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+)(?::(?P<col>\d+))?:\s*error:\s*(?P<msg>.*)$")


async def typecheck(
    path: str | None = None,
    ignore_missing_imports: bool = True,
    timeout: int = 120,
) -> str:
    """Run mypy against `path` (default: current directory).

    Args:
        path: File or directory to type-check.
        ignore_missing_imports: Pass --ignore-missing-imports (handy for third-party libs).
        timeout: Max seconds.

    Returns:
        Formatted type-check output. Exit 0 with empty body means "no errors".
    """
    cwd = _resolve_cwd(path)
    args: list[str] = ["mypy", "--no-color-output", "--show-error-codes"]
    if ignore_missing_imports:
        args.append("--ignore-missing-imports")
    if path:
        args.append(path)
    try:
        rc, out, err = await _run(args, cwd=cwd, timeout=timeout)
    except ToolNotFoundError as e:
        return f"typecheck error: {e}"
    except TimeoutError as e:
        return f"typecheck error: {e}"
    text = (out or err or "").rstrip()
    # Count error lines for a quick at-a-glance summary.
    err_count = sum(1 for line in text.splitlines() if _ERROR_LINE.match(line))
    if rc == 0 and not text:
        return "typecheck: no errors"
    return f"typecheck exit={rc} errors={err_count}\n{text}"


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File or directory to type-check. Defaults to current directory.",
            },
            "ignore_missing_imports": {
                "type": "boolean",
                "description": "Pass --ignore-missing-imports.",
                "default": True,
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds.",
                "default": 120,
                "minimum": 10,
                "maximum": 300,
            },
        },
    }
