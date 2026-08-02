"""Agent turn loop.

The core driver: send a user message to the LLM, parse tool calls, dispatch
them, feed results back, and repeat until the model emits no more tool calls
or we hit `max_turns`.

Implemented as an async generator that yields `TurnEvent`s so the CLI can
render progress incrementally (and so tests can assert on intermediate steps).
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from .compact.micro_compact import micro_compact
from .config import Config
from .providers.base import ChatRequest, ModelProvider, ToolUseBlock
from .tools.dispatcher import (
    DispatchResult,
    ToolDispatcher,
    ToolNeedsConfirmation,
)
from .tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class TurnEvent:
    """An event the loop yields to its caller.

    The CLI / tests consume these to render output and assert behavior.
    """

    kind: str  # "text_delta" | "tool_call" | "tool_result" | "turn_end" | "error" | "compact"
    text: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    tool_output: str = ""
    is_error: bool = False
    turn_index: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)


SYSTEM_PROMPT = """You are DDW Code CLI, a coding assistant that executes tools to solve problems.

## Core Rules
1. You are a TOOL EXECUTOR, not a chatbot. Always use tools when available.
2. Never describe what you would do — just do it by calling the tool.
3. After receiving tool results, check if you have enough info → summarize → stop.
4. Never repeat tool call details in your text output.

## Anti-Patterns (FORBIDDEN)
❌ "I would read the file..." → ✅ Just call file_read
❌ "Let me think about this..." → ✅ Just call the appropriate tool
❌ Repeating what a tool returned in your own words
❌ Continuing to call tools after you have enough information

## Output Rules
- When writing code, output it directly without markdown formatting.
- When answering questions, be concise and direct.
- After completing a task, stop. Do not continue with unnecessary tool calls.

## Parameter Rules
- Use exact parameter names from the tool schema (case-sensitive).
- Always provide required parameters."""


def _tool_message(call_id: str, name: str, content: str) -> dict[str, Any]:
    """Build an OpenAI-style tool result message."""
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": name,
        "content": content,
    }


def _assistant_message(
    text: str, tool_calls: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Build an OpenAI-style assistant message."""
    msg: dict[str, Any] = {"role": "assistant", "content": text}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _build_tool_call_block(tu: ToolUseBlock) -> dict[str, Any]:
    """Wrap a parsed ToolUseBlock into the OpenAI streaming format."""
    return {
        "id": tu.id,
        "type": "function",
        "function": {
            "name": tu.name,
            "arguments": json.dumps(tu.input, ensure_ascii=False),
        },
    }


