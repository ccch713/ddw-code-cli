"""`SelfHealer` — retry loop that feeds failures back to an LLM provider.

The healer's job is the "self-healing" loop described in the spec: when the
quality gate fails, the healer asks a provider for a fixed version of the
code, then re-runs the gate. It caps retries to avoid runaway regeneration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol

from .gate import QualityGate, QualityGateConfig, QualityResult


class HealerProvider(Protocol):
    """Minimal provider contract for the self-healer.

    Any object exposing `async def fix(prompt: str) -> str` works. The
    concrete providers in `ddw_code.providers` already satisfy this
    contract via thin adapter functions.
    """

    async def fix(self, prompt: str) -> str:  # pragma: no cover - structural
        ...


@dataclass(frozen=True)
class HealAttempt:
    """A single retry attempt's outcome."""

    attempt: int
    passed: bool
    code: str
    quality: QualityResult | None
    error: str | None = None


@dataclass(frozen=True)
class HealResult:
    """Final outcome of the self-heal loop."""

    success: bool
    code: str
    attempts: list[HealAttempt] = field(default_factory=list)
    final_quality: QualityResult | None = None

    @property
    def attempts_used(self) -> int:
        return len(self.attempts)


def _build_fix_prompt(
    code: str,
    code_path: str | None,
    quality: QualityResult,
    attempt: int,
) -> str:
    """Build the prompt the healer sends to the LLM."""
    summary_lines: list[str] = []
    if quality.test is not None and not quality.test.passed_ok:
        summary_lines.append(quality.test.summary())
        # Include the tail of the test output for context.
        if quality.test.output:
            tail = "\n".join(quality.test.output.splitlines()[-30:])
            summary_lines.append("--- pytest output (tail) ---")
            summary_lines.append(tail)
    if quality.lint is not None and not quality.lint.passed_ok:
        summary_lines.append(quality.lint.summary())
        for issue in quality.lint.issues[:20]:
            summary_lines.append("  " + issue.format())
    if quality.typecheck is not None and not quality.typecheck.passed_ok:
        summary_lines.append(quality.typecheck.summary())
        for err in quality.typecheck.errors[:20]:
            summary_lines.append("  " + err.format())
    errors = "\n".join(summary_lines) or "(no structured errors; see below)"
    code_section = f"```\n{code}\n```" if code else "(no code provided)"
    return (
        f"You are fixing code that failed quality checks on attempt {attempt}.\n"
        f"Target file: {code_path or '<unspecified>'}\n\n"
        f"Current code:\n{code_section}\n\n"
        f"Quality gate output:\n{errors}\n\n"
        f"Return ONLY the fixed code. Do not include commentary, markdown fences, "
        f"or explanations. The output will be written verbatim to the target file."
    )


def _extract_code(response: str) -> str:
    """Strip optional markdown fences from the LLM's reply."""
    text = response.strip()
    if text.startswith("```"):
        # Drop the first line (```python or ```), then the trailing fence.
        lines = text.splitlines()
        # remove the first fence line
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        # remove the last fence line if present
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).rstrip()
    return text


class SelfHealer:
    """Drive a fix-retry loop until the quality gate passes or retries exhaust."""

    def __init__(
        self,
        provider: HealerProvider,
        gate: QualityGate | None = None,
        max_retries: int = 3,
    ) -> None:
        self.provider = provider
        self.gate = gate or QualityGate(QualityGateConfig())
        self.max_retries = max(1, int(max_retries))

    async def heal(
        self,
        code: str,
        *,
        test_path: str | None = None,
        code_path: str | None = None,
    ) -> HealResult:
        """Run the gate; on failure, ask the provider to fix the code and retry.

        Args:
            code: The current code to validate and (potentially) repair.
            test_path: Passed to the gate's test runner.
            code_path: Passed to the gate's lint/typecheck runners.

        Returns:
            A `HealResult` with the final code, attempts, and last quality result.
        """
        current = code
        attempts: list[HealAttempt] = []
        for attempt_num in range(1, self.max_retries + 1):
            quality = await self.gate.check(test_path=test_path, code_path=code_path)
            attempt = HealAttempt(
                attempt=attempt_num,
                passed=quality.passed,
                code=current,
                quality=quality,
            )
            attempts.append(attempt)
            if quality.passed:
                return HealResult(
                    success=True,
                    code=current,
                    attempts=attempts,
                    final_quality=quality,
                )
            # Last attempt — don't burn an LLM call we'll throw away.
            if attempt_num == self.max_retries:
                break
            prompt = _build_fix_prompt(current, code_path, quality, attempt_num)
            try:
                response = await self.provider.fix(prompt)
            except Exception as e:  # pragma: no cover - depends on provider
                attempts.append(
                    HealAttempt(
                        attempt=attempt_num,
                        passed=False,
                        code=current,
                        quality=quality,
                        error=f"provider call failed: {e}",
                    )
                )
                return HealResult(
                    success=False,
                    code=current,
                    attempts=attempts,
                    final_quality=quality,
                )
            current = _extract_code(response)
        return HealResult(
            success=False,
            code=current,
            attempts=attempts,
            final_quality=attempts[-1].quality if attempts else None,
        )


__all__ = ["SelfHealer", "HealResult", "HealAttempt", "HealerProvider"]
