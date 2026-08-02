"""Skill registry: stores loaded skills and supports BM25 search over them."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .loader import Skill, load_skill, parse_skill


_TOKEN_RX = re.compile(r"[A-Za-z0-9_\-]{2,}")
_STOP = frozenset(
    """
    the a an and or of in to for on at by is are was were be been being
    this that these those it its from with as if but not have has had
    do does did will would can could should may might
    """.split()
)


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RX.findall(text or "") if t.lower() not in _STOP]


@dataclass
class ScoredSkill:
    """A skill paired with a relevance score."""

    skill: Skill
    score: float


class SkillRegistry:
    """In-memory skill store with BM25-style search."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._docs: list[list[str]] = []  # tokens per skill, parallel to dict values
        self._df: Counter[str] = Counter()
        self._avgdl: float = 0.0

    def register(self, skill: Skill) -> None:
        if skill.name in self._skills:
            raise ValueError(f"skill {skill.name!r} already registered")
        toks = _tokens(
            f"{skill.name} {skill.description} {' '.join(skill.triggers)} {skill.instructions}"
        )
        self._skills[skill.name] = skill
        self._docs.append(toks)
        for term in set(toks):
            self._df[term] += 1
        self._avgdl = sum(len(d) for d in self._docs) / max(1, len(self._docs))

    def unregister(self, name: str) -> None:
        if name not in self._skills:
            return
        del self._skills[name]
        # Rebuild the index — simpler than patching it.
        self._reindex()

    def _reindex(self) -> None:
        self._docs = []
        self._df = Counter()
        for skill in self._skills.values():
            toks = _tokens(
                f"{skill.name} {skill.description} "
                f"{' '.join(skill.triggers)} {skill.instructions}"
            )
            self._docs.append(toks)
            for term in set(toks):
                self._df[term] += 1
        self._avgdl = sum(len(d) for d in self._docs) / max(1, len(self._docs))

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills

    def search(self, query: str, top_k: int = 5) -> list[ScoredSkill]:
        """Return the top_k skills ranked by BM25 relevance to `query`."""
        q = _tokens(query)
        if not q or not self._docs:
            return []
        scores: list[tuple[int, float]] = []
        for i, doc in enumerate(self._docs):
            dl = len(doc) or 1
            s = 0.0
            for term in q:
                df = self._df.get(term, 0)
                if df == 0:
                    continue
                idf = math.log(1 + (len(self._docs) - df + 0.5) / (df + 0.5))
                tf = doc.count(term)
                num = tf * 1.5
                den = tf + 1.5 * (1 - 0.75 + 0.75 * dl / max(1e-9, self._avgdl))
                s += idf * num / den
            if s > 0:
                scores.append((i, s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return [
            ScoredSkill(skill=list(self._skills.values())[i], score=s)
            for i, s in scores[:top_k]
        ]

    def load_directory(self, directory: str | Path) -> int:
        """Load every `*.md` file in `directory` as a skill.

        Files that don't parse cleanly are silently skipped — the registry
        is for *agent* skills, not strict schemas.

        Returns:
            Number of skills successfully loaded.
        """
        d = Path(directory)
        if not d.exists() or not d.is_dir():
            return 0
        loaded = 0
        for path in sorted(d.glob("*.md")):
            try:
                skill = load_skill(path)
            except (OSError, UnicodeError):
                continue
            if not skill.name or skill.name in self._skills:
                continue
            try:
                self.register(skill)
                loaded += 1
            except ValueError:
                continue
        return loaded

    def load_text(self, name: str, text: str) -> Skill:
        """Register a skill directly from raw text (no file I/O).

        The `name` argument is the canonical name used in the registry.
        The skill's frontmatter `name` field (if any) is ignored — the
        registry's name is authoritative so callers don't have to
        remember to also update the Markdown.
        """
        skill = parse_skill(text, source=f"<inline:{name}>")
        skill.name = name
        self.register(skill)
        return skill


__all__ = ["SkillRegistry", "ScoredSkill"]
