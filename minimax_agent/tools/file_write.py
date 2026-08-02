"""`file_write` — write content to a file, creating parent dirs if needed."""
from __future__ import annotations

from pathlib import Path
from typing import Any


async def file_write(path: str, content: str) -> str:
    """Write `content` to `path`, overwriting any existing file.

    Creates parent directories as needed. Writes as UTF-8.
    Returns a short confirmation message.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} bytes to {p}"


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Destination file path."},
            "content": {"type": "string", "description": "Full file content to write."},
        },
        "required": ["path", "content"],
    }
