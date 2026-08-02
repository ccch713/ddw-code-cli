"""`task` — task tree management.

Verbs:
- `create`  : add a new task
- `list`    : show every task
- `get`     : fetch a single task by id
- `start`   : mark in_progress (only if unblocked)
- `block`   : mark blocked
- `unblock` : mark pending again
- `done`    : mark done
- `abandon` : mark abandoned
- `rename`  : change the content text
"""
from __future__ import annotations

from typing import Any

from ._state import get_task_tree


def _fmt(node) -> str:
    deps = ",".join(node.blocked_by) if node.blocked_by else "-"
    return (
        f"[{node.id[:8]}] {node.status:<11} deps={deps} :: {node.content}"
    )


async def task(
    action: str,
    content: str | None = None,
    id: str | None = None,
    parent: str | None = None,
    blocked_by: list[str] | None = None,
) -> str:
    """Dispatch one of the task verbs.

    Args:
        action: One of `create`/`list`/`get`/`start`/`block`/`unblock`/`done`/`abandon`/`rename`.
        content: For `create`/`rename`. Task description (or new content).
        id: Task id (required for get/start/block/unblock/done/abandon/rename).
        parent: Optional parent task id (for `create`).
        blocked_by: Optional list of task ids this task depends on (for `create`).

    Returns:
        A human-readable summary.
    """
    act = (action or "").lower().strip()
    tree = get_task_tree()

    if act == "create":
        if not content:
            return "task error: 'content' is required for create"
        node = tree.create(content, parent_id=parent, blocked_by=blocked_by)
        return f"task created: {_fmt(node)}"

    if act == "list":
        nodes = tree.all()
        if not nodes:
            return "[no tasks]"
        return "\n".join(_fmt(n) for n in nodes)

    if act == "get":
        if not id:
            return "task error: 'id' is required for get"
        node = tree.get(id)
        if node is None:
            return f"task error: unknown id {id!r}"
        return _fmt(node)

    if act == "rename":
        if not id or not content:
            return "task error: 'id' and 'content' are required for rename"
        node = tree.rename(id, content)
        if node is None:
            return f"task error: unknown id {id!r}"
        return f"task renamed: {_fmt(node)}"

    for verb, attr in (
        ("start", "start"),
        ("block", "block"),
        ("unblock", "unblock"),
        ("done", "done"),
        ("abandon", "abandon"),
    ):
        if act == verb:
            if not id:
                return f"task error: 'id' is required for {verb}"
            node = getattr(tree, attr)(id)
            if node is None:
                if verb == "start":
                    # Could be unknown id OR still blocked.
                    existing = tree.resolve(id)
                    if existing is None:
                        return f"task error: unknown id {id!r}"
                    return (
                        f"task error: {id!r} is still blocked by "
                        f"{','.join(existing.blocked_by)}"
                    )
                return f"task error: unknown id {id!r}"
            return f"task {verb}: {_fmt(node)}"

    return (
        f"task error: unknown action {action!r} "
        f"(expected create/list/get/start/block/unblock/done/abandon/rename)"
    )


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "create",
                    "list",
                    "get",
                    "start",
                    "block",
                    "unblock",
                    "done",
                    "abandon",
                    "rename",
                ],
                "description": "Task verb to invoke.",
            },
            "content": {
                "type": "string",
                "description": "Task description or new content (for create/rename).",
            },
            "id": {
                "type": "string",
                "description": "Task id (required for get/start/block/unblock/done/abandon/rename).",
            },
            "parent": {
                "type": "string",
                "description": "Parent task id (optional, for create).",
            },
            "blocked_by": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Task ids this task depends on (optional, for create).",
            },
        },
        "required": ["action"],
    }


__all__ = ["task", "schema"]
