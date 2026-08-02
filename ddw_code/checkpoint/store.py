"""`Checkpoint` — save / load / resume session state.

Persistence is JSON-on-disk under `~/.ddw-code/checkpoints/<session>.json`.
The schema is intentionally permissive (a free-form `state` dict) so any
caller can stash whatever they need.

A real production deployment would back this with the Hub's audit log
and a shadow git tree; for now a single JSON file per session is enough.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_BASE = Path(os.path.expanduser("~/.ddw-code/checkpoints"))


def _session_path(session_id: str) -> Path:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_.") or "default"
    return _BASE / f"{safe}.json"


@dataclass
class Checkpoint:
    """One saved snapshot of a session."""

    checkpoint_id: str
    session_id: str
    created_at: float
    state: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "checkpoint_id": self.checkpoint_id,
                "session_id": self.session_id,
                "created_at": self.created_at,
                "state": self.state,
            },
            ensure_ascii=False,
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> "Checkpoint":
        data = json.loads(text)
        return cls(
            checkpoint_id=str(data.get("checkpoint_id") or uuid.uuid4()),
            session_id=str(data.get("session_id") or "default"),
            created_at=float(data.get("created_at") or time.time()),
            state=data.get("state") or {},
        )


class CheckpointStore:
    """Per-session JSON file store for checkpoints."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base = base_dir or _BASE
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.base / f"{session_id}.json"

    def save(
        self,
        session_id: str,
        state: dict[str, Any],
        *,
        checkpoint_id: str | None = None,
    ) -> Checkpoint:
        """Persist a new checkpoint, replacing any prior one for the session.

        Args:
            session_id: Stable session identifier.
            state: Arbitrary JSON-serialisable state.
            checkpoint_id: Optional explicit id; generated if missing.

        Returns:
            The persisted `Checkpoint`.
        """
        cp = Checkpoint(
            checkpoint_id=checkpoint_id or str(uuid.uuid4()),
            session_id=session_id,
            created_at=time.time(),
            state=copy.deepcopy(state),
        )
        path = self._path(session_id)
        path.write_text(cp.to_json(), encoding="utf-8")
        return cp

    def load(self, session_id: str) -> Checkpoint | None:
        """Return the latest checkpoint for `session_id`, or None."""
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            return Checkpoint.from_json(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def resume(self, session_id: str) -> dict[str, Any] | None:
        """Convenience: load and return just the state dict."""
        cp = self.load(session_id)
        return cp.state if cp else None

    def list_sessions(self) -> list[str]:
        """Return all session ids that have a checkpoint on disk."""
        if not self.base.exists():
            return []
        return sorted(p.stem for p in self.base.glob("*.json"))

    def delete(self, session_id: str) -> bool:
        """Remove a session's checkpoint. Returns True if it existed."""
        path = self._path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False


# Module-level singleton for convenience.
_STORE = CheckpointStore()


def get_checkpoint_store() -> CheckpointStore:
    """Return the process-wide checkpoint store."""
    return _STORE


async def checkpoint_save(
    session_id: str,
    state: dict[str, Any] | None = None,
    checkpoint_id: str | None = None,
) -> str:
    """Async wrapper: save a checkpoint and return a confirmation string."""
    if not session_id:
        return "checkpoint error: 'session_id' is required"
    state = state or {}
    try:
        cp = _STORE.save(session_id, state, checkpoint_id=checkpoint_id)
    except (OSError, TypeError, ValueError) as e:
        return f"checkpoint save error: {e}"
    return f"checkpoint saved: id={cp.checkpoint_id} session={cp.session_id} ts={cp.created_at:.0f}"


async def checkpoint_load(session_id: str) -> str:
    """Async wrapper: load a checkpoint and return its state as text."""
    if not session_id:
        return "checkpoint error: 'session_id' is required"
    cp = _STORE.load(session_id)
    if cp is None:
        return f"checkpoint: no checkpoint for session {session_id!r}"
    body = json.dumps(cp.state, ensure_ascii=False, indent=2)
    return f"checkpoint loaded: id={cp.checkpoint_id} ts={cp.created_at:.0f}\n{body}"


async def checkpoint_resume(session_id: str) -> str:
    """Async wrapper: resume is just a load."""
    state = _STORE.resume(session_id)
    if state is None:
        return f"checkpoint resume: nothing to resume for {session_id!r}"
    return f"checkpoint resumed: keys={list(state.keys())}"


async def checkpoint_list() -> str:
    """Async wrapper: list known sessions."""
    sessions = _STORE.list_sessions()
    if not sessions:
        return "[no checkpoints]"
    return "checkpoints: " + ", ".join(sessions)


async def checkpoint_delete(session_id: str) -> str:
    """Async wrapper: delete a session's checkpoint."""
    if not session_id:
        return "checkpoint error: 'session_id' is required"
    if _STORE.delete(session_id):
        return f"checkpoint deleted: {session_id}"
    return f"checkpoint: no checkpoint for session {session_id!r}"


def schema_save() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Session identifier."},
            "state": {
                "type": "object",
                "description": "Arbitrary JSON-serialisable state to persist.",
            },
            "checkpoint_id": {
                "type": "string",
                "description": "Optional explicit checkpoint id.",
            },
        },
        "required": ["session_id"],
    }


def schema_session() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Session identifier."},
        },
        "required": ["session_id"],
    }


def schema_empty() -> dict[str, Any]:
    return {"type": "object", "properties": {}}


__all__ = [
    "Checkpoint",
    "CheckpointStore",
    "get_checkpoint_store",
    "checkpoint_save",
    "checkpoint_load",
    "checkpoint_resume",
    "checkpoint_list",
    "checkpoint_delete",
    "schema_save",
    "schema_session",
    "schema_empty",
]
