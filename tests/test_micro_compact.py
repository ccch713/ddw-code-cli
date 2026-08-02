"""Tests for micro-compact (zero-LLM context compression)."""
from __future__ import annotations

import pytest

from ddw_code.compact.micro_compact import (
    PLACEHOLDER,
    compact_messages,
    find_compressible_indices,
    micro_compact,
    should_compact,
)


def _tool_msg(idx: int, name: str, content: str) -> dict:
    return {
        "role": "tool",
        "tool_call_id": f"c{idx}",
        "name": name,
        "content": content,
    }


def test_should_compact_threshold() -> None:
    msgs = [{"role": "user", "content": "x" * 1000}]
    # context_window=1000, threshold=0.6 -> 600 tokens ~= 2400 chars.
    assert should_compact(msgs, context_window=1000) is False
    big = [{"role": "user", "content": "x" * 20_000}]
    assert should_compact(big, context_window=1000) is True


def test_keeps_recent_5_others_compressed() -> None:
    msgs = [_tool_msg(i, "file_read", f"content {i}") for i in range(10)]
    indices = find_compressible_indices(msgs, keep_recent=5)
    assert len(indices) == 5
    # The oldest 5 are the targets.
    assert indices == [0, 1, 2, 3, 4]


def test_skips_non_compactable_tools() -> None:
    msgs = [
        _tool_msg(0, "file_write", "a"),
        _tool_msg(1, "file_read", "b"),
        _tool_msg(2, "bash", "c"),
    ]
    indices = find_compressible_indices(msgs, keep_recent=0)
    # file_write isn't in the whitelist; bash and file_read are.
    assert 0 not in indices
    assert 1 in indices
    assert 2 in indices


def test_idempotent() -> None:
    msgs = [_tool_msg(i, "file_read", f"content {i}") for i in range(3)]
    once = compact_messages(msgs, keep_recent=1)
    twice = compact_messages(once, keep_recent=1)
    assert once == twice


def test_already_compressed_skipped() -> None:
    msgs = [
        _tool_msg(0, "file_read", PLACEHOLDER),
        _tool_msg(1, "file_read", "real content"),
    ]
    indices = find_compressible_indices(msgs, keep_recent=0)
    assert 0 not in indices
    assert 1 in indices


def test_micro_compact_returns_flag() -> None:
    msgs = [{"role": "user", "content": "x" * 50_000}]
    out, did = micro_compact(msgs, context_window=1000)
    assert did is True
    # Same length (no message deleted) but some content replaced.
    assert len(out) == len(msgs)


def test_micro_compact_below_threshold_no_op() -> None:
    msgs = [{"role": "user", "content": "short"}]
    out, did = micro_compact(msgs, context_window=10_000)
    assert did is False
    assert out is msgs


def test_compact_messages_preserves_assistant() -> None:
    msgs = [
        {"role": "user", "content": "hi"},
        _tool_msg(0, "file_read", "a" * 1000),
        _tool_msg(1, "file_read", "b" * 1000),
        _tool_msg(2, "file_read", "c" * 1000),
        {"role": "assistant", "content": "ok"},
    ]
    out = compact_messages(msgs, keep_recent=1)
    # The user and assistant messages are untouched.
    assert out[0] == msgs[0]
    assert out[-1] == msgs[-1]
    # At least one tool message is now the placeholder.
    placeholders = [m for m in out if m.get("content") == PLACEHOLDER]
    assert placeholders
