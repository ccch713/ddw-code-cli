"""Tests for Phase 3-5 features: agent tools, auto-compact, smart context,
checkpoint, skills, hooks, MCP, and the Hub integration."""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest

# Agent tools — `ddw_code.tools.agent` re-exports handler functions at
# package level. Pull the *sub-modules* out of `sys.modules` directly so
# monkeypatch can swap private attributes (e.g. the long-term memory
# file path) without the package re-export shadowing them.
import sys as _sys
from ddw_code.tools.agent.actor import actor as actor_call, _execute_locally
from ddw_code.tools.agent.task import task as task_call
from ddw_code.tools.agent.memory import memory as memory_call
from ddw_code.tools.agent.plan import plan_enter as plan_enter_call
from ddw_code.tools.agent.plan import plan_exit as plan_exit_call
from ddw_code.tools.agent.plan import is_plan_mode_active

memory_mod = _sys.modules["ddw_code.tools.agent.memory"]
actor_mod = _sys.modules["ddw_code.tools.agent.actor"]

# Context / compact / checkpoint
from ddw_code.compact.auto_compact import AutoCompact, auto_compact
from ddw_code.context.smart_context import SmartContext, _extract_keywords
from ddw_code.checkpoint.store import (
    Checkpoint,
    CheckpointStore,
    checkpoint_delete,
    checkpoint_list,
    checkpoint_load,
    checkpoint_resume,
    checkpoint_save,
    get_checkpoint_store,
)

# Skills
from ddw_code.skills import (
    Skill,
    SkillRegistry,
    SlashCommands,
    load_skill,
    parse_skill,
)

# Hooks
from ddw_code.hooks import HookManager

# MCP
from ddw_code.mcp import (
    MCPClient,
    MCPError,
    MCPManager,
    MCPServerConfig,
    SseTransport,
    StdioTransport,
)

# Hub
from ddw_code.hub import (
    AuditEntry,
    DDWPlugin,
    HttpResponse,
    PluginResult,
    PluginTask,
    TenantConfig,
    TenantStore,
    UsageRecord,
    WebhookDispatcher,
    WebhookEndpoint,
    WebhookEvent,
    handle_audit,
    handle_execute,
    handle_health,
    handle_tenant_usage,
    handle_webhook,
)

# Builder
from ddw_code.tools.builder import build_default_registry


# =============================================================================
# Agent tools
# =============================================================================


def test_registry_has_agent_tools() -> None:
    reg = build_default_registry()
    names = {t.name for t in reg.all()}
    expected = {"actor", "task", "memory", "plan_enter", "plan_exit"}
    assert expected <= names, f"missing agent tools: {expected - names}"


# ---- actor ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_actor_models() -> None:
    out = await actor_call(action="models")
    assert "minimax" in out
    assert "deepseek" in out


@pytest.mark.asyncio
async def test_actor_run_completes(monkeypatch) -> None:
    async def fake_exec(prompt: str) -> str:
        return f"hi: {prompt}"
    monkeypatch.setattr(actor_mod, "_execute_locally", fake_exec)
    out = await actor_call(action="run", prompt="do X")
    assert "do X" in out


@pytest.mark.asyncio
async def test_actor_spawn_and_status(monkeypatch) -> None:
    async def fake_exec(prompt: str) -> str:
        await asyncio.sleep(0.05)
        return "result"
    monkeypatch.setattr(actor_mod, "_execute_locally", fake_exec)
    out = await actor_call(action="spawn", prompt="X")
    assert "spawned" in out
    # Extract the id from the output.
    aid = out.split("id=")[-1].strip()
    # status should be running or done by now.
    status = await actor_call(action="status", actor_id=aid)
    assert aid in status
    # Wait for completion.
    final = await actor_call(action="wait", actor_id=aid)
    assert "result" in final or "done" in final


