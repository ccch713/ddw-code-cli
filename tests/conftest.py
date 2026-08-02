"""Shared fixtures and helpers for the test suite."""
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

# Make the package importable when running pytest from any cwd.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Set a dummy API key so `load_config` works without env vars.
os.environ.setdefault("MINIMAX_API_KEY", "sk-cp-test-key-for-tests-only")

from minimax_agent.config import Config  # noqa: E402
from minimax_agent.providers.base import (  # noqa: E402
    ChatRequest,
    ModelProvider,
    StreamEvent,
    ToolUseBlock,
    Usage,
)


class MockProvider(ModelProvider):
    """A scripted `ModelProvider` for tests.

    The test supplies a list of "turn scripts" — each script is a list of
    `StreamEvent`s the provider will yield for that turn. The provider
    pops the next script on each call to `chat()`. If no more scripts are
    available, it returns a single `stop` event.
    """

    name = "mock"

    def __init__(self, scripts: list[list[StreamEvent]] | None = None) -> None:
        self.scripts: list[list[StreamEvent]] = list(scripts or [])
        self.calls: list[ChatRequest] = []

    def push(self, events: list[StreamEvent]) -> None:
        """Append a new turn script."""
        self.scripts.append(events)

    async def chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.calls.append(request)
        if self.scripts:
            script = self.scripts.pop(0)
            for ev in script:
                yield ev
                if ev.stop_reason:
                    return
            return
        # Default: just a no-op text reply.
        yield StreamEvent(text_delta="(no more scripts)")
        yield StreamEvent(stop_reason="stop", final_text="(no more scripts)")

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def make_text_event(text: str) -> StreamEvent:
    return StreamEvent(text_delta=text)


def make_tool_event(call_id: str, name: str, args: dict[str, Any]) -> StreamEvent:
    return StreamEvent(
        tool_use=ToolUseBlock(id=call_id, name=name, input=args),
        stop_reason="tool_calls",
        usage=Usage(input_tokens=10, output_tokens=5),
    )


def make_done_event(final_text: str = "") -> StreamEvent:
    return StreamEvent(stop_reason="stop", final_text=final_text, usage=Usage(5, 3))


def make_error_event(msg: str) -> StreamEvent:
    return StreamEvent(error=msg, stop_reason="error")


@pytest.fixture
def mock_provider() -> MockProvider:
    return MockProvider()


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """A temporary directory acting as the agent's working directory."""
    sub = tmp_path / "workspace"
    sub.mkdir()
    return sub


@pytest.fixture
def config(tmp_workspace: Path) -> Config:
    return Config(api_key="sk-cp-test", workspace=tmp_workspace, max_turns=5)


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
