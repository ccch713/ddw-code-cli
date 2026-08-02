"""`TestRunner` — async wrapper around pytest.

Used by the quality gate to validate generated code. Returns a structured
`TestResult` rather than raw text so callers can branch on the verdict.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TestResult:
    """Structured result of a pytest run."""

    # Tell pytest not to try to collect this class as test cases.
    __test__ = False

    returncode: int
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    output: str = ""
    stderr: str = ""
    duration_s: float = 0.0

    @property
    def passed_ok(self) -> bool:
        """True when pytest exited 0 with no failures or errors."""
        return self.returncode == 0 and self.failed == 0 and self.errors == 0

    def summary(self) -> str:
        return (
            f"tests: passed={self.passed} failed={self.failed} "
            f"errors={self.errors} skipped={self.skipped} exit={self.returncode}"
        )


_PASS_RX = re.compile(r"(\d+)\s+passed")
_FAIL_RX = re.compile(r"(\d+)\s+failed")
_ERR_RX = re.compile(r"(\d+)\s+errors?")
_SKIP_RX = re.compile(r"(\d+)\s+skipped")


def _parse_summary(text: str) -> tuple[int, int, int, int]:
    """Pull (passed, failed, errors, skipped) from pytest's terminal output."""
    p = _PASS_RX.findall(text)
    f = _FAIL_RX.findall(text)
    e = _ERR_RX.findall(text)
    s = _SKIP_RX.findall(text)
    # The last match is the most recent summary (multiple per run possible).
    return (
        int(p[-1]) if p else 0,
        int(f[-1]) if f else 0,
        int(e[-1]) if e else 0,
        int(s[-1]) if s else 0,
    )


class TestRunner:
    """Run pytest asynchronously and return a `TestResult`."""

    DEFAULT_TIMEOUT = 300  # 5 min hard cap

    async def run(
        self,
        path: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        extra_args: list[str] | None = None,
        pythonpath: str | None = None,
    ) -> TestResult:
        """Run pytest and return a structured result.

        Args:
            path: File or directory to test. `None` runs from the current directory.
            timeout: Max seconds (capped at `DEFAULT_TIMEOUT`).
            extra_args: Additional arguments appended to the pytest invocation.
            pythonpath: Optional extra PYTHONPATH entries (colon-separated).

        Returns:
            A `TestResult`. The runner never raises on test failure — only on
            hard errors like pytest missing from PATH.
        """
        if shutil.which("pytest") is None and not os.path.exists(os.path.join(os.path.dirname(sys.executable), "pytest")):
            return TestResult(
                returncode=127,
                output="",
                stderr="pytest executable not found in PATH",
            )
        capped = min(int(timeout), self.DEFAULT_TIMEOUT)
        # Use sys.executable -m pytest to ensure we use the venv's pytest
        args: list[str] = [sys.executable, "-m", "pytest", "-q", "--tb=short", "--no-header"]
        if path:
            args.append(path)
        if extra_args:
            args.extend(extra_args)
        env = {**os.environ, "LC_ALL": "C.UTF-8"}
        if pythonpath:
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{pythonpath}:{existing}" if existing else pythonpath
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except Exception as e:  # pragma: no cover - defensive
            return TestResult(returncode=1, stderr=f"failed to spawn pytest: {e}")
        loop = asyncio.get_event_loop()
        start = loop.time()
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=capped)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            finally:
                return TestResult(
                    returncode=124,
                    output="",
                    stderr=f"pytest timed out after {capped}s",
                )
        duration = loop.time() - start
        out = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
        err = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
        passed, failed, errors, skipped = _parse_summary(out + "\n" + err)
        return TestResult(
            returncode=proc.returncode or 0,
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            output=out,
            stderr=err,
            duration_s=duration,
        )


__all__ = ["TestResult", "TestRunner"]
