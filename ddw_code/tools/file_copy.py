"""`file_copy` — copy a file to a new path (preserves metadata)."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..security.danger_check import is_forbidden_path


class FileCopyError(RuntimeError):
    """Raised when a copy operation cannot proceed."""


async def file_copy(src: str, dst: str, overwrite: bool = False) -> str:
    """Copy `src` to `dst`, preserving metadata.

    Args:
        src: Source file path.
        dst: Destination path.
        overwrite: If True, allow replacing an existing file at `dst`.

    Returns:
        Confirmation message.

    Raises:
        PermissionError: If either path is on the forbidden list.
        FileNotFoundError: If `src` does not exist.
        FileCopyError: For other failures.
    """
    src_p = Path(src)
    dst_p = Path(dst)
    if is_forbidden_path(src_p) or is_forbidden_path(dst_p):
        raise PermissionError(
            f"refusing to copy forbidden path: {src_p} -> {dst_p}"
        )
    if not src_p.exists():
        raise FileNotFoundError(f"no such source: {src_p}")
    if not src_p.is_file():
        raise FileCopyError(f"source is not a regular file: {src_p}")
    if dst_p.exists() and not overwrite:
        raise FileCopyError(f"destination already exists: {dst_p} (use overwrite=True to force)")
    try:
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src_p), str(dst_p))
    except (PermissionError, FileNotFoundError, FileCopyError):
        raise
    except Exception as e:
        raise FileCopyError(f"failed to copy {src_p} -> {dst_p}: {e}") from e
    return f"copied {src_p} -> {dst_p}"


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "src": {"type": "string", "description": "Source file path."},
            "dst": {"type": "string", "description": "Destination file path."},
            "overwrite": {
                "type": "boolean",
                "description": "Overwrite an existing destination.",
                "default": False,
            },
        },
        "required": ["src", "dst"],
    }
