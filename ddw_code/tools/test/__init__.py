"""Test/quality tools: pytest, ruff, mypy, format, coverage.

Each tool is a thin wrapper over a CLI tool that is expected to be installed
on the developer's machine. They all return human-readable text rather than
structured objects so the agent's prompts stay simple.
"""
from __future__ import annotations

from . import (
    coverage as _coverage,
    format as _format,
    lint as _lint,
    runner as _runner,
    typecheck as _typecheck,
)
from ..registry import Tool, ToolRegistry

# Re-exports.
test_run = _runner.test_run
lint = _lint.lint
typecheck = _typecheck.typecheck
format_code = _format.format_code
coverage = _coverage.coverage


def register(reg: ToolRegistry) -> None:
    """Register all test/quality tools into `reg`."""
    reg.register(
        Tool(
            name="test_run",
            description="Run pytest against a path and return a structured summary.",
            input_schema=_runner.schema(),
            handler=_runner.test_run,
            requires_confirmation=True,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="lint",
            description="Run ruff check on a path; optionally auto-fix safe issues.",
            input_schema=_lint.schema(),
            handler=_lint.lint,
            requires_confirmation=False,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="typecheck",
            description="Run mypy on a path and report error counts.",
            input_schema=_typecheck.schema(),
            handler=_typecheck.typecheck,
            requires_confirmation=False,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="format",
            description="Format code with ruff format (check-only by default).",
            input_schema=_format.schema(),
            handler=_format.format_code,
            requires_confirmation=True,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="coverage",
            description="Run pytest with coverage and report the total percentage.",
            input_schema=_coverage.schema(),
            handler=_coverage.coverage,
            requires_confirmation=True,
            compactable=True,
        )
    )


__all__ = [
    "register",
    "test_run",
    "lint",
    "typecheck",
    "format_code",
    "coverage",
]
