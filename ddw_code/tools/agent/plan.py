"""`plan_enter` / `plan_exit` — toggle read-only "plan" mode.

Plan mode is enforced at the *permission* layer: when active, all mutating
tools (file_write, file_edit, file_delete, file_move, bash, git_commit,
git_push, git_pull, git_branch, git_merge, format, coverage, test_run,
dependency) are denied unless the user has explicitly approved them
*and* the `allow_in_plan` flag is set. This module exposes a tiny API
the rest of the codebase can read.

The tools themselves call `is_plan_mode_active()` to decide whether to
auto-deny a mutating action.
"""
from __future__ import annotations

import threading
from typing import Any


_LOCK = threading.RLock()
_ACTIVE: bool = False
_PLAN_ID: str | None = None


def is_plan_mode_active() -> bool:
    """Return True when plan mode is currently engaged."""
    with _LOCK:
        return _ACTIVE


def current_plan_id() -> str | None:
    """Return the id of the active plan, or None."""
    with _LOCK:
        return _PLAN_ID


def _enter(plan_id: str | None = None) -> tuple[bool, str | None]:
    with _LOCK:
        global _ACTIVE, _PLAN_ID  # noqa: PLW0603
        if _ACTIVE:
            return False, _PLAN_ID
        _ACTIVE = True
        _PLAN_ID = plan_id or "plan"
        return True, _PLAN_ID


def _exit() -> bool:
    with _LOCK:
        global _ACTIVE, _PLAN_ID  # noqa: PLW0603
        if not _ACTIVE:
            return False
        _ACTIVE = False
        _PLAN_ID = None
        return True


async def plan_enter(plan_id: str | None = None) -> str:
    """Enter plan mode. Mutating tools will be denied."""
    entered, used_id = _enter(plan_id)
    if entered:
        return f"plan mode entered: id={used_id}"
    return f"plan mode already active: id={used_id}"


async def plan_exit() -> str:
    """Exit plan mode and restore default permissions."""
    if _exit():
        return "plan mode exited"
    return "plan mode was not active"


def schema_enter() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "plan_id": {
                "type": "string",
                "description": "Optional id for this plan session.",
            },
        },
    }


def schema_exit() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {},
    }


__all__ = [
    "plan_enter",
    "plan_exit",
    "is_plan_mode_active",
    "current_plan_id",
    "schema_enter",
    "schema_exit",
]
