"""Git tools for the DDW Code CLI.

Eight built-in tools that wrap the most common `git` subcommands:

- `git_status`  : porcelain status + summary
- `git_diff`    : working-tree or staged diff
- `git_commit`  : stage + commit
- `git_push`    : push to remote
- `git_pull`    : pull from remote
- `git_branch`  : list/create/delete/checkout
- `git_merge`   : merge a branch
- `git_log`     : show recent commits

Each tool follows the same shape: an async function plus a `schema()`.
"""
from __future__ import annotations

from . import (
    branch as _branch,
    commit as _commit,
    diff as _diff,
    log as _log,
    merge as _merge,
    pull as _pull,
    push as _push,
    status as _status,
)
from ..registry import Tool, ToolRegistry

# Re-exports for convenience.
git_status = _status.git_status
git_diff = _diff.git_diff
git_commit = _commit.git_commit
git_push = _push.git_push
git_pull = _pull.git_pull
git_branch = _branch.git_branch
git_merge = _merge.git_merge
git_log = _log.git_log


def register(reg: ToolRegistry) -> None:
    """Register all git tools into `reg` with their default policies."""
    reg.register(
        Tool(
            name="git_status",
            description="Show porcelain git status with a short summary.",
            input_schema=_status.schema(),
            handler=_status.git_status,
            requires_confirmation=False,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="git_diff",
            description="Show working-tree or staged diff (optionally for a single path).",
            input_schema=_diff.schema(),
            handler=_diff.git_diff,
            requires_confirmation=False,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="git_commit",
            description="Stage optional files and commit with a message. Amend supported.",
            input_schema=_commit.schema(),
            handler=_commit.git_commit,
            requires_confirmation=True,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="git_push",
            description="Push to a remote. Refuses force pushes (blocked upstream).",
            input_schema=_push.schema(),
            handler=_push.git_push,
            requires_confirmation=True,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="git_pull",
            description="Pull from a remote. Optional --rebase.",
            input_schema=_pull.schema(),
            handler=_pull.git_pull,
            requires_confirmation=True,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="git_branch",
            description="List/create/delete/checkout branches.",
            input_schema=_branch.schema(),
            handler=_branch.git_branch,
            requires_confirmation=True,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="git_merge",
            description="Merge a branch into the current branch. No force pushes are issued.",
            input_schema=_merge.schema(),
            handler=_merge.git_merge,
            requires_confirmation=True,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="git_log",
            description="Show recent commits (oneline or full format).",
            input_schema=_log.schema(),
            handler=_log.git_log,
            requires_confirmation=False,
            compactable=True,
        )
    )


__all__ = [
    "register",
    "git_status",
    "git_diff",
    "git_commit",
    "git_push",
    "git_pull",
    "git_branch",
    "git_merge",
    "git_log",
]