class TurnLoop:
    """Run a multi-turn agent conversation against a provider."""

    def __init__(
        self,
        *,
        config: Config,
        provider: ModelProvider,
        registry: ToolRegistry,
        dispatcher: ToolDispatcher,
        auto_approve_tools: bool = False,
    ) -> None:
        self.config = config
        self.provider = provider
        self.registry = registry
        self.dispatcher = dispatcher
        self.auto_approve_tools = auto_approve_tools
        # Conversation state.
        self.messages: list[dict[str, Any]] = []
        # Cumulative token usage across the session.
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    # ------------------------------------------------------------------ helpers

    def reset(self) -> None:
        self.messages = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def build_system_prompt(self, extra: str = "") -> str:
        sys = SYSTEM_PROMPT
        if extra:
            sys = f"{sys}\n\n{extra}"
        return sys

    # ------------------------------------------------------------------ main loop

    async def run(
        self, user_input: str, *, system_extra: str = ""
    ) -> AsyncIterator[TurnEvent]:
        """Drive the agent loop for one user turn.

        Yields `TurnEvent`s. The final event is always `kind="turn_end"`.
        """
        self.messages.append({"role": "user", "content": user_input})
        system = self.build_system_prompt(system_extra)

        for turn_index in range(self.config.max_turns):
            # 1) Maybe compact.
            msgs, compacted = micro_compact(
                list(self.messages),  # micro_compact copies internally
                context_window=self.config.context_window,
            )
            if compacted:
                self.messages = msgs
                yield TurnEvent(kind="compact", turn_index=turn_index)

            # 2) Call the LLM.
            request = ChatRequest(
                system=system,
                messages=list(self.messages),
                tools=self.registry.schemas(),
                model=self.config.model,
            )
            collected_text = ""
            collected_tool_calls: list[ToolUseBlock] = []
            stop_reason = "stop"
            error: str | None = None
            try:
                async for ev in self.provider.chat(request):
                    if ev.error:
                        error = ev.error
                        stop_reason = "error"
                        break
                    if ev.text_delta:
                        collected_text += ev.text_delta
                        yield TurnEvent(
                            kind="text_delta",
                            text=ev.text_delta,
                            turn_index=turn_index,
                        )
                    if ev.tool_use:
                        collected_tool_calls.append(ev.tool_use)
                    if ev.usage:
                        self.total_input_tokens += ev.usage.input_tokens
                        self.total_output_tokens += ev.usage.output_tokens
                    if ev.stop_reason:
                        stop_reason = ev.stop_reason
            except Exception as e:  # noqa: BLE001
                error = f"provider error: {e}"

            # 3) Persist the assistant turn.
            tool_call_blocks = (
                [_build_tool_call_block(tu) for tu in collected_tool_calls]
                if collected_tool_calls
                else None
            )
            self.messages.append(
                _assistant_message(collected_text, tool_call_blocks)
            )

            if error:
                yield TurnEvent(
                    kind="error", text=error, turn_index=turn_index, is_error=True
                )
                yield TurnEvent(
                    kind="turn_end",
                    turn_index=turn_index,
                    usage={
                        "input": self.total_input_tokens,
                        "output": self.total_output_tokens,
                    },
                    extras={"stop_reason": "error"},
                )
                return

            if not collected_tool_calls:
                # Done — no tool calls, just text.
                yield TurnEvent(
                    kind="turn_end",
                    turn_index=turn_index,
                    usage={
                        "input": self.total_input_tokens,
                        "output": self.total_output_tokens,
                    },
                    extras={"stop_reason": stop_reason, "final_text": collected_text},
                )
                return

            # 4) Dispatch each tool call.
            for tu in collected_tool_calls:
                yield TurnEvent(
                    kind="tool_call",
                    tool_name=tu.name,
                    tool_input=tu.input,
                    turn_index=turn_index,
                )
                try:
                    if self.auto_approve_tools:
                        # Approve the tool for this session so `ask` -> `allow`.

                        # We don't have a direct reference here, but the
                        # dispatcher does. The simplest path: catch
                        # `ToolNeedsConfirmation` and re-dispatch after
                        # approving through the dispatcher's permissions.
                        try:
                            result = await self.dispatcher.dispatch(tu.name, tu.input)
                            if result.is_error and "needs confirmation" in result.output:
                                # shouldn't happen since we approved below
                                self.dispatcher.permissions.approve(tu.name)
                                result = await self.dispatcher.dispatch(tu.name, tu.input)
                        except ToolNeedsConfirmation:
                            self.dispatcher.permissions.approve(tu.name)
                            result = await self.dispatcher.dispatch(tu.name, tu.input)
                    else:
                        result = await self.dispatcher.dispatch(tu.name, tu.input)
                except ToolNeedsConfirmation as e:
                    # Surface to the user; the CLI is expected to handle this.
                    result = DispatchResult(
                        tool_name=e.tool_name,
                        output=f"tool {e.tool_name!r} needs confirmation",
                        is_error=True,
                    )
                except Exception as e:  # noqa: BLE001
                    result = DispatchResult(
                        tool_name=tu.name, output=f"dispatch error: {e}", is_error=True
                    )
                self.messages.append(
                    _tool_message(tu.id, tu.name, result.output)
                )
                yield TurnEvent(
                    kind="tool_result",
                    tool_name=tu.name,
                    tool_output=result.output,
                    is_error=result.is_error,
                    turn_index=turn_index,
                )

        # Exhausted max_turns.
        yield TurnEvent(
            kind="error",
            text=f"exceeded max_turns={self.config.max_turns}",
            turn_index=self.config.max_turns - 1,
            is_error=True,
        )
        yield TurnEvent(
            kind="turn_end",
            turn_index=self.config.max_turns - 1,
            usage={
                "input": self.total_input_tokens,
                "output": self.total_output_tokens,
            },
            extras={"stop_reason": "max_turns"},
        )


__all__ = ["TurnLoop", "TurnEvent"]