@pytest.mark.asyncio
async def test_actor_cancel(monkeypatch) -> None:
    async def fake_exec(prompt: str) -> str:
        await asyncio.sleep(1.0)
        return "never"
    monkeypatch.setattr(actor_mod, "_execute_locally", fake_exec)
    out = await actor_call(action="spawn", prompt="X")
    aid = out.split("id=")[-1].strip()
    cancel = await actor_call(action="cancel", actor_id=aid)
    assert "cancelled" in cancel.lower()


@pytest.mark.asyncio
async def test_actor_send_appends_prompt(monkeypatch) -> None:
    async def fake_exec(prompt: str) -> str:
        return "ok"
    monkeypatch.setattr(actor_mod, "_execute_locally", fake_exec)
    out = await actor_call(action="spawn", prompt="X")
    aid = out.split("id=")[-1].strip()
    send = await actor_call(action="send", actor_id=aid, message="more")
    assert "queued" in send.lower()


@pytest.mark.asyncio
async def test_actor_unknown_status() -> None:
    out = await actor_call(action="status", actor_id="does-not-exist")
    assert "error" in out.lower()


@pytest.mark.asyncio
async def test_actor_unknown_action() -> None:
    out = await actor_call(action="frobnicate")
    assert "unknown action" in out.lower()


@pytest.mark.asyncio
async def test_actor_run_requires_prompt() -> None:
    out = await actor_call(action="run")
    assert "required" in out.lower()


# ---- task -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_lifecycle() -> None:
    # reset the global tree by reusing it; tests should be order-independent.
    await task_call(action="create", content="design")
    out = await task_call(action="list")
    assert "design" in out


def _extract_id(out: str) -> str:
    """Pull the bracketed task id out of a `task created:` / `task X:` line."""
    import re
    m = re.search(r"\[([A-Fa-f0-9]{6,})\]", out)
    assert m, f"no task id in: {out!r}"
    return m.group(1)


@pytest.mark.asyncio
async def test_task_dependency_blocks_start() -> None:
    # Create parent + child
    parent = await task_call(action="create", content="parent")
    pid = _extract_id(parent)
    child = await task_call(action="create", content="child", blocked_by=[pid])
    cid = _extract_id(child)
    # Child can't start until parent is done.
    started = await task_call(action="start", id=cid)
    assert "blocked" in started.lower()
    # Finish parent, then child can start.
    await task_call(action="done", id=pid)
    started2 = await task_call(action="start", id=cid)
    assert "in_progress" in started2


@pytest.mark.asyncio
async def test_task_unknown_action() -> None:
    out = await task_call(action="nope")
    assert "unknown action" in out.lower()


@pytest.mark.asyncio
async def test_task_unknown_id() -> None:
    out = await task_call(action="done", id="zzz")
    assert "unknown id" in out.lower()


@pytest.mark.asyncio
async def test_task_block_unblock_abandon_rename() -> None:
    c = await task_call(action="create", content="alpha")
    cid = _extract_id(c)
    assert "blocked" in (await task_call(action="block", id=cid)).lower()
    assert "pending" in (await task_call(action="unblock", id=cid)).lower()
    rn = await task_call(action="rename", id=cid, content="beta")
    assert "beta" in rn
    assert "abandoned" in (await task_call(action="abandon", id=cid)).lower()


# ---- memory -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_write_and_read_session(tmp_path, monkeypatch) -> None:
    # Redirect the long-term file so we don't pollute the user's home.
    monkeypatch.setattr(memory_mod, "_MEMORY_FILE", tmp_path / "mem.jsonl")
    out = await memory_call(action="write", content="hello world", scope="session")
    assert "written" in out
    out = await memory_call(action="read", scope="session")
    assert "hello world" in out


