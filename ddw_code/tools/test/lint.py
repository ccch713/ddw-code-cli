"""`lint` — run ruff over a file or directory."""
from __future__ import annotations

from typing import Any

from ._helpers import ToolNotFoundError, _resolve_cwd, _run


async def lint(
    path: str | None = None,
    fix: bool = False,
    timeout: int = 60,
) -> str:
    """Run `ruff check` (optionally with `--fix`) on `path`.

    Args:
        path: File or directory to lint. `None` means the current directory.
        fix: If True, pass `--fix` to auto-fix what's safe.
        timeout: Max seconds.

    Returns:
        Ruff output (empty stdout means no issues). Errors are prefixed.
    """
    cwd = _resolve_cwd(path)
    args: list[str] = ["ruff", "check", "--no-fix" if not fix else "--fix"]
    if path:
        args.append(path)
    try:
        rc, out, err = await _run(args, cwd=cwd, timeout=timeout)
    except ToolNotFoundError as e:
        return f"lint error: {e}"
    except TimeoutError as e:
        return f"lint error: {e}"
    text = (out or "").rstrip()
    if err.strip() and rc != 0 and not text:
        text = err.strip()
    if rc == 0 and not text:
        return "lint: no issues"
    return f"lint exit={rc}\n{text}"


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File or directory to lint. Defaults to current directory.",
            },
            "fix": {
                "type": "boolean",
                "description": "Pass --fix to auto-fix safe issues.",
                "default": False,
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
