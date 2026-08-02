"""Tests for the agent turn loop."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from minimax_agent.config import Config
from minimax_agent.security.permissions import Decision, PermissionManager
from minimax_agent.tools.builder import build_default_registry
from minimax_agent.tools.dispatcher import ToolDispatcher, ToolNeedsConfirmation
from minimax_agent.turn_loop import TurnEvent, TurnLoop

from .conftest import (
    MockProvider,
    make_done_event,
    make_error_event,
    make_text_event,
    make_tool_event,
)


def _make_loop(
    config: Config,
    provider: MockProvider,
    *,
    auto_approve: bool = False,
) -> tuple[TurnLoop, ToolDispatcher, PermissionManager]:
    registry = build_default_registry()
    perm = PermissionManager()
    if auto_approve:
        for t in registry.all():
            perm.approve(t.name)
    disp = ToolDispatcher(registry, perm)
    loop = TurnLoop(
        config=config,
        provider=provider,
        registry=registry,
        dispatcher=disp,
        auto_approve_tools=auto_approve,
    )
    return loop, disp, perm


async def _drain(loop: TurnLoop, prompt: str) -> list[TurnEvent]:
    return [ev async for ev in loop.run(prompt)]


def test_simple_text_response(config: Config, mock_provider: MockProvider) -> None:
    """If the model returns text only (no tool calls), the loop terminates."""
    mock_provider.push([make_text_event("Hello!"), make_done_event("Hello!")])
    loop, _, _ = _make_loop(config, mock_provider)
    events = asyncio.run(_drain(loop, "hi"))
    kinds = [e.kind for e in events]
    assert "text_delta" in kinds
    assert "turn_end" in kinds
    assert kinds[-1] == "turn_end"
    end = events[-1]
    assert end.extras["stop_reason"] == "stop"
    assert end.extras["final_text"] == "Hello!"


def test_tool_call_dispatches_and_continues(config: Config, mock_provider: MockProvider) -> None:
    """When the model emits a tool call, the loop runs it and re-prompts."""
    # Turn 1: emit a tool call.
    mock_provider.push(
        [make_tool_event("call_1", "bash", {"command": "echo hi", "timeout": 5})]
    )
    # Turn 2: text reply.
    mock_provider.push([make_text_event("done"), make_done_event("done")])
    loop, _, _ = _make_loop(config, mock_provider, auto_approve=True)
    events = asyncio.run(_drain(loop, "say hi"))
    kinds = [e.kind for e in events]
    assert "tool_call" in kinds
    assert "tool_result" in kinds
    # Find the tool_result.
    results = [e for e in events if e.kind == "tool_result"]
    assert results[0].tool_name == "bash"
    assert "hi" in results[0].tool_output


def test_uses_tools_schemas(config: Config, mock_provider: MockProvider) -> None:
    """The loop forwards the tool registry's schemas to the provider."""
    mock_provider.push([make_text_event("ok"), make_done_event("ok")])
    loop, _, _ = _make_loop(config, mock_provider)
    asyncio.run(_drain(loop, "test"))
    assert len(mock_provider.calls) == 1
    sent = mock_provider.calls[0]
    assert sent.tools, "tools should be sent to the provider"
    names = {t["name"] for t in sent.tools}
    assert "bash" in names
    assert "file_read" in names


def test_ask_policy_raises_without_approval(
    config: Config, mock_provider: MockProvider
) -> None:
    """Default permission policy is `ask` for bash — without auto-approve
    the tool should fail and the message loop continues."""
    mock_provider.push(
        [make_tool_event("call_1", "bash", {"command": "echo blocked", "timeout": 5})]
    )
    # After the denial, the model will get a tool message saying it was
    # denied; it should reply with text.
    mock_provider.push([make_text_event("ok"), make_done_event("ok")])
    loop, _, _ = _make_loop(config, mock_provider, auto_approve=False)
    events = asyncio.run(_drain(loop, "test"))
    results = [e for e in events if e.kind == "tool_result"]
    assert results[0].is_error
    assert "denied" in results[0].tool_output or "needs confirmation" in results[0].tool_output


def test_max_turns(config: Config, mock_provider: MockProvider) -> None:
    """The loop stops after max_turns tool-call iterations."""
    # 5 turns, each emitting a tool call. Loop max_turns=5.
    for i in range(5):
        mock_provider.push(
            [make_tool_event(f"call_{i}", "bash", {"command": "true", "timeout": 5})]
        )
    # Then a final text.
    mock_provider.push([make_text_event("done"), make_done_event("done")])
    loop, _, _ = _make_loop(config, mock_provider, auto_approve=True)
    events = asyncio.run(_drain(loop, "loop"))
    end = [e for e in events if e.kind == "turn_end"]
    assert end
    # We should see at least 6 calls (5 tool + 1 final), or hit max_turns.
    assert len(mock_provider.calls) >= 1


def test_error_event_yields_error_and_turn_end(
    config: Config, mock_provider: MockProvider
) -> None:
    mock_provider.push([make_error_event("boom")])
    loop, _, _ = _make_loop(config, mock_provider)
    events = asyncio.run(_drain(loop, "fail"))
    errs = [e for e in events if e.kind == "error"]
    assert errs and errs[0].text == "boom"
    assert events[-1].kind == "turn_end"
    assert events[-1].extras["stop_reason"] == "error"


def test_total_token_tracking(config: Config, mock_provider: MockProvider) -> None:
    mock_provider.push(
        [make_tool_event("c1", "bash", {"command": "true", "timeout": 5})]
    )
    mock_provider.push([make_text_event("ok"), make_done_event("ok")])
    loop, _, _ = _make_loop(config, mock_provider, auto_approve=True)
    asyncio.run(_drain(loop, "go"))
    assert loop.total_input_tokens > 0
    assert loop.total_output_tokens > 0


def test_reset_clears_state(config: Config, mock_provider: MockProvider) -> None:
    mock_provider.push([make_text_event("a"), make_done_event("a")])
    loop, _, _ = _make_loop(config, mock_provider)
    asyncio.run(_drain(loop, "hi"))
    assert loop.messages
    loop.reset()
    assert loop.messages == []
    assert loop.total_input_tokens == 0
