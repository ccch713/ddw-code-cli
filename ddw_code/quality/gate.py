"""`QualityGate` — orchestrates the test/lint/typecheck runners.

A gate is configured with a set of enabled checks. Calling `check()` runs
them in parallel and returns a combined `QualityResult`.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from .lint_runner import LintResult, LintRunner
from .test_runner import TestResult, TestRunner
from .type_checker import TypeCheckResult, TypeChecker


@dataclass(frozen=True)
class QualityResult:
    """Combined result of all enabled checks."""

    test: TestResult | None = None
    lint: LintResult | None = None
    typecheck: TypeCheckResult | None = None

    @property
    def passed(self) -> bool:
        """True iff every enabled check passed."""
        if self.test is not None and not self.test.passed_ok:
            return False
        if self.lint is not None and not self.lint.passed_ok:
            return False
        if self.typecheck is not None and not self.typecheck.passed_ok:
            return False
        return True

    def errors(self) -> list[str]:
        """Return a flat list of human-readable error messages."""
        out: list[str] = []
        if self.test is not None and not self.test.passed_ok:
            out.append(self.test.summary())
        if self.lint is not None and not self.lint.passed_ok:
            out.append(self.lint.summary())
            for issue in self.lint.issues[:20]:
                out.append("  " + issue.format())
        if self.typecheck is not None and not self.typecheck.passed_ok:
            out.append(self.typecheck.summary())
            for err in self.typecheck.errors[:20]:
                out.append("  " + err.format())
        return out

    def summary(self) -> str:
        parts: list[str] = []
        if self.test is not None:
            parts.append(self.test.summary())
        if self.lint is not None:
            parts.append(self.lint.summary())
        if self.typecheck is not None:
            parts.append(self.typecheck.summary())
        verdict = "PASS" if self.passed else "FAIL"
        return f"[quality gate] {verdict}\n" + "\n".join(parts)


@dataclass
class QualityGateConfig:
    """Toggle which checks the gate runs."""

    run_tests: bool = True
    run_lint: bool = True
    run_typecheck: bool = True
    test_timeout: int = 300
    lint_timeout: int = 120
    typecheck_timeout: int = 180
    test_pythonpath: str | None = None  # extra PYTHONPATH for the test runner


class QualityGate:
    """Coordinate the test/lint/typecheck runners."""

    def __init__(self, config: QualityGateConfig | None = None) -> None:
        self.config = config or QualityGateConfig()
        self._test = TestRunner()
        self._lint = LintRunner()
        self._type = TypeChecker()

    async def check(
        self,
        test_path: str | None = None,
        code_path: str | None = None,
    ) -> QualityResult:
        """Run the enabled checks in parallel.

        Args:
            test_path: Path passed to pytest. Often the `tests/` directory.
            code_path: Path passed to ruff/mypy. Often the package source dir.

        Returns:
            A `QualityResult` with whatever checks were enabled populated.
        """
        coros: list[asyncio.Task[Any]] = []
        if self.config.run_tests:
            coros.append(
                asyncio.create_task(
                    self._test.run(
                        test_path,
                        self.config.test_timeout,
                        pythonpath=self.config.test_pythonpath,
                    )
                )
            )
        if self.config.run_lint:
            coros.append(asyncio.create_task(self._lint.run(code_path, self.config.lint_timeout)))
        if self.config.run_typecheck:
            coros.append(
                asyncio.create_task(self._type.run(code_path, self.config.typecheck_timeout))
            )
        results = await asyncio.gather(*coros, return_exceptions=True)
        # Map back into the QualityResult. We rely on the order of registration.
        i = 0
        t_result: TestResult | None = None
        l_result: LintResult | None = None
        tc_result: TypeCheckResult | None = None
        if self.config.run_tests:
            r = results[i] if i < len(results) else None
            if isinstance(r, TestResult):
                t_result = r
            i += 1
        if self.config.run_lint:
            r = results[i] if i < len(results) else None
            if isinstance(r, LintResult):
                l_result = r
            i += 1
        if self.config.run_typecheck:
            r = results[i] if i < len(results) else None
            if isinstance(r, TypeCheckResult):
                tc_result = r
            i += 1
        return QualityResult(test=t_result, lint=l_result, typecheck=tc_result)


__all__ = ["QualityGate", "QualityGateConfig", "QualityResult"]
