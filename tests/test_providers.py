"""Tests for DeepSeek and OpenAI providers (with mocked HTTP)."""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from ddw_code.providers.base import ChatRequest
from ddw_code.providers.deepseek import DeepSeekProvider
from ddw_code.providers.openai import OpenAIProvider


def _sse_lines(payloads: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for p in payloads:
        lines.append(f"data: {json.dumps(p)}")
    lines.append("data: [DONE]")
    return "\n".join(lines)


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


async def _collect(prov, req: ChatRequest) -> list:
    out: list = []
    async for ev in prov.chat(req):
        out.append(ev)
        if ev.stop_reason:
            return out
    return out


# ---- DeepSeek tests ----


@pytest.mark.asyncio
async def test_deepseek_streaming_text() -> None:
    body = _sse_lines([_text_chunk("hello"), _text_chunk(" world"), _finish_chunk("stop"), _usage_chunk(10, 2)])

    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.deepseek.com" in str(request.url)
        return httpx.Response(200, text=body)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = DeepSeekProvider("sk-test-key", client=client)
        try:
            req = ChatRequest(system="s", messages=[{"role": "user", "content": "hi"}])
            events = await _collect(prov, req)
        finally:
            await prov.aclose()

    texts = [e.text_delta for e in events if e.text_delta]
    assert "".join(texts) == "hello world"
    assert events[-1].stop_reason == "stop"
    assert events[-1].usage.input_tokens == 10


@pytest.mark.asyncio
async def test_deepseek_streaming_tool_call() -> None:
    body = _sse_lines([_tool_chunk("c1", "bash", '{"command":'), _tool_chunk("c1", "bash", '"echo ok"}'), _finish_chunk("tool_calls")])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = DeepSeekProvider("sk-test-key", client=client)
        try:
            req = ChatRequest(system="s", messages=[{"role": "user", "content": "run"}], tools=[{"name": "bash", "description": "shell", "input_schema": {}}])
            events = await _collect(prov, req)
        finally:
            await prov.aclose()

    tool_uses = [e.tool_use for e in events if e.tool_use]
    assert len(tool_uses) == 1
    assert tool_uses[0].name == "bash"
    assert tool_uses[0].input == {"command": "echo ok"}


@pytest.mark.asyncio
async def test_deepseek_retry_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    body = _sse_lines([_text_chunk("ok"), _finish_chunk("stop")])
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, text=body)

    async def fast_sleep(_: int) -> None:
        return None

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = DeepSeekProvider("sk-test-key", client=client)
        monkeypatch.setattr(prov, "_sleep_backoff", fast_sleep)
        try:
            req = ChatRequest(system="s", messages=[{"role": "user", "content": "go"}])
            events = await _collect(prov, req)
        finally:
            await prov.aclose()

    assert attempts["n"] == 2
    assert any(e.text_delta == "ok" for e in events)


@pytest.mark.asyncio
async def test_deepseek_503_exhausts_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(503, text="down")

    async def fast_sleep(_: int) -> None:
        return None

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = DeepSeekProvider("sk-test-key", client=client)
        monkeypatch.setattr(prov, "_sleep_backoff", fast_sleep)
        try:
            req = ChatRequest(system="s", messages=[{"role": "user", "content": "go"}])
            events = await _collect(prov, req)
        finally:
            await prov.aclose()

    assert attempts["n"] == 4
    errs = [e for e in events if e.error]
    assert errs


def test_deepseek_empty_key_rejected() -> None:
    with pytest.raises(ValueError):
        DeepSeekProvider("")


def test_deepseek_count_tokens() -> None:
    p = DeepSeekProvider("sk-test-key")
    assert p.count_tokens("") == 0
    assert p.count_tokens("a" * 400) == 100


def test_deepseek_translate_tools() -> None:
    p = DeepSeekProvider("sk-test-key")
    schema = {"name": "x", "description": "d", "input_schema": {"type": "object"}}
    out = p._translate_tools([schema])
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "x"


@pytest.mark.asyncio
async def test_deepseek_invalid_json_skipped() -> None:
    body = "data: {not json}\ndata: [DONE]\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = DeepSeekProvider("sk-test-key", client=client)
        try:
            events = []
            async for ev in prov.chat(ChatRequest(system="", messages=[{"role": "user", "content": "go"}])):
                events.append(ev)
                if ev.stop_reason:
                    break
        finally:
            await prov.aclose()
    assert any(e.stop_reason for e in events)


@pytest.mark.asyncio
async def test_deepseek_max_retries_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    async def fast_sleep(_: int) -> None:
        return None

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = DeepSeekProvider("sk-test-key", client=client)
        monkeypatch.setattr(prov, "_sleep_backoff", fast_sleep)
        try:
            events = []
            async for ev in prov.chat(ChatRequest(system="", messages=[{"role": "user", "content": "go"}])):
                events.append(ev)
                if ev.stop_reason:
                    break
        finally:
            await prov.aclose()
    errs = [e for e in events if e.error]
    assert errs
    assert "max retries" in errs[0].error or "503" in errs[0].error