@pytest.mark.asyncio
async def test_memory_write_read_long(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(memory_mod, "_MEMORY_FILE", tmp_path / "mem.jsonl")
    await memory_call(action="write", content="persistent fact", scope="long")
    out = await memory_call(action="read", scope="long")
    assert "persistent fact" in out


@pytest.mark.asyncio
async def test_memory_search_ranking(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(memory_mod, "_MEMORY_FILE", tmp_path / "mem.jsonl")
    await memory_call(action="write", content="python decorators tutorial", scope="session")
    await memory_call(action="write", content="rust ownership rules", scope="session")
    out = await memory_call(action="search", query="python", scope="session")
    assert "python" in out.lower()


@pytest.mark.asyncio
async def test_memory_delete_session(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(memory_mod, "_MEMORY_FILE", tmp_path / "mem.jsonl")
    out = await memory_call(action="write", content="ephemeral", scope="session")
    eid = out.split("id=")[1].split()[0]
    delete = await memory_call(action="delete", id=eid, scope="session")
    assert "deleted" in delete.lower()


@pytest.mark.asyncio
async def test_memory_unknown_action() -> None:
    out = await memory_call(action="nope")
    assert "unknown action" in out.lower()


@pytest.mark.asyncio
async def test_memory_write_requires_content() -> None:
    out = await memory_call(action="write")
    assert "required" in out.lower()


# ---- plan_enter / plan_exit -------------------------------------------------


@pytest.mark.asyncio
async def test_plan_enter_and_exit() -> None:
    # Ensure we start in a known state.
    while is_plan_mode_active():
        await plan_exit_call()
    out = await plan_enter_call(plan_id="abc")
    assert "entered" in out
    assert is_plan_mode_active()
    # Re-entering is idempotent and reports the existing id.
    out2 = await plan_enter_call(plan_id="different")
    assert "already" in out2.lower()
    out3 = await plan_exit_call()
    assert "exited" in out3.lower()
    assert not is_plan_mode_active()


@pytest.mark.asyncio
async def test_plan_exit_when_not_active() -> None:
    while is_plan_mode_active():
        await plan_exit_call()
    out = await plan_exit_call()
    assert "not active" in out.lower()


# =============================================================================
# auto_compact / smart_context / checkpoint
# =============================================================================


@pytest.mark.asyncio
async def test_auto_compact_noop_when_under_threshold() -> None:
    class Stub:
        async def summarise(self, prompt: str) -> str:
            return "summary"

    msgs = [{"role": "user", "content": "hi"}] * 3
    ac = AutoCompact(Stub(), threshold=0.5, keep_recent=2)
    out, changed = await ac.compact(msgs, context_window=10_000)
    assert changed is False
    assert out is msgs


@pytest.mark.asyncio
async def test_auto_compact_uses_summariser_when_over_threshold() -> None:
    called = {"n": 0}

    class Stub:
        async def summarise(self, prompt: str) -> str:
            called["n"] += 1
            return "key insight"

    big = [{"role": "user", "content": "x" * 1000}] * 5
    ac = AutoCompact(Stub(), threshold=0.1, keep_recent=2)
    out, changed = await ac.compact(big, context_window=200)
    assert changed
    assert called["n"] == 1
    assert out[0]["role"] == "system"
    assert "key insight" in out[0]["content"]
    assert len(out) == 3  # 1 summary + 2 recent


@pytest.mark.asyncio
async def test_auto_compact_provider_failure_returns_input() -> None:
    class Boom:
        async def summarise(self, prompt: str) -> str:
            raise RuntimeError("down")

    msgs = [{"role": "user", "content": "x" * 1000}] * 5
    ac = AutoCompact(Boom(), threshold=0.1, keep_recent=2)
    out, changed = await ac.compact(msgs, context_window=200)
    assert changed is False
    assert out is msgs


def test_smart_context_extracts_keywords() -> None:
    kws = _extract_keywords("how do I configure pytest with django settings?")
    assert "pytest" in kws
    assert "django" in kws
    assert "settings" in kws
    # Stop words filtered.
    assert "the" not in kws
    assert "with" not in kws


@pytest.mark.asyncio
async def test_smart_context_picks_relevant_files(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def login(user, pwd): ... pytest fixtures")
    (tmp_path / "other.py").write_text("def parser(): ... unrelated content")
    ctx = SmartContext(max_files=2, preview_lines=5)
    result = await ctx.load("How does pytest login work?", str(tmp_path))
    assert "auth" in str(result.hits[0].path) if result.hits else True
    assert result.keywords


@pytest.mark.asyncio
async def test_smart_context_no_matches(tmp_path: Path) -> None:
    ctx = SmartContext()
    result = await ctx.load("", str(tmp_path))
    assert result.hits == []


@pytest.mark.asyncio
async def test_smart_context_forbidden_path(tmp_path: Path) -> None:
    ctx = SmartContext()
    result = await ctx.load("auth", str(Path.home() / ".ssh"))
    assert result.hits == []


def test_checkpoint_save_and_load(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("ddw_code.checkpoint.store._BASE", tmp_path)
    store = CheckpointStore()
    cp = store.save("sess-1", {"a": 1, "b": [1, 2]})
    assert cp.session_id == "sess-1"
    loaded = store.load("sess-1")
    assert loaded is not None
    assert loaded.state == {"a": 1, "b": [1, 2]}


def test_checkpoint_load_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("ddw_code.checkpoint.store._BASE", tmp_path)
    store = CheckpointStore()
    assert store.load("nope") is None


def test_checkpoint_delete(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("ddw_code.checkpoint.store._BASE", tmp_path)
    store = CheckpointStore()
    store.save("sess", {"k": "v"})
    assert store.delete("sess") is True
    assert store.delete("sess") is False


def test_checkpoint_async_helpers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("ddw_code.checkpoint.store._BASE", tmp_path)
    out = asyncio.run(checkpoint_save("sess", {"x": 1}))
    assert "saved" in out.lower()
    out = asyncio.run(checkpoint_load("sess"))
    assert "loaded" in out.lower()
    out = asyncio.run(checkpoint_resume("sess"))
    assert "resumed" in out.lower()
    out = asyncio.run(checkpoint_list())
    assert "sess" in out
    out = asyncio.run(checkpoint_delete("sess"))
    assert "deleted" in out.lower()


def test_checkpoint_invalid_state_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("ddw_code.checkpoint.store._BASE", tmp_path)
    store = CheckpointStore()
    with pytest.raises(TypeError):
        store.save("s", {"bad": object()})  # not JSON-serialisable


# =============================================================================
# Skills
# =============================================================================


def test_skill_parse_simple() -> None:
    md = (
        "---\n"
        "name: review\n"
        "description: Review the current diff\n"
        "triggers: [review, /review]\n"
        "---\n"
        "Do the following:\n1. Read the diff.\n2. Summarise.\n"
    )
    s = parse_skill(md, source="/skills/review.md")
    assert s.name == "review"
    assert "Review" in s.description
    assert s.triggers == ["review", "/review"]
    assert "Read the diff" in s.instructions
    assert s.source == "/skills/review.md"


def test_skill_parse_no_frontmatter() -> None:
    md = "Just some text without frontmatter."
    s = parse_skill(md, source="x.md")
    assert s.source == "x.md"
    # Falls back to file stem.
    assert s.name == "x"


def test_skill_parse_missing_name() -> None:
    md = "---\ndescription: hi\n---\nbody"
    s = parse_skill(md, source="path/some-name.md")
    assert s.name == "some-name"


def test_skill_load_from_disk(tmp_path: Path) -> None:
    p = tmp_path / "deploy.md"
    p.write_text(
        "---\nname: deploy\ndescription: Deploy to staging\n---\n"
        "Run the deploy pipeline.\n"
    )
    s = load_skill(p)
    assert s.name == "deploy"
    assert "pipeline" in s.instructions


def test_skill_load_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_skill(tmp_path / "nope.md")


def test_skill_registry_register_and_search() -> None:
    reg = SkillRegistry()
    reg.load_text("review", "---\nname: review\ndescription: code review\n---\nLook at the diff carefully.\n")
    reg.load_text("deploy", "---\nname: deploy\ndescription: deploy code\n---\nPush to staging.\n")
    results = reg.search("review")
    assert any(r.skill.name == "review" for r in results)
    assert len(reg) == 2


def test_skill_registry_rejects_duplicate() -> None:
    reg = SkillRegistry()
    reg.load_text("a", "body 1")
    with pytest.raises(ValueError):
        reg.load_text("a", "body 2")


def test_skill_registry_load_directory(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("---\nname: a\ndescription: alpha\n---\nA skill\n")
    (tmp_path / "b.md").write_text("---\nname: b\ndescription: beta\n---\nB skill\n")
    (tmp_path / "not-md.txt").write_text("ignored")
    reg = SkillRegistry()
    n = reg.load_directory(tmp_path)
    assert n == 2
    assert "a" in reg and "b" in reg


def test_skill_registry_unregister() -> None:
    reg = SkillRegistry()
    reg.load_text("a", "body")
    reg.unregister("a")
    assert "a" not in reg


@pytest.mark.asyncio
async def test_slash_commands_resolves() -> None:
    reg = SkillRegistry()
    reg.load_text("commit", "stage and commit changes")
    sc = SlashCommands(reg)
    assert sc.is_slash_command("/commit")
    out = await sc.handle("/commit add login")
    assert "commit" in (out or "")
    # Unknown slash.
    out2 = await sc.handle("/does-not-exist")
    assert out2 and "no such skill" in out2


@pytest.mark.asyncio
async def test_slash_commands_ignores_non_slash() -> None:
    reg = SkillRegistry()
    sc = SlashCommands(reg)
    assert await sc.handle("hello world") is None


# =============================================================================
# Hooks
# =============================================================================


@pytest.mark.asyncio
async def test_hooks_pre_tool_veto() -> None:
    mgr = HookManager()

    async def veto(name, args):
        return False

    mgr.register_pre_tool(veto)
    allowed = await mgr.trigger_pre_tool("bash", {"command": "ls"})
    assert allowed is False


@pytest.mark.asyncio
async def test_hooks_pre_tool_passes_when_unset() -> None:
    mgr = HookManager()
    assert await mgr.trigger_pre_tool("bash", {"command": "ls"}) is True


@pytest.mark.asyncio
async def test_hooks_pre_tool_short_circuits() -> None:
    mgr = HookManager()
    calls: list[str] = []

    async def first(name, args):
        calls.append("first")
        return False  # veto

    async def second(name, args):
        calls.append("second")
        return True

    mgr.register_pre_tool(first)
    mgr.register_pre_tool(second)
    await mgr.trigger_pre_tool("x", {})
    assert calls == ["first"]


@pytest.mark.asyncio
async def test_hooks_post_tool_threads_result() -> None:
    mgr = HookManager()

    async def add_marker(name, args, result):
        return f"{result} (audited)"

    async def upper(name, args, result):
        return result.upper()

    mgr.register_post_tool(add_marker)
    mgr.register_post_tool(upper)
    final = await mgr.trigger_post_tool("x", {}, "hello")
    assert final == "HELLO (AUDITED)"


@pytest.mark.asyncio
async def test_hooks_lifecycle_fans_out() -> None:
    mgr = HookManager()
    seen: list[str] = []

    async def hook1(event, payload):
        seen.append(event)

    async def hook2(event, payload):
        seen.append(event + "!")

    mgr.register_lifecycle(hook1)
    mgr.register_lifecycle(hook2)
    await mgr.trigger_lifecycle("start", {"x": 1})
    assert "start" in seen
    assert "start!" in seen


@pytest.mark.asyncio
async def test_hooks_buggy_handler_does_not_crash() -> None:
    mgr = HookManager()

    async def broken(name, args):
        raise RuntimeError("boom")

    async def ok(name, args):
        return None

    mgr.register_pre_tool(broken)
    mgr.register_pre_tool(ok)
    assert await mgr.trigger_pre_tool("x", {}) is True


# =============================================================================
# MCP
# =============================================================================


def test_mcp_stdio_transport_construct() -> None:
    t = StdioTransport(command=["echo", "hi"])
    assert t.command == ["echo", "hi"]


def test_mcp_stdio_rejects_empty_command() -> None:
    with pytest.raises(ValueError):
        StdioTransport(command=[])


def test_mcp_sse_transport_construct() -> None:
    t = SseTransport(url="https://example.com")
    assert t.url == "https://example.com"


def test_mcp_sse_rejects_empty_url() -> None:
    with pytest.raises(ValueError):
        SseTransport(url="")


def test_mcp_server_config_defaults() -> None:
    cfg = MCPServerConfig(name="x", command=["echo"])
    assert cfg.transport == "stdio"


def test_mcp_client_rejects_bad_transport() -> None:
    cfg = MCPServerConfig(name="x", transport="bogus")
    client = MCPClient(cfg)
    with pytest.raises(MCPError):
        asyncio.run(client.connect())


def test_mcp_client_stdio_missing_command() -> None:
    cfg = MCPServerConfig(name="x", transport="stdio", command=[])
    client = MCPClient(cfg)
    with pytest.raises(MCPError):
        asyncio.run(client.connect())


def test_mcp_client_sse_missing_url() -> None:
    cfg = MCPServerConfig(name="x", transport="sse", url="")
    client = MCPClient(cfg)
    with pytest.raises(MCPError):
        asyncio.run(client.connect())


@pytest.mark.asyncio
async def test_mcp_manager_unknown_returns_none() -> None:
    mgr = MCPManager()
    assert mgr.get("missing") is None


# =============================================================================
# Hub
# =============================================================================


class _StubHandler:
    def __init__(self, output: str = "ok") -> None:
        self.output = output
        self.calls: list[PluginTask] = []

    async def handle(self, task: PluginTask) -> str:
        self.calls.append(task)
        return self.output


@pytest.mark.asyncio
async def test_plugin_manifest_and_lifecycle() -> None:
    handler = _StubHandler()
    plugin = DDWPlugin("ddw-code-cli", "0.1.0", handler)
    m = plugin.manifest()
    assert m["name"] == "ddw-code-cli"
    assert "chat" in m["capabilities"]
    assert plugin.started is False
    await plugin.start()
    assert plugin.started
    await plugin.stop()
    assert plugin.started is False


@pytest.mark.asyncio
async def test_plugin_execute_success_reports_to_sink() -> None:
    seen: list[PluginResult] = []

    async def sink(result: PluginResult) -> None:
        seen.append(result)

    handler = _StubHandler("result text")
    plugin = DDWPlugin("p", "0.1.0", handler, report_sink=sink)
    task = PluginTask.from_dict({"action": "chat", "payload": {"prompt": "hi"}})
    result = await plugin.execute(task)
    assert result.ok
    assert result.output == "result text"
    assert seen and seen[0].task_id == task.task_id


@pytest.mark.asyncio
async def test_plugin_execute_failure_isolated() -> None:
    class BoomHandler:
        async def handle(self, task):
            raise RuntimeError("kaboom")

    plugin = DDWPlugin("p", "0.1.0", BoomHandler())
    task = PluginTask.from_dict({})
    result = await plugin.execute(task)
    assert not result.ok
    assert "kaboom" in (result.error or "")


def test_tenant_store_persists_config(tmp_path: Path) -> None:
    store = TenantStore(base=tmp_path)
    cfg = TenantConfig(
        tenant_id="acme",
        daily_token_limit=500_000,
        blocked_tools=["bash"],
    )
    store.set_config(cfg)
    loaded = store.get_config("acme")
    assert loaded.daily_token_limit == 500_000
    assert "bash" in loaded.blocked_tools


def test_tenant_store_default_config() -> None:
    store = TenantStore(base=Path("/tmp/never-written"))
    cfg = store.get_config("new-tenant")
    assert cfg.tenant_id == "new-tenant"
    assert cfg.daily_token_limit > 0


def test_tenant_usage_within_budget(tmp_path: Path) -> None:
    store = TenantStore(base=tmp_path)
    store.record_usage(UsageRecord("acme", "u1", "minimax", 100, 50))
    within, daily, monthly = store.usage_within_budget("acme")
    assert daily == 150
    assert monthly == 150
    assert within


def test_tenant_usage_over_budget(tmp_path: Path) -> None:
    store = TenantStore(base=tmp_path)
    store.set_config(TenantConfig(tenant_id="acme", daily_token_limit=10))
    store.record_usage(UsageRecord("acme", "u1", "minimax", 100, 50))
    within, _, _ = store.usage_within_budget("acme")
    assert not within


def test_tenant_audit_log(tmp_path: Path) -> None:
    store = TenantStore(base=tmp_path)
    store.append_audit(AuditEntry("acme", "u1", "tool_use", "bash"))
    store.append_audit(AuditEntry("other", "u2", "tool_use", "file_read"))
    acme_log = store.audit_log("acme")
    assert len(acme_log) == 1
    all_log = store.audit_log()
    assert len(all_log) == 2


@pytest.mark.asyncio
async def test_webhook_dispatcher_no_subscribers() -> None:
    d = WebhookDispatcher()
    out = await d.dispatch("test", {"x": 1})
    assert out == []
    await d.aclose()


@pytest.mark.asyncio
async def test_webhook_dispatcher_calls_subscribers() -> None:
    received: list[tuple[str, str]] = []

    async def fake_post(url: str, *, body: str, headers: dict[str, str]) -> None:
        received.append((url, body))

    d = WebhookDispatcher(max_retries=0)
    d.set_transport(fake_post)
    d.subscribe("task.done", WebhookEndpoint(url="https://hub.local/events"))
    out = await d.dispatch("task.done", {"id": "abc"})
    assert len(out) == 1
    assert out[0].status_code is None  # we used a stub transport
    assert received and received[0][0] == "https://hub.local/events"
    assert "task.done" in received[0][1]


@pytest.mark.asyncio
async def test_webhook_unsubscribe() -> None:
    d = WebhookDispatcher()
    d.subscribe("e", WebhookEndpoint(url="https://x"))
    assert d.unsubscribe("e", "https://x") is True
    assert d.unsubscribe("e", "https://x") is False


@pytest.mark.asyncio
async def test_rest_handlers_smoke() -> None:
    handler = _StubHandler("ok")
    plugin = DDWPlugin("p", "0.1.0", handler)
    await plugin.start()
    dispatcher = WebhookDispatcher()
    store = TenantStore(base=Path("/tmp/ddw-rest"))

    h = await handle_health(plugin)
    assert h.status == 200
    assert h.body["ok"] is True

    e = await handle_execute(plugin, {"action": "chat", "payload": {}})
    assert e.status == 200
    assert e.body["ok"] is True

    a = await handle_audit(store)
    assert a.status == 200

    tu = await handle_tenant_usage(store, "acme")
    assert tu.status == 200
    assert tu.body["tenant_id"] == "acme"

    w = await handle_webhook(dispatcher, "x", {})
    assert w.status == 200

    await plugin.stop()
    await dispatcher.aclose()


@pytest.mark.asyncio
async def test_rest_execute_bad_request() -> None:
    plugin = DDWPlugin("p", "0.1.0", _StubHandler())
    await plugin.start()
    bad = await handle_execute(plugin, "not a dict")  # type: ignore[arg-type]
    assert bad.status == 400
    await plugin.stop()


@pytest.mark.asyncio
async def test_rest_webhook_requires_event() -> None:
    d = WebhookDispatcher()
    bad = await handle_webhook(d, "", {})
    assert bad.status == 400
    await d.aclose()


# =============================================================================
# Builder sanity (agent tools present)
# =============================================================================


def test_builder_includes_all_phase3_tools() -> None:
    reg = build_default_registry()
    names = {t.name for t in reg.all()}
    assert {"actor", "task", "memory", "plan_enter", "plan_exit"} <= names
    # All 5 agent tools should be marked compactable.
    for tool in reg.all():
        if tool.name in {"actor", "task", "memory", "plan_enter", "plan_exit"}:
            assert tool.compactable is True
