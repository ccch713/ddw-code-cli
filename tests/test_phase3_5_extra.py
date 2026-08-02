"""Extra integration tests to push coverage above 85%.

These target the trickier code paths: MCP with a fake stdio transport,
skills BM25 ranking edge cases, hook robustness, and the hub REST
fallback when fastapi isn't installed.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ddw_code.mcp.client import (
    MCPClient,
    MCPError,
    MCPManager,
    MCPServerConfig,
)
from ddw_code.mcp.stdio import StdioTransport
from ddw_code.skills.registry import SkillRegistry
from ddw_code.skills.slash_commands import SlashCommands
from ddw_code.hooks.manager import HookManager
from ddw_code.hub.rest import (
    handle_audit,
    handle_execute,
    handle_health,
    handle_tenant_usage,
    handle_webhook,
    try_build_fastapi_app,
    HttpResponse,
)
from ddw_code.hub.plugin import DDWPlugin, PluginResult, PluginTask
from ddw_code.hub.webhook import WebhookDispatcher, WebhookEndpoint
from ddw_code.hub.tenant import TenantStore, TenantConfig, UsageRecord
from ddw_code.compact.auto_compact import AutoCompact
from ddw_code.checkpoint.store import (
    CheckpointStore,
    checkpoint_save,
    checkpoint_load,
)


# =============================================================================
# MCP — fake transports
# =============================================================================


class _FakeStdioTransport:
    """A scripted stdio transport used in place of a real subprocess."""

    def __init__(self, scripts: list[dict[str, Any]] | None = None) -> None:
        self.scripts = list(scripts or [])
        self._outbox: list[str] = []
        self._closed = False

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        self._closed = True

    async def send(self, payload: str) -> None:
        if not self.scripts:
            return
        self._outbox.append(self.scripts.pop(0))

    async def recv(self) -> str | None:
        if not self._outbox:
            return None
        item = self._outbox.pop(0)
        if isinstance(item, dict):
            return json.dumps(item)
        return str(item)

    @property
    def is_closing(self) -> bool:
        return self._closed


@pytest.mark.asyncio
async def test_mcp_client_initialize_and_list_tools(monkeypatch) -> None:
    init_response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
        },
    }
    list_response = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "tools": [
                {"name": "echo", "description": "echo back", "inputSchema": {"type": "object"}}
            ]
        },
    }
    transport = _FakeStdioTransport(scripts=[init_response, list_response])
    cfg = MCPServerConfig(name="test", transport="stdio", command=["x"])
    client = MCPClient(cfg)
    # Inject the fake transport directly so connect() is a no-op.
    client._transport = transport  # type: ignore[assignment]
    cap = await client.initialize()
    assert cap["protocolVersion"] == "2024-11-05"
    tools = await client.list_tools()
    assert tools[0]["name"] == "echo"


@pytest.mark.asyncio
async def test_mcp_client_call_tool_success(monkeypatch) -> None:
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [{"type": "text", "text": "hello"}],
            "isError": False,
        },
    }
    transport = _FakeStdioTransport(scripts=[response])
    cfg = MCPServerConfig(name="t", transport="stdio", command=["x"])
    client = MCPClient(cfg)
    client._transport = transport  # type: ignore[assignment]
    result = await client.call_tool("echo", {"x": 1})
    assert result[0]["text"] == "hello"


@pytest.mark.asyncio
async def test_mcp_client_call_tool_error(monkeypatch) -> None:
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "isError": True,
            "content": [{"type": "text", "text": "boom"}],
        },
    }
    transport = _FakeStdioTransport(scripts=[response])
    cfg = MCPServerConfig(name="t", transport="stdio", command=["x"])
    client = MCPClient(cfg)
    client._transport = transport  # type: ignore[assignment]
    with pytest.raises(MCPError) as ei:
        await client.call_tool("broken", {})
    assert "boom" in str(ei.value)


@pytest.mark.asyncio
async def test_mcp_client_request_without_transport() -> None:
    cfg = MCPServerConfig(name="t", transport="stdio", command=["x"])
    client = MCPClient(cfg)
    with pytest.raises(MCPError):
        await client._request("tools/list")  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_mcp_client_handles_skipped_messages() -> None:
    """If the transport returns a message with an id we don't own, skip it."""
    # We use id=1 for the request, so the response for id=99 should be ignored.
    not_ours = {"jsonrpc": "2.0", "id": 99, "result": {"skipped": True}}
    response = {"jsonrpc": "2.0", "id": 1, "result": {"content": []}}
    transport = _FakeStdioTransport()
    transport._outbox = [not_ours, response]  # type: ignore[attr-defined]
    cfg = MCPServerConfig(name="t", transport="stdio", command=["x"])
    client = MCPClient(cfg)
    client._transport = transport  # type: ignore[assignment]
    result = await client._request("tools/list")  # type: ignore[attr-defined]
    assert result == {"content": []}


