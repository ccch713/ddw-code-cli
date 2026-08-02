"""Detect project context: language, build system, and AGENTS.md / README.md.

Used to enrich the system prompt with project-specific guidance without
making the model guess.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# File markers used to identify a project language / build system.
_LANGUAGE_MARKERS: dict[str, tuple[str, ...]] = {
    "python": ("pyproject.toml", "setup.py", "requirements.txt", "Pipfile", "pyproject.toml"),
    "node": ("package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"),
    "go": ("go.mod", "go.sum"),
    "rust": ("Cargo.toml", "Cargo.lock"),
    "java": ("pom.xml", "build.gradle", "build.gradle.kts"),
    "ruby": ("Gemfile", "Gemfile.lock"),
}

# Context files we look for, in priority order.
_CONTEXT_FILES: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "README_ZH.md",
)


@dataclass(frozen=True)
class ProjectContext:
    """The detected shape of a project."""

    root: Path
    language: str | None
    context_files: list[Path]
    # A combined system-prompt-friendly snippet of the context files.
    context_excerpt: str

    def system_prompt_extras(self) -> str:
        """Return a short block to append to the system prompt."""
        parts: list[str] = []
        if self.language:
            parts.append(f"Detected project language: {self.language}.")
        if self.context_excerpt:
            parts.append(
                "Project guidance (loaded from AGENTS.md / CLAUDE.md / README.md):\n"
                + self.context_excerpt
            )
        return "\n\n".join(parts)


def detect(root: str | Path, *, max_excerpt_chars: int = 6000) -> ProjectContext:
    """Inspect `root` and return a `ProjectContext`.

    `max_excerpt_chars` caps the total length of loaded context files
    (truncated with a notice if exceeded).
    """
    root_path = Path(root).expanduser().resolve()
    language: str | None = None
    for lang, markers in _LANGUAGE_MARKERS.items():
        if any((root_path / m).exists() for m in markers):
            language = lang
            break

    context_files: list[Path] = []
    for name in _CONTEXT_FILES:
        candidate = root_path / name
        if candidate.is_file():
            context_files.append(candidate)

    excerpt_parts: list[str] = []
    used = 0
    for f in context_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        header = f"\n--- {f.name} ---\n"
        # Per-file cap to avoid one giant file dominating the prompt.
        per_file = min(len(text), 4000)
        block = header + text[:per_file]
        if used + len(block) > max_excerpt_chars:
            remaining = max_excerpt_chars - used
            if remaining <= len(header) + 20:
                break
            block = header + text[: max(0, remaining - len(header))]
            excerpt_parts.append(block)
            used += len(block)
            break
        excerpt_parts.append(block)
        used += len(block)
    if used >= max_excerpt_chars:
        excerpt_parts.append("\n... [context excerpt truncated]")

    return ProjectContext(
        root=root_path,
        language=language,
        context_files=context_files,
        context_excerpt="".join(excerpt_parts),
    )
