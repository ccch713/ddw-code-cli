"""Tool registry: declares each tool's name, description, input schema, and handler."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

# JSON schema (subset of Draft 7) describing the tool's input arguments.
InputSchema = dict[str, Any]
# A tool handler is an async function taking validated kwargs and returning a string.
ToolHandler = Callable[..., Awaitable[str]]


@dataclass(frozen=True)
class Tool:
    """A single tool that the agent can invoke.

    The schema follows the OpenAI `tools[].function.parameters` shape so it can
    be passed through the provider adapter without translation.
    """

    name: str
    description: str
    input_schema: InputSchema
    handler: ToolHandler
    # Whether the tool is safe to invoke without an explicit user confirmation.
    # Tools that mutate state or have side effects set this False.
    requires_confirmation: bool = False
    # Marked True for tools whose output is safe to micro-compact.
    compactable: bool = False


class ToolRegistry:
    """In-memory registry mapping tool name -> Tool."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as e:
            raise KeyError(f"unknown tool: {name!r}") from e

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        """Return OpenAI-style tool definitions for the LLM."""
        out: list[dict[str, Any]] = []
        for t in self.all():
            out.append(
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
            )
        return out

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