@pytest.mark.asyncio
async def test_mcp_client_recv_none_raises() -> None:
    transport = _FakeStdioTransport(scripts=[])
    cfg = MCPServerConfig(name="t", transport="stdio", command=["x"])
    client = MCPClient(cfg)
    client._transport = transport  # type: ignore[assignment]
    with pytest.raises(MCPError):
        await client._request("tools/list")  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_mcp_client_aclose_clears_transport() -> None:
    transport = _FakeStdioTransport()
    cfg = MCPServerConfig(name="t", transport="stdio", command=["x"])
    client = MCPClient(cfg)
    client._transport = transport  # type: ignore[assignment]
    await client.aclose()
    assert client._transport is None  # type: ignore[attr-defined]
    assert transport._closed


@pytest.mark.asyncio
async def test_mcp_client_context_manager() -> None:
    transport = _FakeStdioTransport()
    cfg = MCPServerConfig(name="t", transport="stdio", command=["x"])
    client = MCPClient(cfg)
    # Override connect() to skip the real subprocess.
    orig_connect = client.connect

    async def fake_connect() -> None:
        client._transport = transport  # type: ignore[assignment]

    client.connect = fake_connect  # type: ignore[assignment]
    async with client as c:
        assert c is client
        assert c._transport is not None  # type: ignore[attr-defined]
    assert client._transport is None  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_mcp_manager_close_all() -> None:
    mgr = MCPManager()
    # Inject two fake clients without going through connect().
    from ddw_code.mcp.client import MCPClient as _MCP

    c1 = _MCP(MCPServerConfig(name="a", transport="stdio", command=["x"]))
    c1._transport = _FakeStdioTransport()  # type: ignore[assignment]
    c2 = _MCP(MCPServerConfig(name="b", transport="stdio", command=["x"]))
    c2._transport = _FakeStdioTransport()  # type: ignore[assignment]
    mgr._clients = {"a": c1, "b": c2}  # type: ignore[attr-defined]
    await mgr.aclose()
    assert mgr.all() == {}


@pytest.mark.asyncio
async def test_mcp_manager_disconnect_unknown() -> None:
    mgr = MCPManager()
    assert await mgr.disconnect("nope") is False


# -----------------------------------------------------------------------------
# StdioTransport real-process smoke (only if `cat` exists)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stdio_transport_echo_smoke() -> None:
    if not shutil.which("cat"):
        pytest.skip("cat not available")
    t = StdioTransport(command=["cat"])
    await t.start()
    await t.send("hi\n")
    line = await t.recv()
    assert line == "hi"
    await t.close()


# -----------------------------------------------------------------------------
# SseTransport minimal
# -----------------------------------------------------------------------------


def test_sse_transport_constructs_with_headers() -> None:
    from ddw_code.mcp.sse import SseTransport
    t = SseTransport(url="https://x", headers={"X-Auth": "y"})
    assert t.headers.get("X-Auth") == "y"


# =============================================================================
# Skills — additional edge cases
# =============================================================================


def test_skill_registry_search_returns_scored() -> None:
    reg = SkillRegistry()
    reg.load_text("alpha", "alpha body content with keyword1")
    reg.load_text("beta", "beta body content with keyword2")
    results = reg.search("keyword1")
    assert results and results[0].skill.name == "alpha"
    assert results[0].score > 0


def test_skill_registry_search_empty_query() -> None:
    reg = SkillRegistry()
    reg.load_text("a", "body")
    assert reg.search("") == []


def test_skill_registry_search_no_match() -> None:
    reg = SkillRegistry()
    reg.load_text("a", "body about python")
    assert reg.search("nonexistent-zzz") == []


def test_skill_registry_load_directory_missing() -> None:
    reg = SkillRegistry()
    assert reg.load_directory("/nonexistent-path-zzz") == 0


def test_skill_registry_load_directory_empty(tmp_path: Path) -> None:
    reg = SkillRegistry()
    assert reg.load_directory(tmp_path) == 0


def test_skill_registry_reindex_after_unregister() -> None:
    reg = SkillRegistry()
    reg.load_text("a", "alpha content")
    reg.load_text("b", "beta content")
    reg.unregister("a")
    # After reindex, search should still work and only find b.
    results = reg.search("alpha")
    assert results == []
    results2 = reg.search("beta")
    assert any(r.skill.name == "b" for r in results2)


def test_skill_registry_rejects_duplicate_via_load_text() -> None:
    reg = SkillRegistry()
    reg.load_text("x", "body 1")
    with pytest.raises(ValueError):
        reg.load_text("x", "body 2")


