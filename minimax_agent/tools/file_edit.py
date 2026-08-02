"""`file_edit` — exact-string replace inside a file.

Fails if the target string is not found, or if it appears more than once
unless `replace_all=True` is set.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


class EditError(RuntimeError):
    """Raised when an edit cannot be applied."""


async def file_edit(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> str:
    """Replace `old_string` with `new_string` in `path`.

    Args:
        path: Path to the file to edit.
        old_string: The exact substring to find.
        new_string: The replacement.
        replace_all: If True, replace every occurrence. If False (default),
            require exactly one match.

    Returns:
        A short summary like "edited path (1 replacement)".

    Raises:
        EditError: if `old_string` is empty, not found, or ambiguous.
    """
    if not old_string:
        raise EditError("old_string must not be empty")
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"no such file: {p}")
    text = p.read_text(encoding="utf-8", errors="replace")
    count = text.count(old_string)
    if count == 0:
        raise EditError(f"old_string not found in {p}")
    if count > 1 and not replace_all:
        raise EditError(
            f"old_string matches {count} locations in {p}; pass replace_all=True to replace all"
        )
    if replace_all:
        new_text = text.replace(old_string, new_string)
        replacements = count
    else:
        new_text = text.replace(old_string, new_string, 1)
        replacements = 1
    p.write_text(new_text, encoding="utf-8")
    return f"edited {p} ({replacements} replacement{'s' if replacements != 1 else ''})"


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File to edit."},
            "old_string": {
                "type": "string",
                "description": "Exact substring to replace (must be unique unless replace_all).",
            },
            "new_string": {
                "type": "string",
                "description": "Replacement string.",
            },
            "replace_all": {
                "type": "boolean",
                "description": "Replace all occurrences instead of requiring uniqueness.",
                "default": False,
            },
        },
        "required": ["path", "old_string", "new_string"],
    }
