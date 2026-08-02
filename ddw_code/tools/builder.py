"""Build a `ToolRegistry` pre-loaded with all built-in tools.

Single entry point so the agent loop doesn't need to know which tool files
exist.
"""
from __future__ import annotations

from . import (
    bash,
    file_edit,
    file_read,
    file_write,
    glob,
    grep,
    todo,
    web_search,
)
from .registry import Tool, ToolRegistry


def build_default_registry() -> ToolRegistry:
    """Return a registry populated with the eight built-in tools."""
    reg = ToolRegistry()
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
    return reg


__all__ = ["build_default_registry", "Tool", "ToolRegistry"]
