"""Agent-oriented tools: actor, task, memory, plan_enter, plan_exit.

These wrap a process-local state layer (sub-agent runs, task tree) and
shared subsystems (BM25-backed memory, plan-mode permission toggle).
"""
from __future__ import annotations

from . import actor as _actor
from . import memory as _memory
from . import plan as _plan
from . import task as _task
from ..registry import Tool, ToolRegistry

actor = _actor.actor
task = _task.task
memory = _memory.memory
plan_enter = _plan.plan_enter
plan_exit = _plan.plan_exit


def register(reg: ToolRegistry) -> None:
    """Register all agent tools into `reg`."""
    reg.register(
        Tool(
            name="actor",
            description=(
                "Sub-agent delegation with 7 verbs: run/spawn/status/wait/"
                "cancel/send/models."
            ),
            input_schema=_actor.schema(),
            handler=_actor.actor,
            requires_confirmation=False,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="task",
            description=(
                "Task tree management: create/list/get/start/block/unblock/"
                "done/abandon/rename."
            ),
            input_schema=_task.schema(),
            handler=_task.task,
            requires_confirmation=False,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="memory",
            description=(
                "Session and long-term memory with BM25 search."
            ),
            input_schema=_memory.schema(),
            handler=_memory.memory,
            requires_confirmation=False,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="plan_enter",
            description="Enter read-only plan mode (mutating tools denied).",
            input_schema=_plan.schema_enter(),
            handler=_plan.plan_enter,
            requires_confirmation=False,
            compactable=True,
        )
    )
    reg.register(
        Tool(
            name="plan_exit",
            description="Exit plan mode and restore default permissions.",
            input_schema=_plan.schema_exit(),
            handler=_plan.plan_exit,
            requires_confirmation=False,
            compactable=True,
        )
    )


__all__ = [
    "register",
    "actor",
    "task",
    "memory",
    "plan_enter",
    "plan_exit",
]
