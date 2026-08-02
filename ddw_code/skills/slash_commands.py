"""Slash command handler.

A slash command (`/commit`, `/review`, etc.) maps to a skill by name.
The handler resolves `/foo` against the `SkillRegistry` and returns the
skill's instructions. An optional executor hook lets callers run the
skill in a custom way (e.g. push the instructions into the prompt
context, or run them via a sub-agent).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

from .registry import SkillRegistry


_SLASH_RX = re.compile(r"^/([A-Za-z0-9_\-\.]+)\b(.*)$")


class SkillExecutor(Protocol):
    """Anything that can take a skill's instructions and return output text."""

    async def execute(self, name: str, instructions: str, args: str) -> str:  # pragma: no cover
        ...


class _DefaultExecutor:
    """Default executor: returns the skill's rendered instructions.

    The real production executor would feed `instructions` into a sub-agent
    or prepend them to the next user turn. For local use, simply surfacing
    the text is enough.
    """

    async def execute(self, name: str, instructions: str, args: str) -> str:
        tail = f"\n\nArgs: {args.strip()}" if args.strip() else ""
        return f"## /{name}{tail}\n\n{instructions.strip()}"


@dataclass
class SlashCommands:
    """Resolve `/command` strings to skills."""

    registry: SkillRegistry
    executor: SkillExecutor | None = None

    def __post_init__(self) -> None:
        if self.executor is None:
            self.executor = _DefaultExecutor()

    @staticmethod
    def is_slash_command(text: str) -> bool:
        return bool(_SLASH_RX.match((text or "").lstrip()))

    async def handle(self, command: str) -> str | None:
        """Resolve a slash command, or return None if it isn't one.

        Args:
            command: A user-typed line, expected to start with `/`.

        Returns:
            The executor's output, or `None` if the command isn't a slash
            command / the skill isn't registered.
        """
        if not command:
            return None
        m = _SLASH_RX.match(command.lstrip())
        if not m:
            return None
        name = m.group(1)
        args = m.group(2).strip()
        skill = self.registry.get(name)
        if skill is None:
            return f"/{name}: no such skill"
        assert self.executor is not None
        return await self.executor.execute(name, skill.instructions, args)

    def list_commands(self) -> list[str]:
        """Return the names of all registered slash commands."""
        return [f"/{s.name}" for s in self.registry.all()]


__all__ = ["SlashCommands", "SkillExecutor", "_DefaultExecutor"]
