"""`git_status` — show the working tree status in porcelain format."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ._helpers import GitError, _resolve_cwd, _run_git


async def git_status(path: str | None = None) -> str:
    """Return `git status --porcelain` output for `path` (default: cwd).

    Args:
        path: Optional directory to inspect. `None` means current working directory.

    Returns:
        Porcelain-formatted status, plus a human-readable summary line.

    Raises:
        GitError: If git is unavailable or the command fails (e.g. not a repo).
    """
    cwd = _resolve_cwd(path)
    try:
        rc, out, err = await _run_git(["status", "--porcelain"], cwd=cwd)
    except GitError as e:
        return f"git_status error: {e}"
    if rc != 0:
        return f"git_status failed: {err.strip() or out.strip()}"
    if not out.strip():
        return f"clean working tree at {cwd or Path.cwd()}"
    lines = out.splitlines()
    summary = {
        "modified": 0,
        "staged": 0,
        "untracked": 0,
        "deleted": 0,
        "renamed": 0,
    }
    for line in lines:
        x = line[:1]  # staged
        y = line[1:2]  # working tree
        if x != " " and x != "?":
            summary["staged"] += 1
        if y == "M":
            summary["modified"] += 1
        elif y == "D":
            summary["deleted"] += 1
        elif y == "?":
            summary["untracked"] += 1
        if x == "R":
            summary["renamed"] += 1
    header = (
        f"status: {len(lines)} entries "
        f"(staged={summary['staged']}, modified={summary['modified']}, "
        f"untracked={summary['untracked']}, deleted={summary['deleted']})"
    )
    return header + "\n" + out


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory to inspect (default: current working directory).",
            },
        },
    }
