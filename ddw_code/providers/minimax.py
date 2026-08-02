"""MiniMax Token Plan API provider.

Implements the `ModelProvider` ABC against the OpenAI-compatible
`/v1/chat/completions` endpoint, with SSE streaming, function calling,
exponential-backoff retries on 429/503, and a coarse token counter.

Compatible with Token Plan keys (`sk-cp-...`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .base import ChatRequest, ModelProvider, StreamEvent, ToolUseBlock, Usage

logger = logging.getLogger(__name__)

# Retry policy.
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# Approximate tokens per character; good enough for budget heuristics.
_TOKENS_PER_CHAR = 0.25


class MiniMaxProvider(ModelProvider):
    """MiniMax Token Plan provider.

    Uses the OpenAI-compatible chat completions endpoint with SSE streaming.
    """

    name = "minimax"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.minimaxi.com/v1",
        *,
        timeout: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("MiniMaxProvider requires a non-empty api_key")
        # Don't log the key, but record its prefix for diagnostics.
        self._key_prefix = api_key[:7] if len(api_key) >= 7 else "***"
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        # Allow injecting a client (for tests) but default to a real one.
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ------------------------------------------------------------------ public

    async def chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        """Stream a chat completion, yielding StreamEvents.

        Yields a sequence of `text_delta` events, then zero-or-more
        `tool_use` events, then a final `done` event with `usage`.
        """
        payload = self._build_payload(request)
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                async for event in self._stream_once(payload):
                    if event.error and self._is_retryable_error(event.error):
                        if attempt < _MAX_RETRIES:
                            await self._sleep_backoff(attempt)
                            last_exc = RuntimeError(event.error)
                            break  # retry the whole request
                    yield event
                    if event.stop_reason in {"stop", "tool_calls", "error"}:
                        return
                else:
                    # Inner loop completed without `break` -> success.
                    return
            except httpx.HTTPStatusError as e:
                if e.response.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                    logger.warning(
                        "retryable HTTP %s on attempt %s/%s",
                        e.response.status_code,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await self._sleep_backoff(attempt)
                    last_exc = e
                    continue
                yield StreamEvent(
                    error=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                    stop_reason="error",
                )
                return
            except httpx.RequestError as e:
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "request error on attempt %s/%s: %s",
                        attempt + 1,
                        _MAX_RETRIES,
                        e,
                    )
                    await self._sleep_backoff(attempt)
                    last_exc = e
                    continue
                yield StreamEvent(
                    error=f"network error: {e}",
                    stop_reason="error",
                )
                return
            # If we get here via `break`, retry the outer loop.
            else:
                return

        # All retries exhausted.
        yield StreamEvent(
            error=f"max retries exceeded: {last_exc}",
            stop_reason="error",
        )

    def count_tokens(self, text: str) -> int:
        """Rough token count: ~4 chars per token. Good enough for budget heuristics."""
        if not text:
            return 0
        return max(1, int(len(text) * _TOKENS_PER_CHAR))

    # ------------------------------------------------------------------ helpers

    def _build_payload(self, request: ChatRequest) -> dict[str, Any]:
        """Translate ChatRequest -> OpenAI-compatible JSON payload."""
        messages: list[dict[str, Any]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        # Trust the caller's message list — it already encodes tool/assistant turns.
        messages.extend(request.messages)

        payload: dict[str, Any] = {
            "model": request.model or "MiniMax-Text-01",
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if request.tools:
            payload["tools"] = self._translate_tools(request.tools)
            payload["tool_choice"] = "auto"
        return payload

    def _translate_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Pass through tool defs in OpenAI `tools` schema (our internal format
        already matches, but normalize `parameters` -> `parameters`)."""
        out: list[dict[str, Any]] = []
        for t in tools:
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get(
                            "input_schema",
                            {"type": "object", "properties": {}},
                        ),
                    },
                }
            )
        return out

    async def _stream_once(
        self, payload: dict[str, Any]
    ) -> AsyncIterator[StreamEvent]:
        """Make a single streaming POST and parse SSE events."""
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        # Buffer for partially-streamed tool-call argument JSON.
        tool_buffers: dict[int, dict[str, Any]] = {}
        # Accumulators.
        final_text = ""
        usage = Usage()
        # Last `finish_reason` seen; used in the final event.
        last_finish: str | None = None

        async with self._client.stream(
            "POST", url, json=payload, headers=headers
        ) as response:
            if response.status_code >= 400:
                # Drain the body so the connection can be released, then raise.
                await response.aread()
                raise httpx.HTTPStatusError(
                    f"{response.status_code}",
                    request=response.request,
                    response=response,
                )

            async for raw_line in response.aiter_lines():
                if not raw_line:
                    continue
                if not raw_line.startswith("data:"):
                    # ignore keep-alive / comment lines
                    continue
                data = raw_line[len("data:") :].strip()
                if data == "[DONE]":
                    # Drain any buffered tool calls before the final event.
                    for slot in tool_buffers.values():
                        try:
                            args = json.loads(slot["args"] or "{}")
                        except json.JSONDecodeError:
                            args = {"_raw": slot["args"]}
                        yield StreamEvent(
                            tool_use=ToolUseBlock(
                                id=slot["id"],
                                name=slot["name"],
                                input=args,
                            )
                        )
                    yield StreamEvent(
                        usage=usage,
                        stop_reason=last_finish or "stop",
                        final_text=final_text,
                    )
                    return
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    logger.debug("skipping malformed SSE line: %r", data[:120])
                    continue

                choice = (chunk.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}

                # `usage` may arrive in a chunk with no choices — handle it first.
                u = chunk.get("usage") or {}
                if u:
                    usage = Usage(
                        input_tokens=u.get("prompt_tokens", 0) or 0,
                        output_tokens=u.get("completion_tokens", 0) or 0,
                    )

                # Text delta.
                text_piece = delta.get("content")
                if text_piece:
                    final_text += text_piece
                    yield StreamEvent(text_delta=text_piece)

                # Tool calls (OpenAI streaming format).
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = tool_buffers.setdefault(
                        idx,
                        {"id": "", "name": "", "args": ""},
                    )
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["args"] += fn["arguments"]

                finish = choice.get("finish_reason")
                if finish:
                    last_finish = finish

            # Stream ended without [DONE] — yield final event as fallback.
            # MiniMax API may end stream after usage chunk without sending [DONE].
            for slot in tool_buffers.values():
                try:
                    args = json.loads(slot["args"] or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": slot["args"]}
                yield StreamEvent(
                    tool_use=ToolUseBlock(
                        id=slot["id"],
                        name=slot["name"],
                        input=args,
                    )
                )
            yield StreamEvent(
                usage=usage,
                stop_reason=last_finish or "stop",
                final_text=final_text,
            )

    # ------------------------------------------------------------------ retry

    def _is_retryable_error(self, msg: str) -> bool:
        return any(code in msg for code in ("429", "500", "502", "503", "504"))

    async def _sleep_backoff(self, attempt: int) -> None:
        delay = _RETRY_BASE_DELAY * (2**attempt) + random.uniform(0, 0.25)
        await asyncio.sleep(delay)
