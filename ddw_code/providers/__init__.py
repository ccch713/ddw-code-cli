"""Provider registry with factory pattern.

Usage::

    from ddw_code.providers import get_provider
    provider = get_provider("minimax", api_key="sk-...")
"""
from __future__ import annotations

from typing import Any

from .base import ModelProvider
from .deepseek import DeepSeekProvider
from .minimax import MiniMaxProvider
from .openai import OpenAIProvider

PROVIDERS: dict[str, type[ModelProvider]] = {
    "minimax": MiniMaxProvider,
    "deepseek": DeepSeekProvider,
    "openai": OpenAIProvider,
}


def get_provider(name: str, **kwargs: Any) -> ModelProvider:
    """Instantiate a provider by name.

    Raises ValueError if the provider name is unknown.
    """
    cls = PROVIDERS.get(name)
    if cls is None:
        available = ", ".join(sorted(PROVIDERS))
        raise ValueError(f"unknown provider {name!r} (available: {available})")
    return cls(**kwargs)


__all__ = ["get_provider", "PROVIDERS", "ModelProvider"]
