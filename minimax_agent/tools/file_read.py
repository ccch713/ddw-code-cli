"""`file_read` — read a slice of a file from disk.

Supports `offset` (1-indexed line number) and `limit` (max lines).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..security.danger_check import is_forbidden_path


async def file_read(
    path: str,
    offset: int | None = None,
    limit: int | None = None,
) -> str:
    """Read `path` and return its contents (optionally a slice).

    Args:
        path: Absolute or workspace-relative path to a text file.
        offset: 1-indexed starting line. `None` means start of file.
        limit: Max number of lines to return. `None` means all.

    Returns:
        The file contents as a string, with a header line if `offset` is set.

    Raises:
        FileNotFoundError: if the path does not exist.
        PermissionError: if the path is on the forbidden list.
        IsADirectoryError: if the path is a directory.
    """
    p = Path(path)
    if is_forbidden_path(p):
        raise PermissionError(f"refusing to read forbidden path: {p}")
    if not p.exists():
        raise FileNotFoundError(f"no such file: {p}")
    if p.is_dir():
        raise IsADirectoryError(f"is a directory: {p}")
    # Read as text; cap absurdly large files at 200k chars to keep the model safe.
    raw = p.read_text(encoding="utf-8", errors="replace")
    if len(raw) > 200_000:
        raw = raw[:200_000] + "\n... [truncated]"
    if offset is None and limit is None:
        return raw
    lines = raw.splitlines()
    start = max(1, int(offset or 1)) - 1
    end = start + int(limit) if limit else len(lines)
    chunk = lines[start:end]
    header = f"[{path} lines {start + 1}-{start + len(chunk)}/{len(lines)}]\n"
    return header + "\n".join(chunk)


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to read."},
            "offset": {
                "type": "integer",
                "description": "1-indexed starting line number.",
                "minimum": 1,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to return.",
                "minimum": 1,
            },
        },
        "required": ["path"],
    }
