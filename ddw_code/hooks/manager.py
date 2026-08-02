"""Hook manager.

Three hook kinds are supported:

- `pre_tool(name, args)`    : runs before a tool is dispatched. Returning
                              `False` blocks the call; anything else lets it
                              through.
- `post_tool(name, args, result)` : runs after a tool returns. May mutate
                                    the result (must return the new value)
                                    or simply observe.
- `lifecycle(event, payload)` : session-level events — `start`, `end`,
                               `turn_start`, `turn_end`, etc.

Hooks are registered as plain async callables; no decorator is required.
The manager dispatches them sequentially in registration order. If a
pre-tool hook returns `False`, the call is blocked and no further hooks
run.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any, Callable

# Hook callable types
PreToolHook = Callable[[str, dict[str, Any]], Awaitable[bool | None]]
PostToolHook = Callable[[str, dict[str, Any], Any], Awaitable[Any]]
LifecycleHook = Callable[[str, dict[str, Any]], Awaitable[None]]


class HookManager:
    """Sequential async hook dispatcher."""

    def __init__(self) -> None:
        self._pre: list[PreToolHook] = []
        self._post: list[PostToolHook] = []
        self._lifecycle: list[LifecycleHook] = []

    # ---- registration -----------------------------------------------------

    def register_pre_tool(self, hook: PreToolHook) -> None:
        self._pre.append(hook)

    def register_post_tool(self, hook: PostToolHook) -> None:
        self._post.append(hook)

    def register_lifecycle(self, hook: LifecycleHook) -> None:
        self._lifecycle.append(hook)

    def clear(self) -> None:
        """Remove every registered hook. Useful in tests."""
        self._pre.clear()
        self._post.clear()
        self._lifecycle.clear()

    # ---- introspection ---------------------------------------------------

    @property
    def pre_count(self) -> int:
        return len(self._pre)

    @property
    def post_count(self) -> int:
        return len(self._post)

    @property
    def lifecycle_count(self) -> int:
        return len(self._lifecycle)

    # ---- dispatch --------------------------------------------------------

    async def trigger_pre_tool(self, tool_name: str, args: dict[str, Any]) -> bool:
        """Run every pre-tool hook. Returns False if any hook vetoed the call."""
        for hook in list(self._pre):
            try:
                result = await hook(tool_name, args)
            except Exception:
                # A buggy hook should never crash the agent — skip it.
                continue
            if result is False:
                return False
        return True

    async def trigger_post_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: Any,
    ) -> Any:
        """Run every post-tool hook, threading the (possibly-mutated) result through.

        A post-tool hook may return a new value, which becomes the input to
        the next hook (and the final return value).
        """
        current = result
        for hook in list(self._post):
            try:
                current = await hook(tool_name, args, current)
            except Exception:
                continue
        return current

    async def trigger_lifecycle(self, event: str, payload: dict[str, Any] | None = None) -> None:
        """Fan out a session-level event to every lifecycle hook."""
        payload = payload or {}
        for hook in list(self._lifecycle):
            try:
                await hook(event, payload)
            except Exception:
                continue


__all__ = [
    "HookManager",
    "PreToolHook",
    "PostToolHook",
    "LifecycleHook",
]
