"""micro-compact: zero-LLM context compression.

When the conversation crosses 60% of the model's context window, replace
older tool results with a `[已压缩]` placeholder to free space. The
most recent `keep_recent` tool results are preserved verbatim.

Pure string replacement, no model calls, idempotent.
"""
from __future__ import annotations

import copy
from typing import Any

from ..config import COMPACTABLE_TOOLS, MICRO_COMPACT_KEEP_RECENT, MICRO_COMPACT_THRESHOLD

# The placeholder inserted in place of compressed tool results.
PLACEHOLDER = "[已压缩]"


def _approx_tokens(messages: list[dict[str, Any]]) -> int:
    """Cheap token estimate: ~4 chars per token over the full message list."""
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += len(str(block.get("text", "")))
                    total += len(str(block.get("content", "")))
        # Tool-call argument blobs count too.
        tool_calls = m.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                fn = tc.get("function") or {}
                total += len(str(fn.get("arguments", "")))
    return max(1, int(total * 0.25))


def _is_already_compressed(content: Any) -> bool:
    if not isinstance(content, str):
        return False
    return content.strip() == PLACEHOLDER


def _content_str(content: Any) -> str:
    if isinstance(content, str):
        return content
    # Best-effort: turn the OpenAI-style content list into a string.
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if "text" in block:
                    parts.append(str(block["text"]))
                elif "content" in block:
                    parts.append(str(block["content"]))
        return "\n".join(parts)
    return str(content)


def _set_content(message: dict[str, Any], new_str: str) -> None:
    """Mutate `message` in place to set its content to `new_str`.

    Preserves the original shape (string vs list-of-blocks).
    """
    content = message.get("content")
    if isinstance(content, list):
        # Replace the first text block, or insert a new one.
        for block in content:
            if isinstance(block, dict) and block.get("type") in (None, "text"):
                block["text"] = new_str
                return
        content.insert(0, {"type": "text", "text": new_str})
        return
    message["content"] = new_str


def find_compressible_indices(
    messages: list[dict[str, Any]],
    keep_recent: int = MICRO_COMPACT_KEEP_RECENT,
) -> list[int]:
    """Return the indices of `tool` messages eligible for compression.

    Skips:
        - The most recent `keep_recent` tool messages.
        - Messages that are already the placeholder.
        - Messages whose tool name isn't in the compactable whitelist.
        - Non-tool messages.
    """
    # Walk backwards to find `keep_recent` tool messages to preserve.
    tool_indices: list[int] = []
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") != "tool":
            continue
        tool_indices.append(i)
        if len(tool_indices) >= keep_recent:
            break
    # `keep_recent=0` means "preserve none"; the loop above collects one
    # before the break, so trim that off explicitly.
    if keep_recent <= 0:
        tool_indices = []
    preserved = set(tool_indices)
    out: list[int] = []
    for i, m in enumerate(messages):
        if i in preserved:
            continue
        if m.get("role") != "tool":
            continue
        name = m.get("name") or ""
        if name not in COMPACTABLE_TOOLS:
            continue
        if _is_already_compressed(m.get("content")):
            continue
        out.append(i)
    return out


def should_compact(
    messages: list[dict[str, Any]],
    context_window: int,
    threshold: float = MICRO_COMPACT_THRESHOLD,
) -> bool:
    """Return True if micro-compaction should fire."""
    if context_window <= 0:
        return False
    used = _approx_tokens(messages)
    return used >= int(context_window * threshold)


def compact_messages(
    messages: list[dict[str, Any]],
    *,
    keep_recent: int = MICRO_COMPACT_KEEP_RECENT,
) -> list[dict[str, Any]]:
    """Return a new message list with old tool results replaced by the placeholder.

    Idempotent: re-running on already-compressed messages is a no-op.
    """
    out = copy.deepcopy(messages)
    targets = find_compressible_indices(out, keep_recent=keep_recent)
    for i in targets:
        _set_content(out[i], PLACEHOLDER)
    return out


def micro_compact(
    messages: list[dict[str, Any]],
    context_window: int,
    *,
    keep_recent: int = MICRO_COMPACT_KEEP_RECENT,
    threshold: float = MICRO_COMPACT_THRESHOLD,
) -> tuple[list[dict[str, Any]], bool]:
    """Compact `messages` if the threshold is exceeded.

    Returns:
        (possibly-new message list, was_compacted).
    """
    if not should_compact(messages, context_window, threshold=threshold):
        return messages, False
    return compact_messages(messages, keep_recent=keep_recent), True
