"""`git_merge` — merge a branch into the current one (dangerous, requires confirmation)."""
from __future__ import annotations

from typing import Any

from ._helpers import GitError, _resolve_cwd, _run_git


async def git_merge(
    branch: str,
    no_ff: bool = False,
    path: str | None = None,
    message: str | None = None,
) -> str:
    """Merge `branch` into the current branch.

    Args:
        branch: Branch to merge in (required).
        no_ff: Force a merge commit even if fast-forward is possible.
        path: Optional working directory.
        message: Optional merge commit message (`-m`).

    Returns:
        git output on success, or an error message on failure.
    """
    if not branch or not branch.strip():
        return "git_merge error: 'branch' is required"
    cwd = _resolve_cwd(path)
    args: list[str] = ["merge"]
    if no_ff:
        args.append("--no-ff")
    if message:
        args.extend(["-m", message])
    args.append(branch)
    try:
        rc, out, err = await _run_git(args, cwd=cwd)
    except GitError as e:
        return f"git_merge error: {e}"
    if rc != 0:
        return f"git_merge failed: {(err or out).strip()}"
    return out.strip() or f"merged {branch} into current branch"


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "description": "Branch to merge in (required).",
            },
            "no_ff": {
                "type": "boolean",
                "description": "Force a merge commit (--no-ff).",
                "default": False,
            },
            "path": {
                "type": "string",
                "description": "Optional working directory.",
            },
            "message": {
                "type": "string",
                "description": "Optional merge commit message.",
            },
        },
        "required": ["branch"],
    }
