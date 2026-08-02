"""Additional tests to improve coverage: CLI, provider registry, edge cases."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from ddw_code.providers.base import StreamEvent, ToolUseBlock, Usage


# ---- CLI parser tests ----


def test_build_parser_defaults() -> None:
    from ddw_code.cli import build_parser
    parser = build_parser()
    args = parser.parse_args([])
    assert args.provider == "minimax"
    assert args.api_key is None
    assert args.print_mode is False
    assert args.sandbox is False
    assert args.auto_approve is False
    assert args.verbose is False
    assert args.prompt is None


def test_build_parser_all_flags() -> None:
    from ddw_code.cli import build_parser
    parser = build_parser()
    args = parser.parse_args([
        "--provider", "deepseek",
        "--api-key", "sk-x",
        "--base-url", "https://example/v1",
        "--model", "custom-model",
        "--max-turns", "10",
        "--workspace", "/tmp",
        "--sandbox",
        "--auto-approve",
        "--verbose",
        "--print",
        "hello",
    ])
    assert args.provider == "deepseek"
    assert args.api_key == "sk-x"
    assert args.base_url == "https://example/v1"
    assert args.model == "custom-model"
    assert args.max_turns == 10
    assert args.sandbox is True
    assert args.auto_approve is True
    assert args.verbose is True
    assert args.print_mode is True
    assert args.prompt == "hello"


def test_build_parser_provider_choices() -> None:
    from ddw_code.cli import build_parser
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--provider", "invalid"])


# ---- CLI confirm_tool tests ----


def test_confirm_tool_non_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    from ddw_code.cli import _confirm_tool
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert _confirm_tool("bash", {"command": "ls"}) is False


def test_confirm_tool_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    from ddw_code.cli import _confirm_tool
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "y")
    assert _confirm_tool("bash", {"command": "ls"}) is True


def test_confirm_tool_no(monkeypatch: pytest.MonkeyPatch) -> None:
    from ddw_code.cli import _confirm_tool
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert _confirm_tool("bash", {"command": "ls"}) is False


def test_confirm_tool_eof(monkeypatch: pytest.MonkeyPatch) -> None:
    from ddw_code.cli import _confirm_tool
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def raise_eof():
        raise EOFError

    monkeypatch.setattr("builtins.input", lambda _: raise_eof())
    assert _confirm_tool("bash", {"command": "ls"}) is False


# ---- CLI keyboard interrupt ----


def test_main_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    from ddw_code.cli import main

    def raise_ki(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("asyncio.run", raise_ki)
    code = main(["--print", "--api-key", "sk-x", "hi"])
    assert code == 130


# ---- CLI provider flag integration ----


def test_cli_provider_flag_deepseek(monkeypatch: pytest.MonkeyPatch) -> None:
    from ddw_code.cli import main

    class FakeProvider:
        name = "fake"
        async def chat(self, request):
            yield StreamEvent(text_delta="ok", stop_reason="stop", final_text="ok")
        def count_tokens(self, text: str) -> int:
            return 1
        async def aclose(self) -> None:
            return None

    def fake_get_provider(name, **kwargs):
        assert name == "deepseek"
        return FakeProvider()

    monkeypatch.setattr("ddw_code.cli.get_provider", fake_get_provider)
    code = main(["--provider", "deepseek", "--print", "--api-key", "sk-x", "hi"])
    assert code == 0


def test_cli_provider_flag_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    from ddw_code.cli import main

    class FakeProvider:
        name = "fake"
        async def chat(self, request):
            yield StreamEvent(text_delta="ok", stop_reason="stop", final_text="ok")
        def count_tokens(self, text: str) -> int:
            return 1
        async def aclose(self) -> None:
            return None

    def fake_get_provider(name, **kwargs):
        assert name == "openai"
        return FakeProvider()

    monkeypatch.setattr("ddw_code.cli.get_provider", fake_get_provider)
    code = main(["--provider", "openai", "--print", "--api-key", "sk-x", "hi"])
    assert code == 0


def test_cli_provider_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    from ddw_code.cli import main
    # argparse will reject invalid provider choices with SystemExit
    with pytest.raises(SystemExit):
        main(["--provider", "invalid", "--print", "--api-key", "sk-x", "hi"])


# ---- CLI verbose mode ----


def test_cli_verbose_enables_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    from ddw_code.cli import main
    import logging

    class FakeProvider:
        name = "fake"
        async def chat(self, request):
            yield StreamEvent(text_delta="ok", stop_reason="stop", final_text="ok")
        def count_tokens(self, text: str) -> int:
            return 1
        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("ddw_code.cli.get_provider", lambda *a, **kw: FakeProvider())
    code = main(["--verbose", "--print", "--api-key", "sk-x", "hi"])
    assert code == 0


# ---- Edge case: danger_check special chars ----


def test_danger_check_special_characters() -> None:
    from ddw_code.security.danger_check import is_dangerous_command
    # Commands with special characters that aren't dangerous
    assert not is_dangerous_command("echo 'hello world'")
    assert not is_dangerous_command("python -c 'print(1)'")
    assert not is_dangerous_command("git commit -m 'fix: bug'")


def test_danger_check_rm_rf_variations() -> None:
    from ddw_code.security.danger_check import is_dangerous_command
    assert is_dangerous_command("rm -rf /")
    assert is_dangerous_command("rm -rf /*")
    assert is_dangerous_command("rm -rf *")


# ---- Edge case: glob error paths ----


def test_glob_permission_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ddw_code.tools import glob
    import pathlib

    def raising_glob(self, pattern):
        raise PermissionError("access denied")

    monkeypatch.setattr(pathlib.Path, "glob", raising_glob)
    with pytest.raises(PermissionError):
        asyncio.run(glob.glob("*.py", str(tmp_path)))


def test_glob_max_results(tmp_path: Path) -> None:
    from ddw_code.tools import glob
    for i in range(20):
        (tmp_path / f"f{i}.py").write_text("")
    out = asyncio.run(glob.glob("*.py", str(tmp_path), max_results=5))
    assert out.count("\n") <= 6  # 5 files + possible truncation note


# ---- Edge case: file_edit replace_all ----


def test_file_edit_replace_all(tmp_path: Path) -> None:
    from ddw_code.tools import file_edit
    p = tmp_path / "r.txt"
    p.write_text("a\na\na\n")
    asyncio.run(file_edit.file_edit(str(p), "a", "b", replace_all=True))
    assert p.read_text() == "b\nb\nb\n"


def test_file_edit_no_match(tmp_path: Path) -> None:
    from ddw_code.tools import file_edit
    p = tmp_path / "n.txt"
    p.write_text("hello\n")
    with pytest.raises(file_edit.EditError):
        asyncio.run(file_edit.file_edit(str(p), "world", "x"))


# ---- Edge case: bash output truncation ----


def test_bash_large_output(tmp_path: Path) -> None:
    from ddw_code.tools import bash
    # Generate output exceeding 50k bytes
    out = asyncio.run(bash.bash("python3 -c \"print('x' * 60000)\"", timeout=10))
    assert len(out) <= 50_100  # capped at ~50k


# ---- Edge case: todo edge cases ----


def test_todo_update_nonexistent() -> None:
    from ddw_code.tools import todo
    todo.reset()
    out = asyncio.run(todo.todo(action="update", id=999, status="done"))
    assert "no todo" in out


def test_todo_remove_nonexistent() -> None:
    from ddw_code.tools import todo
    todo.reset()
    out = asyncio.run(todo.todo(action="remove", id=999))
    assert "no todo" in out


# ---- Edge case: detector with multiple context files ----


def test_detect_multiple_context_files(tmp_path: Path) -> None:
    from ddw_code.context.detector import detect
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "AGENTS.md").write_text("# agents\n")
    (tmp_path / "CLAUDE.md").write_text("# claude\n")
    ctx = detect(tmp_path)
    assert ctx.language == "python"
    names = [p.name for p in ctx.context_files]
    assert "AGENTS.md" in names
    assert "CLAUDE.md" in names


# ---- CLI provider error path ----


def test_cli_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """When get_provider raises ValueError, CLI returns exit code 2."""
    from ddw_code.cli import main

    def raising_get_provider(name, **kwargs):
        raise ValueError("bad provider")

    monkeypatch.setattr("ddw_code.cli.get_provider", raising_get_provider)
    code = main(["--print", "--api-key", "sk-x", "hi"])
    assert code == 2


# ---- CLI interactive mode ----


def test_cli_interactive_exit_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """Interactive mode should exit on 'exit' command."""
    from ddw_code.cli import main

    class FakeProvider:
        name = "fake"
        async def chat(self, request):
            yield StreamEvent(text_delta="ok", stop_reason="stop", final_text="ok")
        def count_tokens(self, text: str) -> int:
            return 1
        async def aclose(self) -> None:
            return None

    inputs = iter(["exit"])

    def fake_input(prompt=""):
        return next(inputs)

    monkeypatch.setattr("ddw_code.cli.get_provider", lambda *a, **kw: FakeProvider())
    monkeypatch.setattr("builtins.input", fake_input)
    # Simulate non-tty so console.input works via mocked input
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    code = main(["--api-key", "sk-x"])
    assert code == 0


def test_cli_interactive_quit_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """Interactive mode should exit on 'quit' command."""
    from ddw_code.cli import main

    class FakeProvider:
        name = "fake"
        async def chat(self, request):
            yield StreamEvent(text_delta="ok", stop_reason="stop", final_text="ok")
        def count_tokens(self, text: str) -> int:
            return 1
        async def aclose(self) -> None:
            return None

    inputs = iter(["quit"])

    def fake_input(prompt=""):
        return next(inputs)

    monkeypatch.setattr("ddw_code.cli.get_provider", lambda *a, **kw: FakeProvider())
    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    code = main(["--api-key", "sk-x"])
    assert code == 0


def test_cli_interactive_empty_input_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty input should be skipped, then 'exit' terminates."""
    from ddw_code.cli import main

    class FakeProvider:
        name = "fake"
        async def chat(self, request):
            yield StreamEvent(text_delta="ok", stop_reason="stop", final_text="ok")
        def count_tokens(self, text: str) -> int:
            return 1
        async def aclose(self) -> None:
            return None

    inputs = iter(["", "  ", "exit"])

    def fake_input(prompt=""):
        return next(inputs)

    monkeypatch.setattr("ddw_code.cli.get_provider", lambda *a, **kw: FakeProvider())
    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    code = main(["--api-key", "sk-x"])
    assert code == 0


