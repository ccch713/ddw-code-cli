"""Configuration management for minimax-agent.

Loads settings from environment variables and CLI flags, with sensible defaults.
The Token Plan key (`sk-cp-...`) is required and never logged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Default API endpoint (OpenAI-compatible, used by MiniMax Token Plan).
DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_MODEL = "MiniMax-Text-01"
DEFAULT_MAX_TURNS = 15
# 60% threshold for triggering micro-compact (matches MaxCode).
MICRO_COMPACT_THRESHOLD = 0.60
# Keep the last 5 tool results verbatim; older ones become placeholders.
MICRO_COMPACT_KEEP_RECENT = 5

# Tools whose results are eligible for micro-compaction.
COMPACTABLE_TOOLS: frozenset[str] = frozenset(
    {"file_read", "bash", "grep", "glob", "web_search"}
)

# Path safety: never let tools read these.
FORBIDDEN_PATH_PREFIXES: tuple[str, ...] = (
    str(Path.home() / ".ssh"),
    str(Path.home() / ".gnupg"),
    str(Path.home() / ".aws" / "credentials"),
    str(Path.home() / ".config" / "git"),
    "/etc/shadow",
    "/etc/passwd",
    "/etc/sudoers",
)


@dataclass(frozen=True)
class Config:
    """Runtime configuration. Immutable once constructed."""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    max_turns: int = DEFAULT_MAX_TURNS
    workspace: Path = field(default_factory=Path.cwd)
    sandbox: bool = False
    print_mode: bool = False
    # Context window size in tokens. 200k is a safe default for modern
    # long-context models; the provider may override.
    context_window: int = 200_000
    # Per-call timeout in seconds for the LLM request.
    request_timeout: float = 120.0

    def is_token_plan_key(self) -> bool:
        """Return True if the API key is a Token Plan key (`sk-cp-...`)."""
        return self.api_key.startswith("sk-cp-")


def load_config(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    workspace: Path | None = None,
    sandbox: bool = False,
    print_mode: bool = False,
) -> Config:
    """Build a Config from explicit args, falling back to env vars and defaults.

    Lookup order: explicit arg > env var > default.
    Required: `api_key` (or `MINIMAX_API_KEY` env var, or `MINIMAX_TOKEN`).
    """
    key = (
        api_key
        or os.environ.get("MINIMAX_API_KEY")
        or os.environ.get("MINIMAX_TOKEN")
    )
    if not key:
        raise ValueError(
            "Missing API key. Pass --api-key or set MINIMAX_API_KEY (or MINIMAX_TOKEN) env var."
        )

    return Config(
        api_key=key,
        base_url=base_url or os.environ.get("MINIMAX_BASE_URL", DEFAULT_BASE_URL),
        model=model or os.environ.get("MINIMAX_MODEL", DEFAULT_MODEL),
        max_turns=max_turns or int(os.environ.get("MINIMAX_MAX_TURNS", str(DEFAULT_MAX_TURNS))),
        workspace=(workspace or Path.cwd()).resolve(),
        sandbox=sandbox,
        print_mode=print_mode,
    )
