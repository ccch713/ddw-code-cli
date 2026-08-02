"""`TypeChecker` — async wrapper around `mypy`."""
from __future__ import annotations

import asyncio
import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TypeError:
    """A single mypy error."""

    file: str
    line: int
    column: int
    message: str
    code: str

    def format(self) -> str:
        return f"{self.file}:{self.line}:{self.column}: [{self.code}] {self.message}"


@dataclass(frozen=True)
class TypeCheckResult:
    """Structured result of a mypy run."""

    returncode: int
    errors: list[TypeError] = field(default_factory=list)
    output: str = ""
    stderr: str = ""

    @property
    def passed_ok(self) -> bool:
        return self.returncode == 0 and not self.errors

    def summary(self) -> str:
        if self.passed_ok:
            return "typecheck: no errors"
        codes = sorted({e.code for e in self.errors if e.code})
        return f"typecheck: {len(self.errors)} errors, codes={codes}"


# mypy output is one of:
#   file.py:line:col: error: message [code]
#   file.py:line: error: message [code]   (col omitted)
# We support both. The trailing `[code]` is optional too.
_LINE_RX = re.compile(
    r"^(?P<file>[^:\s][^:]*?):(?P<line>\d+)(?::(?P<col>\d+))?:\s*error:\s*(?P<msg>.+?)(?:\s*\[(?P<code>[A-Za-z0-9_\-]+)\])?\s*$"
)


def _parse_mypy_output(text: str) -> list[TypeError]:
    """Extract structured errors from mypy's text output."""
    errs: list[TypeError] = []
    for line in text.splitlines():
        stripped = line.strip()
        m = _LINE_RX.match(stripped)
        if not m:
            continue
        try:
            errs.append(
                TypeError(
                    file=m.group("file"),
                    line=int(m.group("line")),
                    column=int(m.group("col") or 0),
                    message=m.group("msg"),
                    code=m.group("code") or "",
                )
            )
        except (KeyError, ValueError, IndexError):
            continue
    return errs


class TypeChecker:
    """Run `mypy` asynchronously."""

    DEFAULT_TIMEOUT = 180

    async def run(
        self,
        path: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        ignore_missing_imports: bool = True,
    ) -> TypeCheckResult:
        """Run mypy and return a structured result.

        Args:
            path: File or directory to check. `None` means current directory.
            timeout: Max seconds.
            ignore_missing_imports: Pass --ignore-missing-imports (default True).

        Returns:
            A `TypeCheckResult`. Never raises on type failure; only on hard errors.
        """
        if shutil.which("mypy") is None:
            return TypeCheckResult(
                returncode=127,
                output="",
                stderr="mypy executable not found in PATH",
            )
        capped = min(int(timeout), self.DEFAULT_TIMEOUT)
        args: list[str] = ["mypy", "--no-color-output", "--show-error-codes"]
        if ignore_missing_imports:
            args.append("--ignore-missing-imports")
        if path:
            args.append(path)
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "LC_ALL": "C.UTF-8"},
            )
        except Exception as e:  # pragma: no cover
            return TypeCheckResult(returncode=1, stderr=f"failed to spawn mypy: {e}")
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=capped)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            finally:
                return TypeCheckResult(
                    returncode=124,
                    output="",
                    stderr=f"mypy timed out after {capped}s",
                )
        out = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
        err = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
        errors = _parse_mypy_output(out + "\n" + err)
        return TypeCheckResult(
            returncode=proc.returncode or 0,
            errors=errors,
            output=out,
            stderr=err,
        )


__all__ = ["TypeCheckResult", "TypeError", "TypeChecker"]
