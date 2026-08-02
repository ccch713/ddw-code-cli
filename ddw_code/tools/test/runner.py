"""`test_run` — run the project's pytest suite."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ._helpers import ToolNotFoundError, _resolve_cwd, _run


@dataclass(frozen=True)
class TestSummary:
    """Structured summary of a pytest run."""

    returncode: int
    passed: int
    failed: int
    errors: int
    skipped: int
    output: str

    @property
    def passed_ok(self) -> bool:
        return self.returncode == 0 and self.failed == 0 and self.errors == 0


_PASS_RX = re.compile(r"(\d+)\s+passed")
_FAIL_RX = re.compile(r"(\d+)\s+failed")
_ERR_RX = re.compile(r"(\d+)\s+errors?")
_SKIP_RX = re.compile(r"(\d+)\s+skipped")


def _parse_summary(returncode: int, stdout: str) -> TestSummary:
    """Extract a structured summary from pytest's terminal output.

    Looks at the whole output rather than the last line — pytest sometimes
    inserts a "=== short test summary info ===" block that confuses naive
    parsers. Falls back to `(0, 0, 0, 0)` if no summary line is present.
    """
    text = stdout or ""
    # Find the summary line(s). They look like:
    #   === 1 passed, 2 failed in 0.42s ===
    # or:
    #   === 1 failed in 0.01s ===
    summary_block = ""
    if "=" in text:
        # Take everything after the last "===" separator block.
        summary_block = text.rsplit("===", 2)[-2] if text.count("===") >= 2 else text
    m_pass = _PASS_RX.search(summary_block) or _PASS_RX.search(text)
    m_fail = _FAIL_RX.search(summary_block) or _FAIL_RX.search(text)
    m_err = _ERR_RX.search(summary_block) or _ERR_RX.search(text)
    m_skip = _SKIP_RX.search(summary_block) or _SKIP_RX.search(text)
    return TestSummary(
        returncode=returncode,
        passed=int(m_pass.group(1)) if m_pass else 0,
        failed=int(m_fail.group(1)) if m_fail else 0,
        errors=int(m_err.group(1)) if m_err else 0,
        skipped=int(m_skip.group(1)) if m_skip else 0,
        output=stdout,
    )


async def test_run(
    path: str | None = None,
    pattern: str = "test_*.py",
    verbose: bool = True,
    timeout: int = 180,
) -> str:
    """Run pytest against `path` (or the current directory if not given).

    Args:
        path: File or directory to pass to pytest. `None` runs the whole suite.
        pattern: pytest `-k` expression (default matches `test_*.py` via the standard discovery).
        verbose: If True, add `-v` and `--tb=short` for readable output.
        timeout: Max seconds (capped at 300).

    Returns:
        Human-readable summary plus the raw tail of the pytest output.
    """
    cwd = _resolve_cwd(path)
    args: list[str] = ["pytest", "-q" if not verbose else "-v", "--tb=short"]
    if path:
        args.append(path)
    try:
        rc, out, err = await _run(args, cwd=cwd, timeout=timeout)
    except ToolNotFoundError as e:
        return f"test_run error: {e}"
    except TimeoutError as e:
        return f"test_run error: {e}"
    summary = _parse_summary(rc, out)
    head = (
        f"pytest exit={rc} "
        f"passed={summary.passed} failed={summary.failed} "
        f"errors={summary.errors} skipped={summary.skipped}"
    )
    # Keep the tail of the output for context (last 20 lines).
    tail_lines = out.splitlines()[-20:] if out else []
    tail = "\n".join(tail_lines)
    if err.strip() and rc != 0:
        tail = f"{tail}\n[stderr]\n{err.strip()}" if tail else err.strip()
    return f"{head}\n{tail}".rstrip()


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File or directory to test. Defaults to the current directory.",
            },
            "pattern": {
                "type": "string",
                "description": "pytest -k expression. Default: 'test_*.py'.",
                "default": "test_*.py",
            },
            "verbose": {
                "type": "boolean",
                "description": "Verbose output (-v --tb=short).",
                "default": True,
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait (capped at 300).",
                "default": 180,
                "minimum": 10,
                "maximum": 300,
            },
        },
    }
