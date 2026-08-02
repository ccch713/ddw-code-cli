"""Tests for the MiniMax API provider (with mocked HTTP)."""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from minimax_agent.providers.base import ChatRequest
from minimax_agent.providers.minimax import MiniMaxProvider


def _sse_lines(payloads: list[dict[str, Any]], finish: str = "stop") -> str:
    """Build an SSE body from a list of JSON chunks."""
    lines: list[str] = []
    for p in payloads:
        lines.append(f"data: {json.dumps(p)}")
    lines.append("data: [DONE]")
    return "\n".join(lines)


def _mock_transport(handler):
    """Return an httpx.MockTransport wrapping `handler`."""
    return httpx.MockTransport(handler)


async def _collect(prov: MiniMaxProvider, req: ChatRequest) -> list:
    out: list = []
    async for ev in prov.chat(req):
        out.append(ev)
        if ev.stop_reason:
            return out
    return out


def _text_chunk(content: str) -> dict[str, Any]:
    return {"choices": [{"delta": {"content": content}}]}


def _tool_chunk(call_id: str, name: str, args: str, index: int = 0) -> dict[str, Any]:
    return {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": index,
                            "id": call_id,
                            "function": {"name": name, "arguments": args},
                        }
                    ]
                }
            }
        ]
    }


def _finish_chunk(finish: str) -> dict[str, Any]:
    return {"choices": [{"finish_reason": finish}]}


def _usage_chunk(prompt: int, completion: int) -> dict[str, Any]:
    return {"usage": {"prompt_tokens": prompt, "completion_tokens": completion}}


@pytest.mark.asyncio
async def test_streaming_text_response() -> None:
    body = _sse_lines(
        [
            _text_chunk("Hello"),
            _text_chunk(" world"),
            _finish_chunk("stop"),
            _usage_chunk(10, 2),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer sk-cp-test"
        return httpx.Response(200, text=body)

    transport = _mock_transport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = MiniMaxProvider("sk-cp-test", client=client)
        try:
            req = ChatRequest(system="s", messages=[{"role": "user", "content": "hi"}])
            events = await _collect(prov, req)
        finally:
            await prov.aclose()

    texts = [e.text_delta for e in events if e.text_delta]
    assert "".join(texts) == "Hello world"
    last = events[-1]
    assert last.stop_reason == "stop"
    assert last.usage is not None
    assert last.usage.input_tokens == 10
    assert last.usage.output_tokens == 2


@pytest.mark.asyncio
async def test_streaming_tool_call() -> None:
    body = _sse_lines(
        [
            _tool_chunk("c1", "bash", '{"command":'),
            _tool_chunk("c1", "bash", '"echo ok"}'),
            _finish_chunk("tool_calls"),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    transport = _mock_transport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = MiniMaxProvider("sk-cp-test", client=client)
        try:
            req = ChatRequest(
                system="s",
                messages=[{"role": "user", "content": "run it"}],
                tools=[{"name": "bash", "description": "shell", "input_schema": {}}],
            )
            events = await _collect(prov, req)
        finally:
            await prov.aclose()

    tool_uses = [e.tool_use for e in events if e.tool_use]
    assert len(tool_uses) == 1
    assert tool_uses[0].name == "bash"
    assert tool_uses[0].input == {"command": "echo ok"}
    assert events[-1].stop_reason == "tool_calls"


@pytest.mark.asyncio
async def test_retry_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 429 should trigger retry; success on the 2nd attempt yields the result."""
    body = _sse_lines([_text_chunk("ok"), _finish_chunk("stop")])
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, text=body)

    # Speed up retries.
    import asyncio as _asyncio

    async def fast_sleep(_: int) -> None:
        return None

    transport = _mock_transport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = MiniMaxProvider("sk-cp-test", client=client)
        monkeypatch.setattr(prov, "_sleep_backoff", fast_sleep)
        try:
            req = ChatRequest(system="s", messages=[{"role": "user", "content": "go"}])
            events = await _collect(prov, req)
        finally:
            await prov.aclose()
    assert attempts["n"] == 2
    assert any(e.text_delta == "ok" for e in events)


@pytest.mark.asyncio
async def test_503_exhausts_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(503, text="down")

    import asyncio as _asyncio

    async def fast_sleep(_: int) -> None:
        return None

    transport = _mock_transport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = MiniMaxProvider("sk-cp-test", client=client)
        monkeypatch.setattr(prov, "_sleep_backoff", fast_sleep)
        try:
            req = ChatRequest(system="s", messages=[{"role": "user", "content": "go"}])
            events = await _collect(prov, req)
        finally:
            await prov.aclose()
    # 1 initial + 3 retries = 4 attempts.
    assert attempts["n"] == 4
    errs = [e for e in events if e.error]
    assert errs, "expected an error event after retries exhausted"


def test_token_plan_key_accepted() -> None:
    p = MiniMaxProvider("sk-cp-abc123def456")
    assert p._key_prefix == "sk-cp-a"


def test_count_tokens_approximate() -> None:
    p = MiniMaxProvider("sk-cp-x")
    assert p.count_tokens("") == 0
    assert p.count_tokens("a" * 400) == 100


def test_translate_tools_passthrough() -> None:
    p = MiniMaxProvider("sk-cp-x")
    schema = {"name": "x", "description": "d", "input_schema": {"type": "object"}}
    out = p._translate_tools([schema])
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "x"
    assert out[0]["function"]["parameters"] == {"type": "object"}


def test_empty_key_rejected() -> None:
    with pytest.raises(ValueError):
        MiniMaxProvider("")