def test_skill_registry_load_text_with_no_name() -> None:
    reg = SkillRegistry()
    skill = reg.load_text("explicit-name", "---\ndescription: x\n---\nbody")
    assert skill.name == "explicit-name"


@pytest.mark.asyncio
async def test_slash_commands_list() -> None:
    reg = SkillRegistry()
    reg.load_text("a", "body")
    reg.load_text("b", "body")
    sc = SlashCommands(reg)
    cmds = sc.list_commands()
    assert "/a" in cmds
    assert "/b" in cmds


@pytest.mark.asyncio
async def test_slash_commands_with_args() -> None:
    reg = SkillRegistry()
    reg.load_text("echo", "echo back")
    # Custom executor that surfaces the args.
    captured: list[tuple[str, str]] = []

    class _Ex:
        async def execute(self, name, instructions, args):
            captured.append((name, args))
            return f"{name}::{args}"

    sc = SlashCommands(reg, executor=_Ex())
    out = await sc.handle("/echo hello world")
    assert captured == [("echo", "hello world")]
    assert out == "echo::hello world"


# =============================================================================
# Hooks — robustness paths
# =============================================================================


@pytest.mark.asyncio
async def test_hooks_pre_tool_with_buggy_hook_followed_by_ok() -> None:
    mgr = HookManager()

    async def broken(name, args):
        raise RuntimeError("boom")

    async def ok(name, args):
        return None

    mgr.register_pre_tool(broken)
    mgr.register_pre_tool(ok)
    # ok still runs even though broken raised.
    assert await mgr.trigger_pre_tool("x", {}) is True


@pytest.mark.asyncio
async def test_hooks_post_tool_buggy_skipped() -> None:
    mgr = HookManager()

    async def broken(name, args, result):
        raise RuntimeError("boom")

    mgr.register_post_tool(broken)
    final = await mgr.trigger_post_tool("x", {}, "value")
    assert final == "value"


@pytest.mark.asyncio
async def test_hooks_lifecycle_buggy_skipped() -> None:
    mgr = HookManager()
    seen: list[str] = []

    async def broken(event, payload):
        raise RuntimeError("boom")

    async def ok(event, payload):
        seen.append(event)

    mgr.register_lifecycle(broken)
    mgr.register_lifecycle(ok)
    await mgr.trigger_lifecycle("start")
    assert seen == ["start"]


def test_hooks_counts() -> None:
    mgr = HookManager()

    async def nop(name, args):
        return None

    async def nop2(name, args, result):
        return result

    async def nop3(event, payload):
        return None

    mgr.register_pre_tool(nop)
    mgr.register_post_tool(nop2)
    mgr.register_lifecycle(nop3)
    assert mgr.pre_count == 1
    assert mgr.post_count == 1
    assert mgr.lifecycle_count == 1
    mgr.clear()
    assert mgr.pre_count == 0 and mgr.post_count == 0 and mgr.lifecycle_count == 0


# =============================================================================
# Hub REST — try-build-fastapi path
# =============================================================================


def test_try_build_fastapi_returns_none_or_app() -> None:
    """If fastapi is installed, returns an app; otherwise None."""
    plugin = DDWPlugin("p", "0.1.0", type("H", (), {"handle": lambda self, t: asyncio.sleep(0)})())
    d = WebhookDispatcher()
    s = TenantStore(base=Path("/tmp/ddw-tryfastapi"))
    app = try_build_fastapi_app(plugin, d, s)
    # Either we get an app (fastapi installed) or None (not installed). Both valid.
    if app is not None:
        assert app.title.startswith("ddw-code-cli")
    else:
        assert app is None


@pytest.mark.asyncio
async def test_tenant_usage_with_config_caps(tmp_path: Path) -> None:
    store = TenantStore(base=tmp_path)
    store.set_config(TenantConfig(tenant_id="acme", monthly_token_limit=20_000_000))
    # Add some usage that fits.
    store.record_usage(UsageRecord("acme", "u", "m", 100, 50))
    within, daily, monthly = store.usage_within_budget("acme")
    assert within
    assert daily == 150


def test_tenant_default_config_fresh(tmp_path: Path) -> None:
    store = TenantStore(base=tmp_path)
    cfg = store.get_config("brand-new")
    assert cfg.daily_token_limit > 0
    assert cfg.monthly_token_limit > 0
    assert cfg.allowed_models == []
    assert cfg.blocked_tools == []


def test_tenant_safe_id() -> None:
    assert TenantStore._safe("acme-corp!") == "acme-corp"  # type: ignore[attr-defined]


