"""`todo` — manage a session task list.

State is in-memory and lives for the duration of the agent loop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TodoState:
    """In-memory list of tasks. Shared by reference across calls."""

    items: list[dict[str, Any]] = field(default_factory=list)

    def as_lines(self) -> str:
        if not self.items:
            return "[todo list is empty]"
        return "\n".join(
            f"[{'x' if i.get('done') else ' '}] {i['id']}. {i['content']} ({i['status']})"
            for i in self.items
        )


# Module-level singleton — survives within a single CLI run.
_state = TodoState()


async def todo(action: str, **kwargs: Any) -> str:
    """Operate on the session todo list.

    Actions:
        - add: add a task, requires `content` (and optional `status`).
        - update: change a task, requires `id` and one of `status` / `content`.
        - remove: remove a task, requires `id`.
        - list: list all tasks.

    Returns:
        A short status message.
    """
    global _state
    action = action.strip().lower()
    if action == "add":
        content = kwargs.get("content")
        if not content:
            return "error: 'add' requires a 'content' field"
        nid = max((i["id"] for i in _state.items), default=0) + 1
        _state.items.append(
            {
                "id": nid,
                "content": str(content),
                "status": kwargs.get("status", "pending"),
                "done": False,
            }
        )
        return f"added todo #{nid}: {content}"
    if action == "update":
        nid = int(kwargs.get("id", 0))
        for i in _state.items:
            if i["id"] == nid:
                if "content" in kwargs:
                    i["content"] = str(kwargs["content"])
                if "status" in kwargs:
                    i["status"] = str(kwargs["status"])
                    i["done"] = i["status"] in {"done", "completed"}
                return f"updated todo #{nid}"
        return f"error: no todo with id {nid}"
    if action == "remove":
        nid = int(kwargs.get("id", 0))
        before = len(_state.items)
        _state.items = [i for i in _state.items if i["id"] != nid]
        if len(_state.items) < before:
            return f"removed todo #{nid}"
        return f"error: no todo with id {nid}"
    if action == "list":
        return _state.as_lines()
    return f"error: unknown action {action!r} (use add/update/remove/list)"


def reset() -> None:
    """Clear the in-memory todo state (useful for tests)."""
    global _state
    _state = TodoState()


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "update", "remove", "list"],
                "description": "Todo operation to perform.",
            },
            "id": {"type": "integer", "description": "Task id (for update/remove)."},
            "content": {"type": "string", "description": "Task text (for add/update)."},
            "status": {
                "type": "string",
                "description": "Task status (for add/update).",
            },
        },
        "required": ["action"],
    }


# Expose the state object for tests.
def get_state() -> TodoState:
    return _state
