"""Hooks subsystem.

Three hook kinds: pre-tool, post-tool, lifecycle. See `manager.py` for the
dispatch contract.
"""
from __future__ import annotations

from .manager import HookManager, LifecycleHook, PostToolHook, PreToolHook

__all__ = [
    "HookManager",
    "PreToolHook",
    "PostToolHook",
    "LifecycleHook",
]
