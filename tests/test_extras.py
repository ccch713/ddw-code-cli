"""Extra tests for CLI, context detector, web_search, auto-compact, and
config to push coverage above 80%."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from ddw_code import config as cfg_mod
from ddw_code.compact.auto_compact import auto_compact
from ddw_code.context.detector import detect
from ddw_code.tools import web_search


# ---------------------------------------------------------------- config


def test_load_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-cp-env")
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-Text-01")
    c = cfg_mod.load_config()
    assert c.api_key == "sk-cp-env"
    assert c.model == "MiniMax-Text-01"
    assert c.is_token_plan_key() is True


def test_load_config_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_TOKEN", raising=False)
    with pytest.raises(ValueError):
        cfg_mod.load_config()


def test_load_config_overrides() -> None:
    c = cfg_mod.load_config(
        api_key="sk-cp-x", base_url="https://example/v1", model="custom"
    )
    assert c.base_url == "https://example/v1"
    assert c.model == "custom"


# ---------------------------------------------------------------- detector


def test_detect_python_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "AGENTS.md").write_text("# agent guide\nbe careful.\n")
    ctx = detect(tmp_path)
    assert ctx.language == "python"
    assert any(p.name == "AGENTS.md" for p in ctx.context_files)
    assert "be careful" in ctx.context_excerpt


def test_detect_node_project(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}")
    ctx = detect(tmp_path)
    assert ctx.language == "node"


def test_detect_unknown_language(tmp_path: Path) -> None:
    ctx = detect(tmp_path)
    assert ctx.language is None
    assert ctx.context_files == []


def test_detect_truncates_large_files(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("a" * 100_000)
    ctx = detect(tmp_path, max_excerpt_chars=1000)
    assert "truncated" in ctx.context_excerpt


# ---------------------------------------------------------------- auto-compact


@pytest.mark.asyncio
async def test_auto_compact_short_input() -> None:
    msgs = [{"role": "user", "content": "hi"}]
    out = await auto_compact(msgs, provider=None)  # type: ignore[arg-type]
    assert out is msgs


@pytest.mark.asyncio
async def test_auto_compact_collapses_old() -> None:
    msgs = [{"role": "user", "content": f"msg{i}"} for i in range(15)]
    out = await auto_compact(msgs, provider=None, keep_recent=5)  # type: ignore[arg-type]
    # We added a system summary, dropped 10 old user msgs, kept 5.
    assert len(out) == 6
    assert out[0]["role"] == "system"
    assert "auto-compact" in out[0]["content"]


# ---------------------------------------------------------------- web_search


@pytest.mark.asyncio
async def test_web_search_handles_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched_client)
    out = await web_search.web_search("python")
    assert "HTTP" in out or "error" in out.lower()


@pytest.mark.asyncio
async def test_web_search_parses_results(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    html = """
    <a class="result__a" href="https://example.com">Example Title</a>
    <a class="result__url" href="https://example.com">example.com</a>
    <a class="result__snippet">This is the snippet.</a>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched_client)
    out = await web_search.web_search("anything", max_results=3)
    assert "Example Title" in out
    assert "snippet" in out


# ---------------------------------------------------------------- CLI


def test_cli_help_runs(capsys) -> None:
    from ddw_code.cli import build_parser, main

    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "ddw-code" in captured.out


def test_cli_print_requires_prompt() -> None:
    from ddw_code.cli import main

    code = main(["--print", "--api-key", "sk-cp-x"])
    assert code == 2


def test_cli_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from ddw_code.cli import main

    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_TOKEN", raising=False)
    code = main(["--print", "hi"])
    assert code == 2


# ---------------------------------------------------------------- provider retry


@pytest.mark.asyncio
async def test_provider_max_retries_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    """All retries fail with 503; we get a single error event."""
    import httpx

    from ddw_code.providers.base import ChatRequest
    from ddw_code.providers.minimax import MiniMaxProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    async def no_sleep(_: int) -> None:
        return None

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = MiniMaxProvider("sk-cp-x", client=client)
        monkeypatch.setattr(prov, "_sleep_backoff", no_sleep)
        try:
            events = []
            async for ev in prov.chat(
                ChatRequest(system="", messages=[{"role": "user", "content": "go"}])
            ):
                events.append(ev)
                if ev.stop_reason:
                    break
        finally:
            await prov.aclose()
    errs = [e for e in events if e.error]
    assert errs
    assert "max retries" in errs[0].error or "503" in errs[0].error


@pytest.mark.asyncio
async def test_provider_invalid_json_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed SSE line is skipped, not fatal."""
    import httpx

    from ddw_code.providers.base import ChatRequest
    from ddw_code.providers.minimax import MiniMaxProvider

    body = "data: {not json}\ndata: [DONE]\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        prov = MiniMaxProvider("sk-cp-x", client=client)
        try:
            events = []
            async for ev in prov.chat(
                ChatRequest(system="", messages=[{"role": "user", "content": "go"}])
            ):
                events.append(ev)
                if ev.stop_reason:
                    break
        finally:
            await prov.aclose()
    # No text but a stop event.
    assert any(e.stop_reason for e in events)
