"""`find` — find files by name pattern, with optional file/dir type filter."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from ..security.danger_check import is_forbidden_path


async def find(
    pattern: str,
    path: str = ".",
    type: Literal["file", "dir", "both"] = "both",
    max_results: int = 200,
) -> str:
    """Find files/directories under `path` whose name matches `pattern`.

    Args:
        pattern: Substring or glob (e.g. `*.py`, `README*`).
        path: Root directory (default `.`).
        type: Restrict the kind of entry returned.
        max_results: Cap on results.

    Returns:
        Newline-separated paths, or a friendly empty message.
    """
    if not pattern or not pattern.strip():
        return "find error: pattern must not be empty"
    p = Path(path)
    if is_forbidden_path(p):
        return f"find error: forbidden path: {p}"
    if not p.exists():
        return f"find error: no such path: {p}"
    if not p.is_dir():
        return f"find error: not a directory: {p}"

    # Use glob if the pattern looks like one, otherwise substring match.
    use_glob = any(c in pattern for c in "*?[")
    matches: list[str] = []
    if use_glob:
        for entry in p.rglob(pattern):
            if len(matches) >= max_results:
                break
            if not _matches_type(entry, type):
                continue
            matches.append(str(entry))
    else:
        needle = pattern.lower()
        for root, dirs, files in os.walk(p):
            # Substring match against both dirs and files.
            for d in dirs:
                if needle in d.lower():
                    full = os.path.join(root, d)
                    if type in {"dir", "both"}:
                        matches.append(full + "/")
                        if len(matches) >= max_results:
                            return _finalise(matches, max_results)
            for f in files:
                if needle in f.lower():
                    full = os.path.join(root, f)
                    if type in {"file", "both"}:
                        matches.append(full)
                        if len(matches) >= max_results:
                            return _finalise(matches, max_results)
    return _finalise(matches, max_results)


def _matches_type(entry: Path, type: str) -> bool:
    if type == "both":
        return True
    if type == "dir":
        return entry.is_dir()
    if type == "file":
        return entry.is_file()
    return True


def _finalise(matches: list[str], max_results: int) -> str:
    if not matches:
        return "[no matches]"
    out = "\n".join(matches)
    if len(matches) >= max_results:
        out += f"\n... [truncated at {max_results} matches]"
    return out


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Substring or glob pattern (e.g. '*.py', 'README*').",
            },
            "path": {
                "type": "string",
                "description": "Root directory (default current working directory).",
                "default": ".",
            },
            "type": {
                "type": "string",
                "enum": ["file", "dir", "both"],
                "description": "Restrict to files, directories, or both.",
                "default": "both",
            },
            "max_results": {
                "type": "integer",
                "description": "Max number of results to return.",
                "default": 200,
                "minimum": 1,
            },
        },
        "required": ["pattern"],
    }
