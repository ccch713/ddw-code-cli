"""`git_log` — show recent commits."""
from __future__ import annotations

from typing import Any

from ._helpers import GitError, _resolve_cwd, _run_git


async def git_log(
    limit: int = 10,
    oneline: bool = False,
    path: str | None = None,
) -> str:
    """Show the most recent `limit` commits.

    Args:
        limit: Number of commits to show (default 10).
        oneline: Use the condensed `--oneline` format.
        path: Optional working directory.

    Returns:
        Formatted log, or a friendly empty message if there are no commits.
    """
    if limit < 1:
        return "git_log error: limit must be >= 1"
    cwd = _resolve_cwd(path)
    args: list[str] = ["log", f"-n{int(limit)}", "--no-color"]
    if oneline:
        args.append("--oneline")
    else:
        args.extend(["--pretty=format:%h %an %ad %s", "--date=short"])
    try:
        rc, out, err = await _run_git(args, cwd=cwd)
    except GitError as e:
        return f"git_log error: {e}"
    if rc != 0:
        text = (err or out).strip()
        # A freshly-initialised repo is not an error from the agent's POV.
        if "does not have any commits yet" in text or "bad default revision" in text:
            return "[no commits]"
        return f"git_log failed: {text}"
    if not out.strip():
        return "[no commits]"
    return out


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Number of commits to show.",
                "default": 10,
                "minimum": 1,
            },
            "oneline": {
                "type": "boolean",
                "description": "Use condensed --oneline format.",
                "default": False,
            },
            "path": {
                "type": "string",
                "description": "Optional working directory.",
            },
        },
    }