# ---- OpenAI tests ----


@pytest.mark.asyncio
async def test_openai_streaming_text() -> None:
    body = _sse_lines([_text_chunk("hi"), _text_chunk(" there"), _finish_chunk("stop"), _usage_chunk(5, 3)])

    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.openai.com" in str(request.url)
        return httpx.Response(200, text=body)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = OpenAIProvider("sk-test-key", client=client)
        try:
            req = ChatRequest(system="s", messages=[{"role": "user", "content": "hi"}])
            events = await _collect(prov, req)
        finally:
            await prov.aclose()

    texts = [e.text_delta for e in events if e.text_delta]
    assert "".join(texts) == "hi there"
    assert events[-1].stop_reason == "stop"


@pytest.mark.asyncio
async def test_openai_streaming_tool_call() -> None:
    body = _sse_lines([_tool_chunk("c1", "grep", '{"pattern":'), _tool_chunk("c1", "grep", '"foo"}'), _finish_chunk("tool_calls")])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = OpenAIProvider("sk-test-key", client=client)
        try:
            req = ChatRequest(system="s", messages=[{"role": "user", "content": "search"}], tools=[{"name": "grep", "description": "search", "input_schema": {}}])
            events = await _collect(prov, req)
        finally:
            await prov.aclose()

    tool_uses = [e.tool_use for e in events if e.tool_use]
    assert len(tool_uses) == 1
    assert tool_uses[0].name == "grep"


@pytest.mark.asyncio
async def test_openai_retry_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    body = _sse_lines([_text_chunk("ok"), _finish_chunk("stop")])
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, text=body)

    async def fast_sleep(_: int) -> None:
        return None

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = OpenAIProvider("sk-test-key", client=client)
        monkeypatch.setattr(prov, "_sleep_backoff", fast_sleep)
        try:
            req = ChatRequest(system="s", messages=[{"role": "user", "content": "go"}])
            events = await _collect(prov, req)
        finally:
            await prov.aclose()

    assert attempts["n"] == 2


@pytest.mark.asyncio
async def test_openai_503_exhausts_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    async def fast_sleep(_: int) -> None:
        return None

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = OpenAIProvider("sk-test-key", client=client)
        monkeypatch.setattr(prov, "_sleep_backoff", fast_sleep)
        try:
            events = []
            async for ev in prov.chat(ChatRequest(system="", messages=[{"role": "user", "content": "go"}])):
                events.append(ev)
                if ev.stop_reason:
                    break
        finally:
            await prov.aclose()

    errs = [e for e in events if e.error]
    assert errs


def test_openai_empty_key_rejected() -> None:
    with pytest.raises(ValueError):
        OpenAIProvider("")


def test_openai_count_tokens() -> None:
    p = OpenAIProvider("sk-test-key")
    assert p.count_tokens("") == 0
    assert p.count_tokens("a" * 400) == 100


def test_openai_translate_tools() -> None:
    p = OpenAIProvider("sk-test-key")
    schema = {"name": "x", "description": "d", "input_schema": {"type": "object"}}
    out = p._translate_tools([schema])
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "x"


@pytest.mark.asyncio
async def test_openai_invalid_json_skipped() -> None:
    body = "data: {not json}\ndata: [DONE]\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = OpenAIProvider("sk-test-key", client=client)
        try:
            events = []
            async for ev in prov.chat(ChatRequest(system="", messages=[{"role": "user", "content": "go"}])):
                events.append(ev)
                if ev.stop_reason:
                    break
        finally:
            await prov.aclose()
    assert any(e.stop_reason for e in events)


@pytest.mark.asyncio
async def test_openai_max_retries_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    async def fast_sleep(_: int) -> None:
        return None

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = OpenAIProvider("sk-test-key", client=client)
        monkeypatch.setattr(prov, "_sleep_backoff", fast_sleep)
        try:
            events = []
            async for ev in prov.chat(ChatRequest(system="", messages=[{"role": "user", "content": "go"}])):
                events.append(ev)
                if ev.stop_reason:
                    break
        finally:
            await prov.aclose()
    errs = [e for e in events if e.error]
    assert errs


# ---- Provider registry tests ----


def test_get_provider_minimax() -> None:
    from ddw_code.providers import get_provider
    p = get_provider("minimax", api_key="sk-test")
    assert p.name == "minimax"


def test_get_provider_deepseek() -> None:
    from ddw_code.providers import get_provider
    p = get_provider("deepseek", api_key="sk-test")
    assert p.name == "deepseek"


