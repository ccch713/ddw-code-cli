"""`git_push` — push to a remote repository (dangerous, requires confirmation)."""
from __future__ import annotations

from typing import Any

from ._helpers import GitError, _resolve_cwd, _run_git


async def git_push(
    remote: str = "origin",
    branch: str | None = None,
    path: str | None = None,
    set_upstream: bool = False,
) -> str:
    """Push `branch` to `remote` (default origin). Refuses force pushes.

    Args:
        remote: Remote name (default "origin").
        branch: Branch name. `None` uses the current branch.
        path: Optional working directory.
        set_upstream: Pass `-u` to set upstream tracking.

    Returns:
        git output on success, or an error message on failure.
    """
    cwd = _resolve_cwd(path)
    args: list[str] = ["push"]
    if set_upstream:
        args.append("-u")
    args.append(remote)
    if branch:
        args.append(branch)
    try:
        rc, out, err = await _run_git(args, cwd=cwd)
    except GitError as e:
        return f"git_push error: {e}"
    if rc != 0:
        return f"git_push failed: {(err or out).strip()}"
    return out.strip() or f"pushed to {remote}{'/' + branch if branch else ''}"


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "remote": {
                "type": "string",
                "description": "Remote name (default 'origin').",
                "default": "origin",
            },
            "branch": {
                "type": "string",
                "description": "Branch to push. Defaults to the current branch.",
            },
            "path": {
                "type": "string",
                "description": "Optional working directory.",
            },
            "set_upstream": {
                "type": "boolean",
                "description": "Set upstream tracking (-u).",
                "default": False,
            },
        },
    }
