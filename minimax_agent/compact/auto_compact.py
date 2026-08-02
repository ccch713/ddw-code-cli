"""auto-compact: LLM-summarized compression (skeleton).

When micro-compact isn't enough (e.g. very long sessions, the model
keeps emitting large tool results that compress poorly), this layer
asks the LLM to summarize the oldest portion of the conversation.

Skeleton only — full implementation is out of scope for v0.1. The
hook is exposed so the turn loop can call it as a second-stage
fallback after micro-compact.
"""
from __future__ import annotations

from typing import Any

from ..providers.base import ChatRequest, ModelProvider


async def auto_compact(
    messages: list[dict[str, Any]],
    provider: ModelProvider,
    *,
    keep_recent: int = 10,
    model: str | None = None,
) -> list[dict[str, Any]]:
    """Ask `provider` to summarize the oldest messages and return a shorter list.

    Args:
        messages: The full conversation to compact.
        provider: LLM provider used to produce the summary.
        keep_recent: How many most-recent messages to preserve verbatim.
        model: Override the model name (defaults to provider default).

    Returns:
        A new message list with the oldest portion collapsed into a
        single "summary" message.

    Implementation note:
        v0.1 returns the input unchanged with a marker. The full
        implementation will run a summarization call and splice the
        result in.
    """
    if len(messages) <= keep_recent:
        return messages
    # Placeholder: prepend a system note. The real version will replace
    # `messages[:-keep_recent]` with a model-generated summary.
    head = messages[:-keep_recent]
    tail = messages[-keep_recent:]
    summary_message: dict[str, Any] = {
        "role": "system",
        "content": (
            "[auto-compact] Earlier turns have been summarized for context budget. "
            f"({len(head)} messages collapsed)"
        ),
    }
    return [summary_message, *tail]


__all__ = ["auto_compact", "ChatRequest"]
