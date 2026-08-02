"""Shared in-process state for the agent tools.

`actor` and `task` need to track sub-agent runs and a task tree across
multiple tool invocations. This module is the single source of truth for
that state. It's deliberately process-local — multi-tenant / multi-user
state lives in the DDW AI Hub, not here.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SubAgentRun:
    """A tracked sub-agent invocation."""

    actor_id: str
    prompt: str
    status: str = "pending"  # pending | running | done | cancelled | failed
    result: str | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def mark_running(self) -> None:
        self.status = "running"

    def mark_done(self, result: str) -> None:
        self.status = "done"
        self.result = result
        self.finished_at = time.time()

    def mark_failed(self, error: str) -> None:
        self.status = "failed"
        self.error = error
        self.finished_at = time.time()

    def mark_cancelled(self) -> None:
        self.status = "cancelled"
        self.finished_at = time.time()


class SubAgentRegistry:
    """Process-local registry of sub-agent runs."""

    def __init__(self) -> None:
        self._runs: dict[str, SubAgentRun] = {}
        self._lock = asyncio.Lock()

    async def create(self, prompt: str) -> SubAgentRun:
        run = SubAgentRun(actor_id=str(uuid.uuid4()), prompt=prompt)
        async with self._lock:
            self._runs[run.actor_id] = run
        return run

    async def get(self, actor_id: str) -> SubAgentRun | None:
        async with self._lock:
            return self._runs.get(actor_id)

    async def all(self) -> list[SubAgentRun]:
        async with self._lock:
            return list(self._runs.values())

    async def update(self, run: SubAgentRun) -> None:
        async with self._lock:
            self._runs[run.actor_id] = run


# A single module-level registry shared by the tools.
_REGISTRY = SubAgentRegistry()


def get_subagent_registry() -> SubAgentRegistry:
    """Return the process-wide sub-agent registry."""
    return _REGISTRY


# -----------------------------------------------------------------------------
# Task tree
# -----------------------------------------------------------------------------


@dataclass
class TaskNode:
    """A node in the agent's task tree."""

    id: str
    content: str
    status: str = "pending"  # pending | in_progress | blocked | done | abandoned
    parent_id: str | None = None
    blocked_by: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()


class TaskTree:
    """An in-process tree of tasks with simple dependency tracking."""

    def __init__(self) -> None:
        self._nodes: dict[str, TaskNode] = {}

    def create(
        self,
        content: str,
        parent_id: str | None = None,
        blocked_by: list[str] | None = None,
    ) -> TaskNode:
        node = TaskNode(
            id=str(uuid.uuid4()),
            content=content,
            parent_id=parent_id,
            blocked_by=list(blocked_by or []),
        )
        self._nodes[node.id] = node
        return node

    def resolve(self, task_id: str) -> TaskNode | None:
        """Resolve `task_id`, accepting exact or unique-prefix matches.

        Full ids are always preferred. If `task_id` is shorter than a full
        id and matches exactly one node's prefix, that node is returned.
        Otherwise `None`.
        """
        if not task_id:
            return None
        node = self._nodes.get(task_id)
        if node is not None:
            return node
        matches = [n for n in self._nodes.values() if n.id.startswith(task_id)]
        if len(matches) == 1:
            return matches[0]
        return None

    def get(self, task_id: str) -> TaskNode | None:
        return self._nodes.get(task_id)

    def all(self) -> list[TaskNode]:
        return list(self._nodes.values())

    def rename(self, task_id: str, content: str) -> TaskNode | None:
        node = self.resolve(task_id)
        if node is None:
            return None
        node.content = content
        node.touch()
        return node

    def start(self, task_id: str) -> TaskNode | None:
        node = self.resolve(task_id)
        if node is None:
            return None
        if not self._unblocked(node):
            return None
        node.status = "in_progress"
        node.touch()
        return node

    def block(self, task_id: str) -> TaskNode | None:
        node = self.resolve(task_id)
        if node is None:
            return None
        node.status = "blocked"
        node.touch()
        return node

    def unblock(self, task_id: str) -> TaskNode | None:
        node = self.resolve(task_id)
        if node is None:
            return None
        node.status = "pending"
        node.touch()
        return node

    def done(self, task_id: str) -> TaskNode | None:
        node = self.resolve(task_id)
        if node is None:
            return None
        node.status = "done"
        node.touch()
        return node

    def abandon(self, task_id: str) -> TaskNode | None:
        node = self.resolve(task_id)
        if node is None:
            return None
        node.status = "abandoned"
        node.touch()
        return node

    def _unblocked(self, node: TaskNode) -> bool:
        for dep in node.blocked_by:
            dep_node = self.resolve(dep)
            if dep_node is None or dep_node.status != "done":
                return False
        return True


_TREE = TaskTree()


def get_task_tree() -> TaskTree:
    """Return the process-wide task tree."""
    return _TREE


__all__ = [
    "SubAgentRun",
    "SubAgentRegistry",
    "TaskNode",
    "TaskTree",
    "get_subagent_registry",
    "get_task_tree",
]
