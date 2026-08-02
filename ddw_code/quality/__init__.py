"""Quality assurance subsystem.

Exposes:

- `TestRunner` / `TestResult`     — pytest wrapper
- `LintRunner` / `LintResult`     — ruff wrapper
- `TypeChecker` / `TypeCheckResult`— mypy wrapper
- `QualityGate` / `QualityResult` — orchestrates the three
- `SelfHealer` / `HealResult`     — retry loop fed back to an LLM provider
"""
from __future__ import annotations

from .gate import QualityGate, QualityGateConfig, QualityResult
from .lint_runner import LintIssue, LintResult, LintRunner
from .self_healer import HealAttempt, HealResult, HealerProvider, SelfHealer
from .test_runner import TestResult, TestRunner
from .type_checker import TypeCheckResult, TypeChecker, TypeError

__all__ = [
    "QualityGate",
    "QualityGateConfig",
    "QualityResult",
    "LintIssue",
    "LintResult",
    "LintRunner",
    "HealAttempt",
    "HealResult",
    "HealerProvider",
    "SelfHealer",
    "TestResult",
    "TestRunner",
    "TypeCheckResult",
    "TypeChecker",
    "TypeError",
]
