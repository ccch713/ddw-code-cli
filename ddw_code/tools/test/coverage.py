"""`coverage` — run pytest with coverage and return a summary."""
from __future__ import annotations

import re
from typing import Any

from ._helpers import ToolNotFoundError, _resolve_cwd, _run


# `coverage report -m` lines look like:
#   Name                 Stmts   Miss  Cover   Missing
#   --------------------------------------------------
#   ddw_code/cli.py         42     17    60%   12-25, 30
_COVER_LINE = re.compile(r"^(?P<file>\S+)\s+(?P<stmts>\d+)\s+(?P<miss>\d+)\s+(?P<pct>\d+)%\s*(?P<missing>.*)$")
_TOTAL_LINE = re.compile(r"^TOTAL\s+(?P<stmts>\d+)\s+(?P<miss>\d+)\s+(?P<pct>\d+)%")


async def coverage(
    path: str | None = None,
    source: str | None = None,
    timeout: int = 240,
) -> str:
    """Run pytest with coverage and return a short report.

    Args:
        path: Test path (passed to pytest). Defaults to current directory.
        source: Source path to measure coverage against. Defaults to the package containing the tests.
        timeout: Max seconds.

    Returns:
        Coverage report (last 30 lines) plus the total percentage.
    """
    cwd = _resolve_cwd(path)
    args: list[str] = ["pytest", "--cov", "--cov-report=term", "-q"]
    if source:
        args.extend(["--cov", source])
    elif path:
        args[-1] = path
    try:
        rc, out, err = await _run(args, cwd=cwd, timeout=timeout)
    except ToolNotFoundError as e:
        return f"coverage error: {e}"
    except TimeoutError as e:
        return f"coverage error: {e}"
    text = (out or err or "").rstrip()
    total_pct: int | None = None
    for line in text.splitlines():
        m = _TOTAL_LINE.match(line.strip())
        if m:
            total_pct = int(m.group("pct"))
            break
    head = f"coverage exit={rc}"
    if total_pct is not None:
        head += f" total={total_pct}%"
    else:
        head += " total=?%"
    tail = "\n".join(text.splitlines()[-30:])
    return f"{head}\n{tail}".rstrip()


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Test path passed to pytest. Defaults to current directory.",
            },
            "source": {
                "type": "string",
                "description": "Source path to measure coverage against.",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds.",
                "default": 240,
                "minimum": 30,
                "maximum": 300,
            },
        },
    }
