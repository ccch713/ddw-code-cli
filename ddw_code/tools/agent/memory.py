"""`memory` — session + long-term memory with BM25 search.

Two scopes are supported:

- `session` : process-local memory that resets when the agent restarts
- `long`    : persisted to `~/.ddw-code/memory.jsonl` so it survives restarts

A tiny BM25 implementation provides ranked search across stored entries.
For real workloads, swap it for `rank_bm25`; the interface here is the
same so the swap is a one-line change.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

_MEMORY_DIR = Path(os.path.expanduser("~/.ddw-code"))
_MEMORY_FILE = _MEMORY_DIR / "memory.jsonl"

_session: list[dict[str, Any]] = []


# -----------------------------------------------------------------------------
# Tokenisation
# -----------------------------------------------------------------------------


_TOKEN_RX = re.compile(r"[A-Za-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RX.findall(text or "")]


# -----------------------------------------------------------------------------
# BM25
# -----------------------------------------------------------------------------


@dataclass
class _BM25Index:
    """Minimal BM25 Okapi index over a fixed document set."""

    k1: float = 1.5
    b: float = 0.75

    def __post_init__(self) -> None:
        self._docs: list[list[str]] = []
        self._df: Counter[str] = Counter()
        self._avgdl: float = 0.0

    def add(self, tokens: list[str]) -> None:
        self._docs.append(tokens)
        for term in set(tokens):
            self._df[term] += 1
        self._avgdl = sum(len(d) for d in self._docs) / max(1, len(self._docs))

    def score(self, query_tokens: list[str], doc_index: int) -> float:
        doc = self._docs[doc_index]
        dl = len(doc) or 1
        s = 0.0
        for term in query_tokens:
            df = self._df.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1 + (len(self._docs) - df + 0.5) / (df + 0.5))
            tf = doc.count(term)
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * dl / max(1e-9, self._avgdl))
            s += idf * numerator / denominator
        return s

    def search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        qt = _tokenize(query)
        if not qt or not self._docs:
            return []
        scores = [
            (i, self.score(qt, i))
            for i in range(len(self._docs))
        ]
        scores.sort(key=lambda x: x[1], reverse=True)
        return [(i, s) for i, s in scores[:top_k] if s > 0]


# -----------------------------------------------------------------------------
# Storage
# -----------------------------------------------------------------------------


def _ensure_memory_file() -> None:
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    if not _MEMORY_FILE.exists():
        _MEMORY_FILE.touch()


def _read_long() -> list[dict[str, Any]]:
    _ensure_memory_file()
    out: list[dict[str, Any]] = []
    with _MEMORY_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _append_long(entry: dict[str, Any]) -> None:
    _ensure_memory_file()
    with _MEMORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _delete_long(entry_id: str) -> int:
    entries = _read_long()
    kept = [e for e in entries if e.get("id") != entry_id]
    removed = len(entries) - len(kept)
    if removed:
        with _MEMORY_FILE.open("w", encoding="utf-8") as f:
            for e in kept:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return removed


# -----------------------------------------------------------------------------
# Public tool
# -----------------------------------------------------------------------------


async def memory(
    action: str,
    content: str | None = None,
    id: str | None = None,
    scope: str = "all",
    query: str | None = None,
    top_k: int = 5,
) -> str:
    """Read / write / search / delete memory entries.

    Args:
        action: One of `read`/`write`/`search`/`delete`.
        content: Body text (required for `write`).
        id: Entry id (required for `delete`).
        scope: `session` (in-memory), `long` (persisted), or `all` (search both).
        query: Search query (required for `search`).
        top_k: How many results to return for search.

    Returns:
        A human-readable summary.
    """
    global _session  # type: ignore[global-without-binding]  # noqa: PLW0603
    act = (action or "").lower().strip()
    if act not in {"read", "write", "search", "delete"}:
        return (
            f"memory error: unknown action {action!r} "
            f"(expected read/write/search/delete)"
        )
    if scope not in {"session", "long", "all"}:
        return f"memory error: invalid scope {scope!r}"

    if act == "write":
        if not content:
            return "memory error: 'content' is required for write"
        entry = {
            "id": str(uuid.uuid4()),
            "content": content,
            "created_at": time.time(),
        }
        if scope in {"session", "all"}:
            _session.append(entry)
        if scope in {"long", "all"}:
            _append_long(entry)
        return f"memory written: id={entry['id']} scope={scope}"

    if act == "delete":
        if not id:
            return "memory error: 'id' is required for delete"
        removed_session = 0
        if scope in {"session", "all"}:
            new_session = [e for e in _session if e.get("id") != id]
            removed_session = len(_session) - len(new_session)
            _session = new_session
        removed_long = 0
        if scope in {"long", "all"}:
            removed_long = _delete_long(id)
        if removed_session == 0 and removed_long == 0:
            return f"memory: id {id!r} not found"
        return f"memory: deleted id={id} (session={removed_session}, long={removed_long})"

    if act == "read":
        scopes: list[list[dict[str, Any]]] = []
        labels: list[str] = []
        if scope in {"session", "all"} and _session:
            scopes.append(_session)
            labels.append("session")
        if scope in {"long", "all"}:
            long_entries = _read_long()
            if long_entries:
                scopes.append(long_entries)
                labels.append("long")
        if not scopes:
            return "[no memory entries]"
        out: list[str] = []
        for label, entries in zip(labels, scopes):
            out.append(f"--- {label} ({len(entries)}) ---")
            for e in entries[-20:]:
                out.append(f"[{e['id'][:8]}] {e['content'][:120]}")
        return "\n".join(out)

    # act == "search"
    if not query:
        return "memory error: 'query' is required for search"
    sources: list[tuple[str, list[dict[str, Any]]]] = []
    if scope in {"session", "all"}:
        sources.append(("session", _session))
    if scope in {"long", "all"}:
        sources.append(("long", _read_long()))
    if not any(entries for _, entries in sources):
        return "memory search: no entries to search"
    results: list[tuple[float, str, dict[str, Any]]] = []
    for label, entries in sources:
        if not entries:
            continue
        idx = _BM25Index()
        for e in entries:
            idx.add(_tokenize(e.get("content", "")))
        scored = idx.search(query, top_k=top_k)
        for i, score in scored:
            results.append((score, label, entries[i]))
    if not results:
        return f"memory search: no matches for {query!r}"
    results.sort(key=lambda r: r[0], reverse=True)
    out = [f"memory search ({len(results)} hits)"]
    for score, label, entry in results[:top_k]:
        out.append(f"  [{score:.2f} {label}:{entry['id'][:8]}] {entry['content'][:160]}")
    return "\n".join(out)


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "write", "search", "delete"],
                "description": "Memory verb to invoke.",
            },
            "content": {
                "type": "string",
                "description": "Memory entry text (required for write).",
            },
            "id": {
                "type": "string",
                "description": "Memory entry id (required for delete).",
            },
            "scope": {
                "type": "string",
                "enum": ["session", "long", "all"],
                "description": "Which memory tier to operate on.",
                "default": "all",
            },
            "query": {
                "type": "string",
                "description": "BM25 search query (required for search).",
            },
            "top_k": {
                "type": "integer",
                "description": "How many search results to return.",
                "default": 5,
                "minimum": 1,
            },
        },
        "required": ["action"],
    }


__all__ = ["memory", "schema", "_BM25Index", "_tokenize"]