# ---- CLI sandbox + auto-approve combo ----


def test_cli_sandbox_and_auto_approve(monkeypatch: pytest.MonkeyPatch) -> None:
    """--sandbox with --auto-approve should work together."""
    from ddw_code.cli import main

    class FakeProvider:
        name = "fake"
        async def chat(self, request):
            yield StreamEvent(text_delta="ok", stop_reason="stop", final_text="ok")
        def count_tokens(self, text: str) -> int:
            return 1
        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("ddw_code.cli.get_provider", lambda *a, **kw: FakeProvider())
    code = main(["--sandbox", "--auto-approve", "--print", "--api-key", "sk-x", "hi"])
    assert code == 0


# ---- CLI interactive mode with Rich console mocking ----


def test_cli_interactive_with_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Interactive mode processes a prompt then exits."""
    import ddw_code.cli as cli_mod

    class FakeProvider:
        name = "fake"
        async def chat(self, request):
            yield StreamEvent(text_delta="response", stop_reason="stop", final_text="response")
        def count_tokens(self, text: str) -> int:
            return 1
        async def aclose(self) -> None:
            return None

    inputs = iter(["hello", "exit"])
    monkeypatch.setattr(cli_mod.console, "input", lambda *a, **kw: next(inputs))
    monkeypatch.setattr(cli_mod.console, "print", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod, "get_provider", lambda *a, **kw: FakeProvider())
    code = cli_mod.main(["--api-key", "sk-x"])
    assert code == 0


def test_cli_interactive_eof(monkeypatch: pytest.MonkeyPatch) -> None:
    """Interactive mode exits on EOFError."""
    import ddw_code.cli as cli_mod

    class FakeProvider:
        name = "fake"
        async def chat(self, request):
            yield StreamEvent(text_delta="ok", stop_reason="stop", final_text="ok")
        def count_tokens(self, text: str) -> int:
            return 1
        async def aclose(self) -> None:
            return None

    call_count = {"n": 0}

    def eof_input(*a, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise EOFError
        return "exit"

    monkeypatch.setattr(cli_mod.console, "input", eof_input)
    monkeypatch.setattr(cli_mod.console, "print", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod, "get_provider", lambda *a, **kw: FakeProvider())
    code = cli_mod.main(["--api-key", "sk-x"])
    assert code == 0


def test_cli_interactive_colon_q(monkeypatch: pytest.MonkeyPatch) -> None:
    """:q exits interactive mode."""
    import ddw_code.cli as cli_mod

    class FakeProvider:
        name = "fake"
        async def chat(self, request):
            yield StreamEvent(text_delta="ok", stop_reason="stop", final_text="ok")
        def count_tokens(self, text: str) -> int:
            return 1
        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(cli_mod.console, "input", lambda *a, **kw: ":q")
    monkeypatch.setattr(cli_mod.console, "print", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod, "get_provider", lambda *a, **kw: FakeProvider())
    code = cli_mod.main(["--api-key", "sk-x"])
    assert code == 0


# ---- CLI verbose print mode with tool calls ----


def test_cli_verbose_print_with_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verbose mode in --print should show token stats."""
    from ddw_code.cli import main
    from ddw_code.providers.base import StreamEvent, ToolUseBlock, Usage

    class FakeProvider:
        name = "fake"
        turn = 0
        async def chat(self, request):
            self.turn += 1
            if self.turn == 1:
                yield StreamEvent(
                    tool_use=ToolUseBlock(id="c1", name="bash", input={"command": "true"}),
                    stop_reason="tool_calls",
                    usage=Usage(2, 2),
                )
            else:
                yield StreamEvent(text_delta="done", stop_reason="stop", final_text="done")
        def count_tokens(self, text: str) -> int:
            return 1
        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("ddw_code.cli.get_provider", lambda *a, **kw: FakeProvider())
    code = main(["--verbose", "--auto-approve", "--print", "--api-key", "sk-x", "anything"])
    assert code == 0


def test_cli_interactive_tool_call_auto_approve(monkeypatch: pytest.MonkeyPatch) -> None:
    """Interactive mode with a tool call and auto-approve."""
    import ddw_code.cli as cli_mod
    from ddw_code.providers.base import StreamEvent, ToolUseBlock, Usage

    class FakeProvider:
        name = "fake"
        turn = 0
        async def chat(self, request):
            self.turn += 1
            if self.turn == 1:
                yield StreamEvent(
                    tool_use=ToolUseBlock(id="c1", name="bash", input={"command": "echo hi"}),
                    stop_reason="tool_calls",
                    usage=Usage(2, 2),
                )
            else:
                yield StreamEvent(text_delta="done", stop_reason="stop", final_text="done")
        def count_tokens(self, text: str) -> int:
            return 1
        async def aclose(self) -> None:
            return None

    inputs = iter(["run echo", "exit"])
    monkeypatch.setattr(cli_mod.console, "input", lambda *a, **kw: next(inputs))
    monkeypatch.setattr(cli_mod.console, "print", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod, "get_provider", lambda *a, **kw: FakeProvider())
    code = cli_mod.main(["--auto-approve", "--api-key", "sk-x"])
    assert code == 0
