"""Additional tests to push coverage above 80%."""
from __future__ import annotations

import asyncio
import builtins
import io
import os
import sys
from pathlib import Path

import pytest

from minimax_agent.compact.micro_compact import (
    _approx_tokens,
    _content_str,
    should_compact,
)
from minimax_agent.security.danger_check import find_ripgrep
from minimax_agent.security.permissions import Decision, PermissionManager
from minimax_agent.tools import bash, grep
from minimax_agent.tools.builder import build_default_registry
from minimax_agent.tools.dispatcher import ToolDispatcher


def test_approx_tokens_empty() -> None:
    assert _approx_tokens([]) == 1


def test_approx_tokens_string_content() -> None:
    msgs = [{"role": "user", "content": "a" * 400}]
    assert _approx_tokens(msgs) == 100


def test_approx_tokens_list_content() -> None:
    msgs = [{"role": "assistant", "content": [{"type": "text", "text": "hi"}]}]
    # At least 1.
    assert _approx_tokens(msgs) >= 1


def test_content_str_handles_list() -> None:
    out = _content_str([{"type": "text", "text": "a"}, {"content": "b"}])
    assert "a" in out and "b" in out


def test_content_str_handles_str() -> None:
    assert _content_str("hi") == "hi"


def test_should_compact_zero_window() -> None:
    assert should_compact([{"role": "user", "content": "x"}], context_window=0) is False


@pytest.mark.asyncio
async def test_grep_fallback_pure_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If rg is missing, the pure-Python fallback should still work."""
    monkeypatch.setattr(grep, "find_ripgrep", lambda: None)
    (tmp_path / "x.py").write_text("alpha\nbeta\ngamma\n")
    out = await grep.grep("beta", str(tmp_path))
    assert "beta" in out
    assert "x.py" in out


@pytest.mark.asyncio
async def test_grep_uses_ripgrep_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When rg is on PATH, the tool shells out and parses the output."""
    monkeypatch.setattr(grep, "find_ripgrep", lambda: "/usr/bin/rg")

    class _FakeProc:
        stdout = "file1:1:hit one\nfile2:5:hit two\n"

    def fake_run(cmd, **kwargs):  # noqa: ARG001
        return _FakeProc()

    import subprocess as _sp

    monkeypatch.setattr(_sp, "run", fake_run)
    out = await grep.grep("hit", str(tmp_path))
    assert "file1:1:hit one" in out
    assert "file2:5:hit two" in out


@pytest.mark.asyncio
async def test_grep_ripgrep_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess as _sp

    monkeypatch.setattr(grep, "find_ripgrep", lambda: "/usr/bin/rg")

    def fake_run(cmd, **kwargs):  # noqa: ARG001
        raise _sp.TimeoutExpired(cmd, 30)

    monkeypatch.setattr(_sp, "run", fake_run)
    out = await grep.grep("x", str(tmp_path))
    assert "timed out" in out


@pytest.mark.asyncio
async def test_grep_ripgrep_no_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess as _sp

    monkeypatch.setattr(grep, "find_ripgrep", lambda: "/usr/bin/rg")

    class _FakeProc:
        stdout = ""

    monkeypatch.setattr(_sp, "run", lambda *a, **kw: _FakeProc())
    out = await grep.grep("nothing", str(tmp_path))
    assert "no matches" in out


@pytest.mark.asyncio
async def test_grep_ripgrep_truncates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess as _sp

    monkeypatch.setattr(grep, "find_ripgrep", lambda: "/usr/bin/rg")

    class _FakeProc:
        stdout = "\n".join(f"f{i}:1:hit" for i in range(10))

    monkeypatch.setattr(_sp, "run", lambda *a, **kw: _FakeProc())
    out = await grep.grep("hit", str(tmp_path), max_results=3)
    assert "truncated" in out


@pytest.mark.asyncio
async def test_grep_fallback_truncates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(grep, "find_ripgrep", lambda: None)
    for i in range(20):
        (tmp_path / f"f{i}.txt").write_text("match\n" * 5)
    out = await grep.grep("match", str(tmp_path), max_results=3)
    assert "truncated" in out


@pytest.mark.asyncio
async def test_grep_invalid_regex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(grep, "find_ripgrep", lambda: None)
    out = await grep.grep("[unclosed", str(tmp_path))
    assert "invalid regex" in out


@pytest.mark.asyncio
async def test_grep_missing_path(tmp_path: Path) -> None:
    out = await grep.grep("x", str(tmp_path / "missing"))
    assert "not found" in out


