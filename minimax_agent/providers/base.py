"""Abstract model provider interface.

Concrete providers (e.g. MiniMax, OpenAI) implement `chat` to stream tokens
and tool calls back to the agent loop.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolUseBlock:
    """A single tool-use request emitted by the model."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class Usage:
    """Token usage returned by the provider."""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class StreamEvent:
    """One event from a streaming chat response.

    A turn yields a sequence of these. `text_delta` is the incremental text
    chunk; `tool_use` is the final assembled tool call (emitted once per tool
    when the model finishes streaming arguments); `done` signals end-of-turn;
    `usage` is emitted at the end with the final token counts.
    """

    text_delta: str | None = None
    tool_use: ToolUseBlock | None = None
    usage: Usage | None = None
    stop_reason: str | None = None
    error: str | None = None
    # Coalesced final assistant message (filled in for convenience at `done`).
    final_text: str = ""

    def __post_init__(self) -> None:
        # Coalesce incremental text so consumers can read the full message.
        if self.text_delta:
            self.final_text = (self.final_text or "") + self.text_delta


@dataclass
class ChatRequest:
    """A request to the model."""

    system: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    model: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.2


class ModelProvider(ABC):
    """Pluggable LLM provider.

    Implementations must yield `StreamEvent`s in order, ending with an event
    whose `stop_reason` is set. Errors should yield a single event with
    `error` set and `stop_reason="error"`.
    """

    name: str = "base"

    @abstractmethod
    async def chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        """Stream a chat completion. Must be an async generator."""
        raise NotImplementedError

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Approximate token count for a piece of text."""
        raise NotImplementedError
