"""`SmartContext` — load only the files relevant to a user query.

Workflow:
1. Extract keywords from the query.
2. Search the workspace for files whose contents / names match.
3. Read up to `max_files` of the best hits and return them.

The implementation is intentionally small — we use the same `grep` and
`glob` primitives that the agent already has. For larger projects the
backend can be swapped for an LSP or a real indexer.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .detector import detect
from ..security.danger_check import is_forbidden_path


_TOKEN_RX = re.compile(r"[A-Za-z0-9_\-]{2,}")
_STOPWORDS = frozenset(
    """
    the a an and or of in to for on at by is are was were be been being
    this that these those it its from with as if but not have has had do
    does did will would can could should may might i you he she we they
    them me my our your their there here what which who whom whose
    """.split()
)


def _extract_keywords(query: str, top_k: int = 8) -> list[str]:
    """Pull the most informative tokens out of `query`."""
    tokens = [t.lower() for t in _TOKEN_RX.findall(query or "")]
    counter = Counter(t for t in tokens if t not in _STOPWORDS and not t.isdigit())
    return [w for w, _ in counter.most_common(top_k)]


@dataclass
class ContextHit:
    """One file considered relevant to the query."""

    path: str
    score: float
    preview: str = ""  # first few lines for the LLM to skim

    def format(self) -> str:
        body = self.preview.rstrip() or "(empty)"
        return f"=== {self.path} (score={self.score:.2f}) ===\n{body}"


@dataclass
class SmartContextResult:
    """Result of a `SmartContext.load` call."""

    query: str
    keywords: list[str]
    hits: list[ContextHit] = field(default_factory=list)

    def to_prompt(self) -> str:
        if not self.hits:
            return f"(no files matched query: {self.query!r})"
        parts = [
            f"# Relevant files for query: {self.query!r}",
            f"# Keywords: {', '.join(self.keywords) or '(none)'}",
            "",
        ]
        parts.extend(h.format() for h in self.hits)
        return "\n\n".join(parts)


class SmartContext:
    """Pick the most relevant files in a workspace for a given query."""

    def __init__(self, max_files: int = 5, preview_lines: int = 60) -> None:
        self.max_files = max(1, int(max_files))
        self.preview_lines = max(5, int(preview_lines))

    async def load(self, query: str, workspace: str) -> SmartContextResult:
        """Find and read the most relevant files for `query`.

        Args:
            query: The user's question / task.
            workspace: Project root.

        Returns:
            A `SmartContextResult` with up to `max_files` files.
        """
        ws = Path(workspace)
        if is_forbidden_path(ws):
            return SmartContextResult(query=query, keywords=[])
        if not ws.exists() or not ws.is_dir():
            return SmartContextResult(query=query, keywords=[])
        keywords = _extract_keywords(query)
        if not keywords:
            return SmartContextResult(query=query, keywords=[])
        # Get a list of candidate files (skip hidden and obvious junk dirs).
        candidates: list[Path] = []
        skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", "dist", "build"}
        for path in ws.rglob("*"):
            if not path.is_file():
                continue
            if any(part in skip_dirs for part in path.parts):
                continue
            if any(part.startswith(".") and part not in {".github"} for part in path.parts):
                continue
            candidates.append(path)
        # Score: filename match (×2) + content match.
        scored: list[tuple[float, Path]] = []
        keyword_set = set(keywords)
        for path in candidates:
            name_lower = path.name.lower()
            score = 0.0
            for kw in keyword_set:
                if kw in name_lower:
                    score += 2.0
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeError):
                continue
            text_lower = text.lower()
            for kw in keyword_set:
                # Count occurrences, capped, to avoid huge files dominating.
                score += min(text_lower.count(kw), 5) * 0.5
            if score > 0:
                scored.append((score, path))
        scored.sort(key=lambda x: x[0], reverse=True)
        hits: list[ContextHit] = []
        for score, path in scored[: self.max_files]:
            try:
                preview = "\n".join(
                    path.read_text(encoding="utf-8", errors="replace").splitlines()[
                        : self.preview_lines
                    ]
                )
            except (OSError, UnicodeError):
                preview = ""
            hits.append(ContextHit(path=str(path), score=score, preview=preview))
        return SmartContextResult(query=query, keywords=keywords, hits=hits)


__all__ = [
    "SmartContext",
    "SmartContextResult",
    "ContextHit",
    "_extract_keywords",
]
