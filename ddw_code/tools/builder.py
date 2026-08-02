"""Build a `ToolRegistry` pre-loaded with all built-in tools.

Single entry point so the agent loop doesn't need to know which tool files
exist.
"""
from __future__ import annotations

from . import (
    bash,
    dependency,
    file_copy,
    file_delete,
    file_edit,
    file_list,
    file_move,
    file_read,
    file_write,
    find,
    glob,
    grep,
    test as _test,
    todo,
    web_extract,
    web_fetch,
    web_search,
)
from .agent import register as _register_agent
from .git import register as _register_git
from .registry import Tool, ToolRegistry


def build_default_registry() -> ToolRegistry:
    """Return a registry populated with every built-in tool.

    Tool count is now 29 (8 original + 8 git + 4 file + 5 test + 2 web + 1 find + 1 dependency).
    """
    reg = ToolRegistry()

    # ---- Original 8 tools ----
    reg.register(
        Tool(
            name="file_read",
            description=(
                "Read a file from the local filesystem. Supports offset/limit for "
                "large files."
            ),
            input_schema=file_read.schema(),
            handler=file_read.file_read,
            requires_confirmation=False,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="file_write",
            description="Write content to a file, creating parent directories as needed.",
            input_schema=file_write.schema(),
            handler=file_write.file_write,
            requires_confirmation=True,
            compactable=False,
        )
    )
    reg.register(
        Tool(
            name="file_edit",
            description=(
                "Replace an exact substring in a file. By default the substring must "
                "be unique; pass replace_all=True to replace every occurrence."
            ),
            input_schema=file_edit.schema(),
            handler=file_edit.file_edit,
            requires_confirmation=True,
            compactable=False,
        )
    )
    reg.register(
        Tool(
            name="bash",
            description=(
                "Execute a shell command. Output is captured. Has a per-call timeout. "
                "Dangerous commands (rm -rf, sudo, git push --force, etc.) are refused."
            ),
            input_schema=bash.schema(),
            handler=bash.bash,
            requires_confirmation=True,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="grep",
            description="Search file contents with a regex (ripgrep if available).",
            input_schema=grep.schema(),
            handler=grep.grep,
            requires_confirmation=False,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="glob",
            description="Find files by glob pattern.",
            input_schema=glob.schema(),
            handler=glob.glob,
            requires_confirmation=False,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="web_search",
            description="Search the web (DuckDuckGo HTML).",
            input_schema=web_search.schema(),
            handler=web_search.web_search,
            requires_confirmation=False,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="todo",
            description="Manage the session todo list (add/update/remove/list).",
            input_schema=todo.schema(),
            handler=todo.todo,
            requires_confirmation=False,
            compactable=False,
        )
    )

    # ---- File operations extension (4) ----
    reg.register(
        Tool(
            name="file_delete",
            description="Delete a file or directory (set recursive=True for rmtree).",
            input_schema=file_delete.schema(),
            handler=file_delete.file_delete,
            requires_confirmation=True,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="file_move",
            description="Move or rename a file/directory (overwrite=False by default).",
            input_schema=file_move.schema(),
            handler=file_move.file_move,
            requires_confirmation=True,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="file_copy",
            description="Copy a file to a new path, preserving metadata.",
            input_schema=file_copy.schema(),
            handler=file_copy.file_copy,
            requires_confirmation=False,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="file_list",
            description="List directory contents with optional recursive walk and pattern filter.",
            input_schema=file_list.schema(),
            handler=file_list.file_list,
            requires_confirmation=False,
            compactable=True,
        )
    )

    # ---- Web extension (2) ----
    reg.register(
        Tool(
            name="web_fetch",
            description="Fetch a URL and return its body as plain text (HTML stripped).",
            input_schema=web_fetch.schema(),
            handler=web_fetch.web_fetch,
            requires_confirmation=False,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="web_extract",
            description="Fetch a URL and return title/meta/selector matches.",
            input_schema=web_extract.schema(),
            handler=web_extract.web_extract,
            requires_confirmation=False,
            compactable=True,
        )
    )

    # ---- Search extension (1) ----
    reg.register(
        Tool(
            name="find",
            description="Find files/directories by name (substring or glob) with type filter.",
            input_schema=find.schema(),
            handler=find.find,
            requires_confirmation=False,
            compactable=True,
        )
    )

    # ---- Project extension (1) ----
    reg.register(
        Tool(
            name="dependency",
            description="List/add/remove Python dependencies in requirements.txt or pyproject.toml.",
            input_schema=dependency.schema(),
            handler=dependency.dependency,
            requires_confirmation=True,
            compactable=True,
        )
    )

    # ---- Git tools (8) ----
    _register_git(reg)

    # ---- Test/quality tools (5) ----
    _test.register(reg)

    # ---- Agent tools (5) ----
    _register_agent(reg)

    return reg


__all__ = ["build_default_registry", "Tool", "ToolRegistry"]
