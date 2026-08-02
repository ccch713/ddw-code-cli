"""`git_commit` — stage and commit changes."""
from __future__ import annotations

import shlex
from typing import Any

from ._helpers import GitError, _resolve_cwd, _run_git


async def git_commit(
    message: str,
    files: list[str] | None = None,
    path: str | None = None,
    amend: bool = False,
) -> str:
    """Stage optional `files` and commit with `message`.

    Args:
        message: Commit message.
        files: Optional list of paths to `git add` first. `None` commits whatever is already staged.
        path: Optional working directory.
        amend: If True, amend the previous commit instead of creating a new one.

    Returns:
        Confirmation with the new commit hash, or an error message.

    Raises:
        GitError: Not raised here; all errors are returned as strings so the agent can surface them.
    """
    if not message or not message.strip():
        return "git_commit error: commit message must not be empty"
    cwd = _resolve_cwd(path)
    try:
        if files:
            # Quote each path safely; reject empty entries.
            safe_files: list[str] = []
            for f in files:
                f = str(f).strip()
                if not f:
                    continue
                safe_files.extend(["--", f]) if False else safe_files.append(f)
            if not safe_files:
                return "git_commit error: no valid files to add"
            add_args = ["add", "--", *safe_files]
            rc, add_out, add_err = await _run_git(add_args, cwd=cwd)
            if rc != 0:
                return f"git_commit failed during `git add`: {add_err.strip() or add_out.strip()}"
        commit_args: list[str] = ["commit", "-m", message]
        if amend:
            commit_args.append("--amend")
        rc, out, err = await _run_git(commit_args, cwd=cwd)
    except GitError as e:
        return f"git_commit error: {e}"
    if rc != 0:
        text = (err or out).strip()
        return f"git_commit failed: {text}"
    return out.strip() or "commit succeeded (no output)"


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Commit message (required, non-empty).",
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of paths to `git add` before committing.",
            },
            "path": {
                "type": "string",
                "description": "Optional working directory.",
            },
            "amend": {
                "type": "boolean",
                "description": "Amend the previous commit instead of creating a new one.",
                "default": False,
            },
        },
        "required": ["message"],
    }


__all__ = ["git_commit", "schema", "shlex"]
