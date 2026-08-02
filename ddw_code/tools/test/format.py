"""`format` — run `ruff format` over a file or directory."""
from __future__ import annotations

from typing import Any

from ._helpers import ToolNotFoundError, _resolve_cwd, _run


async def format_code(
    path: str | None = None,
    check_only: bool = True,
    timeout: int = 60,
) -> str:
    """Format `path` with `ruff format`.

    Args:
        path: File or directory to format. `None` means current directory.
        check_only: If True, only check formatting (--check) and don't modify files.
        timeout: Max seconds.

    Returns:
        Ruff format output.
    """
    cwd = _resolve_cwd(path)
    args: list[str] = ["ruff", "format"]
    if check_only:
        args.append("--check")
    if path:
        args.append(path)
    try:
        rc, out, err = await _run(args, cwd=cwd, timeout=timeout)
    except ToolNotFoundError as e:
        return f"format error: {e}"
    except TimeoutError as e:
        return f"format error: {e}"
    text = (out or err or "").rstrip()
    if rc == 0 and not text:
        return "format: already formatted"
    verb = "checked" if check_only else "formatted"
    return f"format exit={rc} ({verb})\n{text}".rstrip()


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File or directory to format. Defaults to current directory.",
            },
            "check_only": {
                "type": "boolean",
                "description": "If True, only check formatting (--check), don't modify files.",
                "default": True,
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds.",
                "default": 60,
                "minimum": 5,
                "maximum": 300,
            },
        },
    }