def test_tenant_list_sessions_empty(tmp_path: Path) -> None:
    store = TenantStore(base=tmp_path)
    assert store.audit_log("acme") == []


# =============================================================================
# Webhook — retry on failure
# =============================================================================


@pytest.mark.asyncio
async def test_webhook_retries_on_failure() -> None:
    """The dispatcher should retry up to max_retries times on failure."""
    attempts: list[str] = []

    async def flaky_post(url: str, *, body: str, headers: dict[str, str]) -> None:
        attempts.append(url)
        raise RuntimeError("transient")

    d = WebhookDispatcher(max_retries=1)
    d.set_transport(flaky_post)
    d.subscribe("e", WebhookEndpoint(url="https://x"))
    out = await d.dispatch("e", {})
    # max_retries=1 means 1 retry beyond the initial attempt, so 2 calls total.
    assert len(attempts) == 2
    # All attempts failed.
    assert out[0].error is not None
    assert "transient" in out[0].error


# =============================================================================
# AutoCompact — additional paths
# =============================================================================


@pytest.mark.asyncio
async def test_auto_compact_keeps_recent_intact() -> None:
    """The last `keep_recent` messages must be preserved verbatim."""

    class Stub:
        async def summarise(self, prompt):
            return "summary"

    msgs = [
        {"role": "user", "content": f"old {i}", "tag": "old"}
        for i in range(8)
    ] + [
        {"role": "user", "content": f"recent {i}", "tag": "recent"}
        for i in range(3)
    ]
    ac = AutoCompact(Stub(), threshold=0.0, keep_recent=3)
    out, changed = await ac.compact(msgs, context_window=10_000)
    assert changed
    # 1 summary + 3 recent = 4.
    assert len(out) == 4
    assert all(m.get("tag") == "recent" for m in out[1:])


@pytest.mark.asyncio
async def test_auto_compact_noop_when_provider_returns_empty() -> None:
    class Stub:
        async def summarise(self, prompt):
            return "   "

    msgs = [{"role": "user", "content": "x" * 1000}] * 5
    ac = AutoCompact(Stub(), threshold=0.1, keep_recent=2)
    out, changed = await ac.compact(msgs, context_window=200)
    assert changed is False
    assert out is msgs


# =============================================================================
# Checkpoint — list / paths
# =============================================================================


def test_checkpoint_store_list_sessions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("ddw_code.checkpoint.store._BASE", tmp_path)
    store = CheckpointStore()
    store.save("s1", {"x": 1})
    store.save("s2", {"x": 2})
    sessions = store.list_sessions()
    assert "s1" in sessions and "s2" in sessions


def test_checkpoint_store_resume(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("ddw_code.checkpoint.store._BASE", tmp_path)
    store = CheckpointStore()
    store.save("s", {"a": 1, "b": 2})
    state = store.resume("s")
    assert state == {"a": 1, "b": 2}


def test_checkpoint_store_resume_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("ddw_code.checkpoint.store._BASE", tmp_path)
    store = CheckpointStore()
    assert store.resume("missing") is None


def test_checkpoint_load_corrupt_returns_none(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("ddw_code.checkpoint.store._BASE", tmp_path)
    # Write garbage.
    (tmp_path / "s.json").write_text("not valid json", encoding="utf-8")
    store = CheckpointStore()
    assert store.load("s") is None


# =============================================================================
# Plugin — additional paths
# =============================================================================


@pytest.mark.asyncio
async def test_plugin_report_sink_swallows_exceptions() -> None:
    """A failing report sink must not mask the original task outcome."""

    class _Handler:
        async def handle(self, task):
            return "ok"

    async def bad_sink(result):
        raise RuntimeError("sink down")

    plugin = DDWPlugin("p", "0.1.0", _Handler(), report_sink=bad_sink)
    task = PluginTask.from_dict({})
    result = await plugin.execute(task)
    assert result.ok
    assert result.output == "ok"


@pytest.mark.asyncio
async def test_plugin_execute_assigns_id_when_missing() -> None:
    class _Handler:
        async def handle(self, t):
            return t.task_id

    plugin = DDWPlugin("p", "0.1.0", _Handler())
    result = await plugin.execute({"action": "chat"})
    assert result.ok
    assert result.output  # a uuid was generated


def test_plugin_task_from_dict_defaults() -> None:
    t = PluginTask.from_dict({})
    assert t.action == "chat"
    assert t.tenant_id == "default"
    assert t.user_id == "default"


def test_plugin_result_to_dict() -> None:
    r = PluginResult(task_id="t", ok=True, output="hi")
    d = r.to_dict()
    assert d["task_id"] == "t"
    assert d["ok"] is True
    assert d["output"] == "hi"
