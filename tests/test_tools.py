"""Tests for the built-in tools."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ddw_code.tools import (
    bash,
    file_edit,
    file_read,
    file_write,
    glob,
    grep,
    todo,
    web_search,
)
from ddw_code.tools.builder import build_default_registry
from ddw_code.tools.dispatcher import ToolDispatcher
from ddw_code.security.permissions import PermissionManager


def test_registry_contains_original_eight_tools() -> None:
    """The 8 original tools are still present after the Phase 1 expansion."""
    reg = build_default_registry()
    names = {t.name for t in reg.all()}
    expected = {
        "file_read",
        "file_write",
        "file_edit",
        "bash",
        "grep",
        "glob",
        "web_search",
        "todo",
    }
    assert expected <= names, f"missing original tools: {expected - names}"


def test_registry_has_at_least_29_tools() -> None:
    """Phase 1 expansion target: 8 original + 8 git + 4 file + 5 test + 2 web + 1 find + 1 dependency."""
    reg = build_default_registry()
    assert len(reg) >= 29, f"expected >= 29 tools, got {len(reg)}"


def test_registry_includes_git_tools() -> None:
    reg = build_default_registry()
    names = {t.name for t in reg.all()}
    git_tools = {
        "git_status",
        "git_diff",
        "git_commit",
        "git_push",
        "git_pull",
        "git_branch",
        "git_merge",
        "git_log",
    }
    assert git_tools <= names, f"missing git tools: {git_tools - names}"


def test_registry_includes_test_tools() -> None:
    reg = build_default_registry()
    names = {t.name for t in reg.all()}
    expected = {"test_run", "lint", "typecheck", "format", "coverage"}
    assert expected <= names, f"missing test/quality tools: {expected - names}"


def test_registry_includes_extended_file_tools() -> None:
    reg = build_default_registry()
    names = {t.name for t in reg.all()}
    expected = {"file_delete", "file_move", "file_copy", "file_list"}
    assert expected <= names, f"missing extended file tools: {expected - names}"


def test_registry_includes_extended_web_tools() -> None:
    reg = build_default_registry()
    names = {t.name for t in reg.all()}
    expected = {"web_fetch", "web_extract", "find", "dependency"}
    assert expected <= names, f"missing extended tools: {expected - names}"


def test_git_tools_require_confirmation() -> None:
    """All mutating git operations (commit/push/pull/branch/merge) require confirmation."""
    reg = build_default_registry()
    must_confirm = {"git_commit", "git_push", "git_pull", "git_branch", "git_merge"}
    for tool in reg.all():
        if tool.name in must_confirm:
            assert tool.requires_confirmation, f"{tool.name} should require confirmation"
    # Read-only git operations do NOT.
    read_only = {"git_status", "git_diff", "git_log"}
    for tool in reg.all():
        if tool.name in read_only:
            assert not tool.requires_confirmation, f"{tool.name} should not require confirmation"


def test_registry_schemas_openai_shape() -> None:
    reg = build_default_registry()
    schemas = reg.schemas()
    for s in schemas:
        assert {"name", "description", "input_schema"} <= s.keys()


def test_registry_rejects_duplicate() -> None:
    from ddw_code.tools.registry import Tool, ToolRegistry

    reg = ToolRegistry()
    reg.register(
        Tool(name="x", description="", input_schema={}, handler=lambda: "")
    )
    with pytest.raises(ValueError):
        reg.register(
            Tool(name="x", description="", input_schema={}, handler=lambda: "")
        )


def test_file_read_writes_and_reads(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("line1\nline2\nline3\n", encoding="utf-8")
    out = asyncio.run(file_read.file_read(str(p)))
    assert "line2" in out
    # With offset/limit.
    out = asyncio.run(file_read.file_read(str(p), offset=2, limit=1))
    assert "line2" in out
    assert "line3" not in out


def test_file_read_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        asyncio.run(file_read.file_read(str(tmp_path / "nope.txt")))


def test_file_read_forbidden(tmp_path: Path) -> None:
    # Even if the file doesn't exist, the path check fires first.
    with pytest.raises(PermissionError):
        asyncio.run(file_read.file_read(str(Path.home() / ".ssh" / "id_rsa")))


def test_file_read_dir_error(tmp_path: Path) -> None:
    with pytest.raises(IsADirectoryError):
        asyncio.run(file_read.file_read(str(tmp_path)))


def test_file_write_and_edit(tmp_path: Path) -> None:
    p = tmp_path / "b.txt"
    asyncio.run(file_write.file_write(str(p), "hello\n"))
    assert p.read_text() == "hello\n"
    asyncio.run(file_edit.file_edit(str(p), "hello", "hi", replace_all=False))
    assert p.read_text() == "hi\n"
    # Edit non-unique.
    p.write_text("a\na\n", encoding="utf-8")
    with pytest.raises(file_edit.EditError):
        asyncio.run(file_edit.file_edit(str(p), "a", "b"))


def test_file_edit_empty_old_string(tmp_path: Path) -> None:
    p = tmp_path / "c.txt"
    p.write_text("x")
    with pytest.raises(file_edit.EditError):
        asyncio.run(file_edit.file_edit(str(p), "", "y"))


def test_bash_runs_and_captures(tmp_path: Path) -> None:
    out = asyncio.run(bash.bash("echo abc", timeout=10))
    assert "abc" in out
    # Non-zero exit code.
    out = asyncio.run(bash.bash("false", timeout=5))
    assert "exit code" in out


def test_bash_dangerous_refused() -> None:
    with pytest.raises(bash.BashError):
        asyncio.run(bash.bash("rm -rf /", timeout=5))
    with pytest.raises(bash.BashError):
        asyncio.run(bash.bash("sudo apt install foo", timeout=5))
    with pytest.raises(bash.BashError):
        asyncio.run(bash.bash("git push --force", timeout=5))


def test_glob_finds_files(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("")
    (tmp_path / "y.txt").write_text("")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "z.py").write_text("")
    out = asyncio.run(glob.glob("**/*.py", str(tmp_path)))
    assert "x.py" in out
    assert "z.py" in out
    assert "y.txt" not in out


def test_glob_no_match(tmp_path: Path) -> None:
    out = asyncio.run(glob.glob("**/*.does_not_exist", str(tmp_path)))
    assert "no matches" in out


def test_grep_finds_pattern(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("hello\nworld\nhello again\n")
    out = asyncio.run(grep.grep("hello", str(tmp_path), include="*.py"))
    assert "a.py" in out
    assert "hello" in out


def test_grep_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("Hello\nworld\n")
    out = asyncio.run(grep.grep("hello", str(tmp_path), case_insensitive=True))
    assert "Hello" in out


def test_todo_add_update_remove_list() -> None:
    todo.reset()
    out = asyncio.run(todo.todo(action="add", content="write tests"))
    assert "added" in out
    out = asyncio.run(todo.todo(action="list"))
    assert "write tests" in out
    # Update.
    items = todo.get_state().items
    nid = items[0]["id"]
    out = asyncio.run(todo.todo(action="update", id=nid, status="done"))
    assert "updated" in out
    assert todo.get_state().items[0]["done"] is True
    # Remove.
    out = asyncio.run(todo.todo(action="remove", id=nid))
    assert "removed" in out
    assert todo.get_state().items == []


def test_todo_unknown_action() -> None:
    out = asyncio.run(todo.todo(action="bogus"))
    assert "unknown action" in out


def test_dispatcher_validates_required_field() -> None:
    reg = build_default_registry()
    perm = PermissionManager()
    perm.approve("file_write")
    disp = ToolDispatcher(reg, perm)
    # Missing required `content`.
    res = asyncio.run(disp.dispatch("file_write", {"path": "/tmp/x"}))
    assert res.is_error
    assert "content" in res.output


def test_dispatcher_unknown_tool() -> None:
    reg = build_default_registry()
    perm = PermissionManager()
    disp = ToolDispatcher(reg, perm)
    res = asyncio.run(disp.dispatch("does_not_exist", {}))
    assert res.is_error


def test_dispatcher_deny_policy() -> None:
    from ddw_code.security.permissions import Decision

    reg = build_default_registry()
    perm = PermissionManager()
    perm.set_policy("bash", Decision.DENY)
    perm.approve("bash")  # approval doesn't override deny
    disp = ToolDispatcher(reg, perm)
    res = asyncio.run(disp.dispatch("bash", {"command": "echo x"}))
    assert res.is_error
    assert "denied" in res.output


def test_dispatcher_string_arguments() -> None:
    reg = build_default_registry()
    perm = PermissionManager()
    perm.approve("bash")
    disp = ToolDispatcher(reg, perm)
    res = asyncio.run(disp.dispatch("bash", '{"command": "echo json-arg"}'))
    assert not res.is_error
    assert "json-arg" in res.output
