"""`file_list` — list directory contents with optional pattern filter."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..security.danger_check import is_forbidden_path


async def file_list(
    path: str = ".",
    recursive: bool = False,
    pattern: str | None = None,
    include_hidden: bool = False,
    max_entries: int = 1000,
) -> str:
    """List files and directories under `path`.

    Args:
        path: Directory to list (default `.`).
        recursive: If True, walk the entire tree.
        pattern: Optional glob filter (e.g. `*.py`).
        include_hidden: If True, include dotfiles.
        max_entries: Stop after this many entries (output stays bounded).

    Returns:
        Newline-separated list of paths. Directories end with `/`.

    Raises:
        PermissionError: If `path` is on the forbidden list.
        FileNotFoundError: If `path` does not exist.
        NotADirectoryError: If `path` is a file.
    """
    p = Path(path)
    if is_forbidden_path(p):
        raise PermissionError(f"refusing to list forbidden path: {p}")
    if not p.exists():
        raise FileNotFoundError(f"no such path: {p}")
    if not p.is_dir():
        raise NotADirectoryError(f"not a directory: {p}")

    entries: list[str] = []

    def _matches(name: str) -> bool:
        if not pattern:
            return True
        return Path(name).match(pattern)

    def _visit(target: Path) -> None:
        if len(entries) >= max_entries:
            return
        try:
            it = os.scandir(target)
        except OSError:
            return
        try:
            for entry in it:
                if len(entries) >= max_entries:
                    break
                name = entry.name
                if not include_hidden and name.startswith("."):
                    continue
                if entry.is_dir():
                    # Recurse first so we can find matching files in subdirs.
                    if recursive:
                        _visit(Path(entry.path))
                    if _matches(name):
                        entries.append(f"{entry.path}/")
                else:
                    if _matches(name):
                        entries.append(entry.path)
        finally:
            it.close()

    _visit(p)
    if not entries:
        return "[no matches]"
    out = "\n".join(entries)
    if len(entries) >= max_entries:
        out += f"\n... [truncated at {max_entries} entries]"
    return out


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory to list (default current working directory).",
                "default": ".",
            },
            "recursive": {
                "type": "boolean",
                "description": "Walk the tree recursively.",
                "default": False,
            },
            "pattern": {
                "type": "string",
                "description": "Optional glob filter (e.g. '*.py').",
            },
            "include_hidden": {
                "type": "boolean",
                "description": "Include dotfiles.",
                "default": False,
            },
            "max_entries": {
                "type": "integer",
                "description": "Max number of entries to return.",
                "default": 1000,
                "minimum": 1,
            },
        },
    }
