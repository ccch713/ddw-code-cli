"""`glob` — find files by glob pattern."""
from __future__ import annotations

from pathlib import Path
from typing import Any


async def glob(pattern: str, path: str = ".", max_results: int = 200) -> str:
    """Return files matching `pattern` under `path`.

    Args:
        pattern: Glob, e.g. `**/*.py`.
        path: Root directory (default `.`).
        max_results: Cap on the number of results.

    Returns:
        Newline-separated list of matched paths, sorted.
    """
    root = Path(path)
    if not root.exists():
        return f"path not found: {root}"
    matches = sorted(root.glob(pattern))
    if not matches:
        return "[no matches]"
    truncated = False
    if len(matches) > max_results:
        matches = matches[:max_results]
        truncated = True
    out = "\n".join(str(m) for m in matches)
    if truncated:
        out += f"\n... [truncated, {max_results}+ matches]"
    return out


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py'."},
            "path": {
                "type": "string",
                "description": "Root directory to search.",
                "default": ".",
            },
            "max_results": {
                "type": "integer",
                "description": "Max number of matches.",
                "default": 200,
                "minimum": 1,
            },
        },
        "required": ["pattern"],
    }
