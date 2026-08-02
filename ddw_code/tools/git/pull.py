"""`git_pull` — pull from a remote repository."""
from __future__ import annotations

from typing import Any

from ._helpers import GitError, _resolve_cwd, _run_git


async def git_pull(
    remote: str = "origin",
    branch: str | None = None,
    path: str | None = None,
    rebase: bool = False,
) -> str:
    """Fetch and integrate `remote/branch` into the current branch.

    Args:
        remote: Remote name (default "origin").
        branch: Branch name. `None` uses the upstream tracking branch.
        path: Optional working directory.
        rebase: Pass `--rebase` to rebase the current branch on top of the pulled commits.

    Returns:
        git output on success, or an error message on failure.
    """
    cwd = _resolve_cwd(path)
    args: list[str] = ["pull"]
    if rebase:
        args.append("--rebase")
    args.append(remote)
    if branch:
        args.append(branch)
    try:
        rc, out, err = await _run_git(args, cwd=cwd)
    except GitError as e:
        return f"git_pull error: {e}"
    if rc != 0:
        return f"git_pull failed: {(err or out).strip()}"
    return out.strip() or f"pulled from {remote}{'/' + branch if branch else ''}"


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
                "description": "Branch to pull. Defaults to upstream tracking branch.",
            },
            "path": {
                "type": "string",
                "description": "Optional working directory.",
            },
            "rebase": {
                "type": "boolean",
                "description": "Rebase instead of merge (--rebase).",
                "default": False,
            },
        },
    }
