"""DDW AI Hub plugin: lifecycle and dispatch.

When the CLI runs as a Hub plugin it receives task envelopes from the
Hub, executes them, and reports results back. This module is a
self-contained, in-process implementation that captures the *shape* of
the integration; the real Hub wiring is a thin adapter over this.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from ..providers.base import ModelProvider


# -----------------------------------------------------------------------------
# Task envelope
# -----------------------------------------------------------------------------


@dataclass
class PluginTask:
    """A task envelope received from the Hub."""

    task_id: str
    action: str  # 'chat' | 'tool' | 'status' | 'shutdown'
    payload: dict[str, Any] = field(default_factory=dict)
    tenant_id: str = "default"
    user_id: str = "default"
    received_at: float = field(default_factory=time.time)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginTask":
        return cls(
            task_id=str(data.get("task_id") or uuid.uuid4()),
            action=str(data.get("action") or "chat"),
            payload=dict(data.get("payload") or {}),
            tenant_id=str(data.get("tenant_id") or "default"),
            user_id=str(data.get("user_id") or "default"),
        )


@dataclass
class PluginResult:
    """The result of executing a PluginTask."""

    task_id: str
    ok: bool
    output: Any = None
    error: str | None = None
    duration_s: float = 0.0
    finished_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "duration_s": self.duration_s,
            "finished_at": self.finished_at,
        }


# -----------------------------------------------------------------------------
# Plugin
# -----------------------------------------------------------------------------


class TaskHandler(Protocol):
    """Anything that can execute a task envelope."""

    async def handle(self, task: PluginTask) -> Any:  # pragma: no cover - structural
        ...


class DDWPlugin:
    """Hub-side adapter: receives tasks, dispatches to a handler, reports back."""

    def __init__(
        self,
        name: str,
        version: str,
        handler: TaskHandler,
        provider: ModelProvider | None = None,
        report_sink: Callable[[PluginResult], Awaitable[None]] | None = None,
    ) -> None:
        self.name = name
        self.version = version
        self.handler = handler
        self.provider = provider
        self._report_sink = report_sink
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    def manifest(self) -> dict[str, Any]:
        """Return the plugin's manifest for the Hub to discover."""
        return {
            "name": self.name,
            "version": self.version,
            "kind": "ddw-code-cli",
            "capabilities": ["chat", "tool", "status"],
        }

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def execute(self, task: PluginTask | dict[str, Any]) -> PluginResult:
        """Run a single task and (if a sink is configured) report the result."""
        if isinstance(task, dict):
            task = PluginTask.from_dict(task)
        start = time.time()
        try:
            output = await self.handler.handle(task)
            result = PluginResult(
                task_id=task.task_id,
                ok=True,
                output=output,
                duration_s=time.time() - start,
            )
        except Exception as e:
            result = PluginResult(
                task_id=task.task_id,
                ok=False,
                error=str(e),
                duration_s=time.time() - start,
            )
        if self._report_sink is not None:
            try:
                await self._report_sink(result)
            except Exception:
                # Reporting failures must not mask the original outcome.
                pass
        return result


__all__ = [
    "DDWPlugin",
    "PluginTask",
    "PluginResult",
    "TaskHandler",
]
