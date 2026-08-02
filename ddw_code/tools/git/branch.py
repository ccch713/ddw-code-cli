"""`git_branch` — list, create, delete, or check out branches."""
from __future__ import annotations

from typing import Any, Literal

from ._helpers import GitError, _resolve_cwd, _run_git

Action = Literal["list", "create", "delete", "checkout"]


async def git_branch(
    action: str = "list",
    name: str | None = None,
    path: str | None = None,
    force: bool = False,
) -> str:
    """Manage branches.

    Args:
        action: One of `list`, `create`, `delete`, `checkout`.
        name: Branch name (required for create/delete/checkout).
        path: Optional working directory.
        force: For `delete` use `-D` (force); for `create` overwrite an existing branch.

    Returns:
        git output on success, or a friendly error message.

    Raises:
        ValueError: Raised for unknown action. (Caught inside the tool and returned as text.)
    """
    cwd = _resolve_cwd(path)
    action = (action or "list").lower().strip()
    if action not in {"list", "create", "delete", "checkout"}:
        return f"git_branch error: unknown action {action!r} (expected list/create/delete/checkout)"
    if action in {"create", "delete", "checkout"} and not (name and name.strip()):
        return f"git_branch error: 'name' is required for action={action}"
    try:
        if action == "list":
            args: list[str] = ["branch", "--list", "-vv"]
            rc, out, err = await _run_git(args, cwd=cwd)
        elif action == "create":
            args = ["branch", name] if not force else ["branch", "-f", name]
            rc, out, err = await _run_git(args, cwd=cwd)
        elif action == "delete":
            flag = "-D" if force else "-d"
            args = ["branch", flag, name]
            rc, out, err = await _run_git(args, cwd=cwd)
        else:  # checkout
            rc, out, err = await _run_git(["checkout", name], cwd=cwd)
    except GitError as e:
        return f"git_branch error: {e}"
    if rc != 0:
        return f"git_branch {action} failed: {(err or out).strip()}"
    if action == "list":
        if not out.strip():
            return "[no branches]"
        return out
    return out.strip() or f"git_branch {action} succeeded"


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create", "delete", "checkout"],
                "description": "Operation to perform.",
                "default": "list",
            },
            "name": {
                "type": "string",
                "description": "Branch name (required for create/delete/checkout).",
            },
            "path": {
                "type": "string",
                "description": "Optional working directory.",
            },
            "force": {
                "type": "boolean",
                "description": "Force delete (use -D) or force overwrite on create.",
                "default": False,
            },
        },
    }