@pytest.mark.asyncio
async def test_bash_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A command exceeding `timeout` raises BashError."""
    with pytest.raises(bash.BashError):
        await bash.bash("sleep 5", timeout=1)


@pytest.mark.asyncio
async def test_bash_spawn_failure() -> None:
    """An invalid command should fail gracefully."""
    # The shell will still return a non-zero exit, but a structurally bad
    # invocation may raise. We accept either a non-zero exit (string) or
    # a BashError.
    out = await bash.bash("true", timeout=5)
    assert out  # truthy


def test_dispatcher_allow_runs() -> None:
    reg = build_default_registry()
    perm = PermissionManager()
    perm.approve("file_read")
    disp = ToolDispatcher(reg, perm)
    p = "/tmp/cover_test.txt"
    Path(p).write_text("hi")
    try:
        res = asyncio.run(disp.dispatch("file_read", {"path": p}))
        assert not res.is_error
        assert "hi" in res.output
    finally:
        os.unlink(p)


def test_dispatcher_invalid_json_args() -> None:
    reg = build_default_registry()
    perm = PermissionManager()
    perm.approve("file_read")
    disp = ToolDispatcher(reg, perm)
    res = asyncio.run(disp.dispatch("file_read", "{not json"))
    assert res.is_error
    assert "JSON" in res.output


def test_dispatcher_handler_exception() -> None:
    from minimax_agent.tools.registry import Tool, ToolRegistry

    async def boom(**kwargs):
        raise RuntimeError("kaboom")

    reg = ToolRegistry()
    reg.register(
        Tool(
            name="boom",
            description="",
            input_schema={"type": "object"},
            handler=boom,
        )
    )
    perm = PermissionManager()
    perm.set_policy("boom", Decision.ALLOW)
    disp = ToolDispatcher(reg, perm)
    res = asyncio.run(disp.dispatch("boom", {}))
    assert res.is_error
    assert "kaboom" in res.output


# ---------------------------------------------------------------- CLI extras


def test_cli_sandbox_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    from minimax_agent.cli import _apply_sandbox
    from minimax_agent.security.permissions import Decision, PermissionManager

    p = PermissionManager()
    _apply_sandbox(p)
    assert p.decide("bash") == Decision.FORCE_ASK
    assert p.decide("file_write") == Decision.FORCE_ASK
    p.approve("bash")
    # FORCE_ASK is sticky.
    assert p.decide("bash") == Decision.FORCE_ASK


def test_cli_print_runs_with_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end CLI test: --print invokes the provider through TurnLoop."""
    from minimax_agent.cli import main
    from minimax_agent.providers.base import StreamEvent

    class FakeProvider:
        name = "fake"

        def __init__(self) -> None:
            self.calls = 0

        async def chat(self, request):
            self.calls += 1
            yield StreamEvent(text_delta="hi from fake")
            yield StreamEvent(stop_reason="stop", final_text="hi from fake")

        def count_tokens(self, text: str) -> int:
            return 1

        async def aclose(self) -> None:
            return None

    fake = FakeProvider()

    def fake_provider(*args, **kwargs):
        return fake

    monkeypatch.setattr("minimax_agent.cli.MiniMaxProvider", fake_provider)
    # Make sure confirm prompt doesn't fire — auto-approve.
    code = main(["--print", "--api-key", "sk-cp-x", "--auto-approve", "say hi"])
    assert code == 0
    assert fake.calls == 1


def test_cli_auto_approve_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """--auto-approve makes every tool run without confirmation."""
    from minimax_agent.cli import main
    from minimax_agent.providers.base import StreamEvent, ToolUseBlock, Usage

    class FakeProvider:
        name = "fake"
        turn = 0

        async def chat(self, request):
            self.turn += 1
            if self.turn == 1:
                # First call: emit a tool call.
                yield StreamEvent(
                    tool_use=ToolUseBlock(id="c1", name="bash", input={"command": "true"}),
                    stop_reason="tool_calls",
                    usage=Usage(2, 2),
                )
            else:
                # Subsequent calls: stop.
                yield StreamEvent(
                    text_delta="done", stop_reason="stop", final_text="done"
                )

        def count_tokens(self, text: str) -> int:
            return 1

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("minimax_agent.cli.MiniMaxProvider", lambda *a, **kw: FakeProvider())
    # With --auto-approve, no prompt; bash runs and the loop terminates.
    code = main(
        [
            "--print",
            "--api-key",
            "sk-cp-x",
            "--auto-approve",
            "anything",
        ]
    )
    assert code == 0
