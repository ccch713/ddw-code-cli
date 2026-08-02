"""`git_diff` — show working tree or staged changes."""
from __future__ import annotations

from typing import Any

from ._helpers import GitError, _resolve_cwd, _run_git


async def git_diff(
    path: str | None = None,
    staged: bool = False,
    target: str | None = None,
) -> str:
    """Return the diff of the working tree (or staged area).

    Args:
        path: Optional path filter. Limits the diff to a file/directory.
        staged: If True, show the staged diff (`--staged`).
        target: Optional commit/branch to diff against (e.g. `main`, `HEAD~1`).

    Returns:
        Unified diff text, or a friendly empty message if there is no diff.
    """
    cwd = _resolve_cwd(path)
    args: list[str] = ["diff", "--no-color"]
    if staged:
        args.append("--staged")
    if target:
        args.append(target)
    if path:
        args.append("--")
        # If the path is a directory, append it as a pathspec.
        if cwd is not None and path and not path.startswith("-"):
            args.append(path)
    try:
        rc, out, err = await _run_git(args, cwd=cwd)
    except GitError as e:
        return f"git_diff error: {e}"
    if rc != 0:
        return f"git_diff failed: {err.strip() or out.strip()}"
    if not out.strip():
        label = "staged" if staged else "working tree"
        return f"[no {label} changes]"
    return out


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Optional path filter (file or directory).",
            },
            "staged": {
                "type": "boolean",
                "description": "Show staged changes (--staged) instead of working tree.",
                "default": False,
            },
            "target": {
                "type": "string",
                "description": "Optional commit/branch/ref to diff against.",
            },
        },
    }