def test_get_provider_openai() -> None:
    from ddw_code.providers import get_provider
    p = get_provider("openai", api_key="sk-test")
    assert p.name == "openai"


def test_get_provider_unknown() -> None:
    from ddw_code.providers import get_provider
    with pytest.raises(ValueError, match="unknown provider"):
        get_provider("unknown", api_key="sk-test")


# ---- Additional provider error path tests ----


@pytest.mark.asyncio
async def test_deepseek_non_retryable_http_error() -> None:
    """A 400 (non-retryable) should yield an error event immediately."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = DeepSeekProvider("sk-test-key", client=client)
        try:
            events = await _collect(prov, ChatRequest(system="", messages=[{"role": "user", "content": "go"}]))
        finally:
            await prov.aclose()
    errs = [e for e in events if e.error]
    assert errs
    assert "400" in errs[0].error


@pytest.mark.asyncio
async def test_openai_non_retryable_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = OpenAIProvider("sk-test-key", client=client)
        try:
            events = await _collect(prov, ChatRequest(system="", messages=[{"role": "user", "content": "go"}]))
        finally:
            await prov.aclose()
    errs = [e for e in events if e.error]
    assert errs
    assert "400" in errs[0].error


@pytest.mark.asyncio
async def test_deepseek_request_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A network error (httpx.RequestError) should retry then yield error."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        raise httpx.ConnectError("connection refused")

    async def fast_sleep(_: int) -> None:
        return None

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = DeepSeekProvider("sk-test-key", client=client)
        monkeypatch.setattr(prov, "_sleep_backoff", fast_sleep)
        try:
            events = []
            async for ev in prov.chat(ChatRequest(system="", messages=[{"role": "user", "content": "go"}])):
                events.append(ev)
                if ev.stop_reason:
                    break
        finally:
            await prov.aclose()
    errs = [e for e in events if e.error]
    assert errs
    assert "network error" in errs[0].error


@pytest.mark.asyncio
async def test_openai_request_error(monkeypatch: pytest.MonkeyPatch) -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        raise httpx.ConnectError("connection refused")

    async def fast_sleep(_: int) -> None:
        return None

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = OpenAIProvider("sk-test-key", client=client)
        monkeypatch.setattr(prov, "_sleep_backoff", fast_sleep)
        try:
            events = []
            async for ev in prov.chat(ChatRequest(system="", messages=[{"role": "user", "content": "go"}])):
                events.append(ev)
                if ev.stop_reason:
                    break
        finally:
            await prov.aclose()
    errs = [e for e in events if e.error]
    assert errs
    assert "network error" in errs[0].error


@pytest.mark.asyncio
async def test_deepseek_aclose_owned_client() -> None:
    """aclose should close the client when it owns it."""
    prov = DeepSeekProvider("sk-test-key")
    await prov.aclose()
    # No error means success


@pytest.mark.asyncio
async def test_openai_aclose_owned_client() -> None:
    prov = OpenAIProvider("sk-test-key")
    await prov.aclose()


@pytest.mark.asyncio
async def test_deepseek_default_model() -> None:
    """Default model should be deepseek-chat."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "deepseek-chat"
        return httpx.Response(200, text=_sse_lines([_text_chunk("ok"), _finish_chunk("stop")]))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = DeepSeekProvider("sk-test-key", client=client)
        try:
            events = await _collect(prov, ChatRequest(system="", messages=[{"role": "user", "content": "go"}]))
        finally:
            await prov.aclose()


@pytest.mark.asyncio
async def test_openai_default_model() -> None:
    """Default model should be gpt-4o."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "gpt-4o"
        return httpx.Response(200, text=_sse_lines([_text_chunk("ok"), _finish_chunk("stop")]))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = OpenAIProvider("sk-test-key", client=client)
        try:
            events = await _collect(prov, ChatRequest(system="", messages=[{"role": "user", "content": "go"}]))
        finally:
            await prov.aclose()


@pytest.mark.asyncio
async def test_deepseek_custom_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "deepseek-coder"
        return httpx.Response(200, text=_sse_lines([_text_chunk("ok"), _finish_chunk("stop")]))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = DeepSeekProvider("sk-test-key", client=client)
        try:
            events = await _collect(prov, ChatRequest(system="", messages=[{"role": "user", "content": "go"}], model="deepseek-coder"))
        finally:
            await prov.aclose()


@pytest.mark.asyncio
async def test_openai_custom_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "gpt-3.5-turbo"
        return httpx.Response(200, text=_sse_lines([_text_chunk("ok"), _finish_chunk("stop")]))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = OpenAIProvider("sk-test-key", client=client)
        try:
            events = await _collect(prov, ChatRequest(system="", messages=[{"role": "user", "content": "go"}], model="gpt-3.5-turbo"))
        finally:
            await prov.aclose()
