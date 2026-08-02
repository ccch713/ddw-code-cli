"""`file_move` — move or rename a file or directory (dangerous)."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..security.danger_check import is_forbidden_path


class FileMoveError(RuntimeError):
    """Raised when a move operation cannot proceed."""


async def file_move(src: str, dst: str, overwrite: bool = False) -> str:
    """Move `src` to `dst`.

    Args:
        src: Source path.
        dst: Destination path.
        overwrite: If True, allow replacing an existing file at `dst`. If False, refuse.

    Returns:
        Confirmation message.

    Raises:
        PermissionError: If either path is on the forbidden list.
        FileNotFoundError: If `src` does not exist.
        FileMoveError: For other failures (e.g. destination exists and overwrite=False).
    """
    src_p = Path(src)
    dst_p = Path(dst)
    if is_forbidden_path(src_p) or is_forbidden_path(dst_p):
        raise PermissionError(
            f"refusing to move forbidden path: {src_p} -> {dst_p}"
        )
    if not src_p.exists():
        raise FileNotFoundError(f"no such source: {src_p}")
    if dst_p.exists() and not overwrite:
        raise FileMoveError(f"destination already exists: {dst_p} (use overwrite=True to force)")
    try:
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_p), str(dst_p))
    except (PermissionError, FileNotFoundError, FileMoveError):
        raise
    except Exception as e:
        raise FileMoveError(f"failed to move {src_p} -> {dst_p}: {e}") from e
    return f"moved {src_p} -> {dst_p}"


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "src": {"type": "string", "description": "Source path."},
            "dst": {"type": "string", "description": "Destination path."},
            "overwrite": {
                "type": "boolean",
                "description": "Overwrite an existing destination.",
                "default": False,
            },
        },
        "required": ["src", "dst"],
    }
