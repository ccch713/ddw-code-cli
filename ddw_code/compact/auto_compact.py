"""auto-compact: LLM-driven summarisation when the conversation grows large.

Unlike `micro_compact` (which is a free, no-LLM operation that swaps tool
results for a placeholder), this module shells out to the configured
provider to produce a real summary of older turns.

The summarise callback is duck-typed (`async def summarise(prompt) -> str`).
Any object exposing that method works — the production wiring goes through
the Hub; tests can pass a stub.
"""
from __future__ import annotations

import copy
from typing import Any, Awaitable, Callable, Protocol

from .micro_compact import _approx_tokens, should_compact

# Default thresholds (override per-call if needed).
DEFAULT_THRESHOLD = 0.8
DEFAULT_KEEP_RECENT = 4


class Summariser(Protocol):
    """Anything that can turn a prompt into a summary string."""

    async def summarise(self, prompt: str) -> str:  # pragma: no cover - structural
        ...


def _build_summarise_prompt(messages: list[dict[str, Any]]) -> str:
    """Render a transcript into a prompt asking the model to summarise it."""
    parts: list[str] = [
        "You are compacting an old portion of a long conversation.",
        "Produce a faithful summary that preserves:",
        "- user goals and constraints",
        "- key file paths and code references",
        "- decisions taken and their rationale",
        "- any pending TODOs or open questions",
        "Be terse. Do not include pleasantries.",
        "",
        "Conversation transcript:",
    ]
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content")
        if isinstance(content, list):
            content = " ".join(
                str(b.get("text", b.get("content", "")))
                for b in content
                if isinstance(b, dict)
            )
        if not content:
            continue
        text = str(content)
        if len(text) > 2000:
            text = text[:2000] + "...[truncated]"
        parts.append(f"[{role}] {text}")
    return "\n".join(parts)


def _split(
    messages: list[dict[str, Any]],
    keep_recent: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (older, recent) where `recent` is the last `keep_recent` messages."""
    if keep_recent <= 0:
        return list(messages), []
    return list(messages[:-keep_recent]), list(messages[-keep_recent:])


class AutoCompact:
    """Run an LLM-driven compaction when the message list is too long."""

    def __init__(
        self,
        summariser: Summariser,
        threshold: float = DEFAULT_THRESHOLD,
        keep_recent: int = DEFAULT_KEEP_RECENT,
    ) -> None:
        self.summariser = summariser
        self.threshold = float(threshold)
        self.keep_recent = max(0, int(keep_recent))

    async def compact(
        self,
        messages: list[dict[str, Any]],
        context_window: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Compact `messages` if they exceed the threshold.

        Args:
            messages: The full conversation history.
            context_window: Model's context window size in tokens.

        Returns:
            (possibly-new message list, was_compacted).
        """
        if context_window <= 0:
            return messages, False
        if not should_compact(messages, context_window, threshold=self.threshold):
            return messages, False
        if len(messages) <= self.keep_recent + 1:
            return messages, False
        older, recent = _split(messages, self.keep_recent)
        prompt = _build_summarise_prompt(older)
        try:
            summary = await self.summariser.summarise(prompt)
        except Exception:  # provider down: leave messages alone
            return messages, False
        summary = (summary or "").strip()
        if not summary:
            return messages, False
        summary_msg: dict[str, Any] = {
            "role": "system",
            "content": (
                f"[auto-compact summary of {len(older)} earlier messages]\n"
                f"{summary}"
            ),
        }
        return [summary_msg, *recent], True


__all__ = [
    "AutoCompact",
    "Summariser",
    "DEFAULT_KEEP_RECENT",
    "DEFAULT_THRESHOLD",
    "auto_compact",
]


async def auto_compact(
    messages: list[dict[str, Any]],
    provider: Summariser | None = None,
    keep_recent: int = DEFAULT_KEEP_RECENT,
    threshold: float = DEFAULT_THRESHOLD,
    context_window: int = 1,
) -> list[dict[str, Any]]:
    """Backwards-compatible free-function form.

    Old callers passed a `provider` (anything `await`-able returning a
    string) and a `keep_recent` count. The new `AutoCompact` class is a
    thin wrapper around the same idea; this shim preserves the legacy
    signature for existing tests and tools.

    The legacy semantics are: if `provider` is given, ALWAYS compact
    (don't gate on threshold / context_window). If it's `None`, return
    the input unchanged.

    Args:
        messages: The full message list.
        provider: Optional summariser. `None` means "no compaction".
        keep_recent: How many recent messages to keep verbatim.
        threshold: Ignored in legacy mode; kept for signature compatibility.
        context_window: Ignored in legacy mode; kept for signature compatibility.
    """
    if provider is None:
        return messages
    if len(messages) <= keep_recent + 1:
        return messages
    older, recent = _split(messages, keep_recent)
    prompt = _build_summarise_prompt(older)
    try:
        summary = await provider.summarise(prompt)
    except Exception:  # provider down: leave messages alone
        return messages
    summary = (summary or "").strip()
    if not summary:
        return messages
    summary_msg: dict[str, Any] = {
        "role": "system",
        "content": (
            f"[auto-compact summary of {len(older)} earlier messages]\n"
            f"{summary}"
        ),
    }
    return [summary_msg, *recent]
