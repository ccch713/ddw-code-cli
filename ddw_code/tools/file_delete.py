"""`file_delete` — delete a file or empty directory (dangerous)."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..security.danger_check import is_forbidden_path


class FileDeleteError(RuntimeError):
    """Raised when a deletion cannot proceed."""


async def file_delete(path: str, recursive: bool = False) -> str:
    """Delete a file or (optionally) a directory tree at `path`.

    Args:
        path: Path to delete.
        recursive: If True and `path` is a directory, remove it and all its contents
                   (uses `shutil.rmtree`).

    Returns:
        Confirmation message.

    Raises:
        PermissionError: If the path is on the forbidden list.
        FileNotFoundError: If the path does not exist.
        FileDeleteError: For other failures (non-empty dir without recursive, etc.).
    """
    p = Path(path)
    if is_forbidden_path(p):
        raise PermissionError(f"refusing to delete forbidden path: {p}")
    if not p.exists():
        raise FileNotFoundError(f"no such path: {p}")
    try:
        if p.is_dir():
            if recursive:
                shutil.rmtree(p)
            else:
                # Refuse to remove a non-empty directory unless recursive.
                try:
                    p.rmdir()
                except OSError as e:
                    raise FileDeleteError(
                        f"directory not empty (use recursive=True to force): {p}"
                    ) from e
        else:
            p.unlink()
    except (PermissionError, FileNotFoundError):
        raise
    except FileDeleteError:
        raise
    except Exception as e:
        raise FileDeleteError(f"failed to delete {p}: {e}") from e
    return f"deleted {p}"


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File or directory to delete."},
            "recursive": {
                "type": "boolean",
                "description": "If path is a directory, remove it recursively (rmtree).",
                "default": False,
            },
        },
        "required": ["path"],
    }
