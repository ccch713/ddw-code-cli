"""`actor` — sub-agent delegation tool (7 verbs).

Verbs:
- `run`     : execute a sub-agent synchronously and return its result
- `spawn`   : launch a sub-agent asynchronously; return its actor_id
- `status`  : look up a sub-agent's current status
- `wait`    : block until a sub-agent finishes
- `cancel`  : mark a sub-agent as cancelled
- `send`    : post a follow-up message to a sub-agent's prompt
- `models`  : list the model identifiers the local provider knows about

The sub-agent's actual execution is intentionally a thin stub here — the
real production wiring is a Hub feature. For local-mode use we just record
the request and return a deterministic placeholder.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from ._state import SubAgentRun, get_subagent_registry


_KNOWN_MODELS = (
    "minimax",
    "deepseek",
    "openai",
    "anthropic",
    "local",
)


async def _execute_locally(prompt: str) -> str:
    """Stub executor: in real deployments the Hub would do this work.

    The local stub pretends the sub-agent did the work and returns a short
    confirmation. Tests can monkeypatch this function to drive custom flows.
    """
    await asyncio.sleep(0)  # yield to the loop
    return f"[sub-agent] processed prompt ({len(prompt)} chars)"


async def actor(
    action: str,
    prompt: str | None = None,
    actor_id: str | None = None,
    message: str | None = None,
) -> str:
    """Dispatch one of the 7 actor verbs.

    Args:
        action: One of `run`, `spawn`, `status`, `wait`, `cancel`, `send`, `models`.
        prompt: Required for `run`/`spawn`. The task description.
        actor_id: Required for `status`/`wait`/`cancel`/`send`.
        message: Required for `send`. The follow-up message.

    Returns:
        A human-readable summary. Never raises — errors are returned as strings.
    """
    act = (action or "").lower().strip()
    reg = get_subagent_registry()

    if act == "models":
        return "models: " + ", ".join(_KNOWN_MODELS)

    if act == "run":
        if not prompt:
            return "actor error: 'prompt' is required for run"
        run = await reg.create(prompt)
        run.mark_running()
        try:
            result = await _execute_locally(prompt)
            run.mark_done(result)
            return f"actor run done: {result}"
        except Exception as e:  # pragma: no cover
            run.mark_failed(str(e))
            return f"actor run failed: {e}"

    if act == "spawn":
        if not prompt:
            return "actor error: 'prompt' is required for spawn"
        run = await reg.create(prompt)
        run.mark_running()

        async def _bg() -> None:
            try:
                result = await _execute_locally(prompt)
                run.mark_done(result)
            except Exception as e:  # pragma: no cover
                run.mark_failed(str(e))

        asyncio.create_task(_bg())
        return f"actor spawned: id={run.actor_id}"

    if act == "status":
        if not actor_id:
            return "actor error: 'actor_id' is required for status"
        run = await reg.get(actor_id)
        if run is None:
            return f"actor error: unknown actor_id {actor_id!r}"
        return (
            f"actor {run.actor_id} status={run.status} "
            f"started_at={run.started_at} finished_at={run.finished_at}"
        )

    if act == "wait":
        if not actor_id:
            return "actor error: 'actor_id' is required for wait"
        deadline = time.time() + 30.0
        while time.time() < deadline:
            run = await reg.get(actor_id)
            if run is None:
                return f"actor error: unknown actor_id {actor_id!r}"
            if run.status in {"done", "cancelled", "failed"}:
                body = run.result or run.error or ""
                return f"actor {actor_id} {run.status}: {body}"
            await asyncio.sleep(0.05)
        return f"actor wait timed out for {actor_id}"

    if act == "cancel":
        if not actor_id:
            return "actor error: 'actor_id' is required for cancel"
        run = await reg.get(actor_id)
        if run is None:
            return f"actor error: unknown actor_id {actor_id!r}"
        if run.status in {"done", "failed", "cancelled"}:
            return f"actor {actor_id} already {run.status}"
        run.mark_cancelled()
        return f"actor {actor_id} cancelled"

    if act == "send":
        if not actor_id:
            return "actor error: 'actor_id' is required for send"
        if not message:
            return "actor error: 'message' is required for send"
        run = await reg.get(actor_id)
        if run is None:
            return f"actor error: unknown actor_id {actor_id!r}"
        run.prompt = f"{run.prompt}\n[follow-up] {message}"
        return f"actor {actor_id} message queued"

    return (
        f"actor error: unknown action {action!r} "
        f"(expected run/spawn/status/wait/cancel/send/models)"
    )


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["run", "spawn", "status", "wait", "cancel", "send", "models"],
                "description": "Sub-agent verb to invoke.",
            },
            "prompt": {
                "type": "string",
                "description": "Task description (required for run/spawn).",
            },
            "actor_id": {
                "type": "string",
                "description": "Sub-agent identifier (required for status/wait/cancel/send).",
            },
            "message": {
                "type": "string",
                "description": "Follow-up message (required for send).",
            },
        },
        "required": ["action"],
    }


__all__ = ["actor", "schema", "_execute_locally"]
