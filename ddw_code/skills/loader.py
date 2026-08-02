"""Skill loading and representation.

A "skill" is a Markdown file with YAML frontmatter. The frontmatter carries
metadata (name, description, triggers, etc.); the Markdown body becomes the
instructions the agent follows when the skill is invoked.

The loader is deliberately permissive about missing fields — it surfaces
problems in the returned object rather than raising, so the calling tool
can decide what to do.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Matches `---\n...\n---\n` at the start of a file.
_FRONTMATTER_RX = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
# One frontmatter line: `key: value` or `key: [a, b]`.
_KV_LINE = re.compile(r"^(?P<key>[A-Za-z0-9_\-]+)\s*:\s*(?P<value>.*)$")


@dataclass
class Skill:
    """A loaded skill."""

    name: str
    description: str
    instructions: str
    triggers: list[str] = field(default_factory=list)
    source: str = ""
    raw_frontmatter: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        """Return a prompt-ready rendering of the skill."""
        trig = ", ".join(self.triggers) if self.triggers else "(no triggers)"
        return (
            f"## Skill: {self.name}\n"
            f"Description: {self.description}\n"
            f"Triggers: {trig}\n\n"
            f"{self.instructions.strip()}"
        )


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a Markdown file into (frontmatter_dict, body).

    Missing / malformed frontmatter yields an empty dict.
    """
    m = _FRONTMATTER_RX.match(text)
    if not m:
        return {}, text
    raw, body = m.group(1), m.group(2)
    out: dict[str, str] = {}
    for line in raw.splitlines():
        km = _KV_LINE.match(line.strip())
        if not km:
            continue
        out[km.group("key")] = km.group("value").strip()
    return out, body


def _parse_list_value(value: str) -> list[str]:
    """Parse a YAML-ish list value: `[a, b]`, `a, b`, or `a`."""
    v = (value or "").strip()
    if not v:
        return []
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1]
        return [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
    if "," in v:
        return [x.strip() for x in v.split(",") if x.strip()]
    return [v]


def parse_skill(text: str, source: str = "") -> Skill:
    """Parse a skill from raw Markdown text.

    Args:
        text: The full Markdown file contents.
        source: Optional path (for error messages and traceability).

    Returns:
        A `Skill`. `name` defaults to the file stem if missing in the
        frontmatter; `description` is empty if missing.
    """
    front, body = _parse_frontmatter(text)
    name = front.get("name") or ""
    if not name and source:
        name = Path(source).stem
    description = front.get("description", "")
    triggers = _parse_list_value(front.get("triggers", ""))
    return Skill(
        name=name or "(unnamed)",
        description=description,
        instructions=body.strip(),
        triggers=triggers,
        source=source,
        raw_frontmatter=front,
    )


def load_skill(path: str | Path) -> Skill:
    """Read and parse a single skill from disk.

    Raises:
        FileNotFoundError: If `path` doesn't exist.
        OSError: On any other I/O error.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"no such skill file: {p}")
    text = p.read_text(encoding="utf-8", errors="replace")
    return parse_skill(text, source=str(p))


__all__ = ["Skill", "parse_skill", "load_skill"]
