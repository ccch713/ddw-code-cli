"""`LintRunner` — async wrapper around `ruff check`."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LintIssue:
    """A single lint finding."""

    code: str
    message: str
    file: str
    line: int = 0
    column: int = 0

    def format(self) -> str:
        loc = f"{self.file}:{self.line}" if self.line else self.file
        return f"{loc} [{self.code}] {self.message}"


@dataclass(frozen=True)
class LintResult:
    """Structured result of a ruff run."""

    returncode: int
    issues: list[LintIssue] = field(default_factory=list)
    output: str = ""
    stderr: str = ""

    @property
    def passed_ok(self) -> bool:
        return self.returncode == 0 and not self.issues

    def summary(self) -> str:
        if self.passed_ok:
            return "lint: no issues"
        codes = sorted({i.code for i in self.issues})
        return f"lint: {len(self.issues)} issues, codes={codes}"


class LintRunner:
    """Run `ruff check` asynchronously."""

    DEFAULT_TIMEOUT = 120

    async def run(
        self,
        path: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        fix: bool = False,
    ) -> LintResult:
        """Run ruff and parse its JSON output.

        Args:
            path: File or directory to lint. `None` means current directory.
            timeout: Max seconds.
            fix: If True, pass `--fix` so ruff auto-fixes what's safe.

        Returns:
            A `LintResult`. Never raises on lint failure; only on hard errors.
        """
        if shutil.which("ruff") is None:
            return LintResult(
                returncode=127,
                output="",
                stderr="ruff executable not found in PATH",
            )
        capped = min(int(timeout), self.DEFAULT_TIMEOUT)
        args: list[str] = [
            "ruff",
            "check",
            "--output-format=json",
            "--no-fix" if not fix else "--fix",
        ]
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
            return LintResult(returncode=1, stderr=f"failed to spawn ruff: {e}")
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=capped)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            finally:
                return LintResult(
                    returncode=124,
                    output="",
                    stderr=f"ruff timed out after {capped}s",
                )
        out = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
        err = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
        issues: list[LintIssue] = []
        if out.strip():
            try:
                raw = json.loads(out)
                if isinstance(raw, list):
                    for item in raw:
                        issues.append(
                            LintIssue(
                                code=str(item.get("code", "")),
                                message=str(item.get("message", "")),
                                file=str(item.get("filename", "")),
                                line=int(item.get("location", {}).get("row", 0) or 0),
                                column=int(item.get("location", {}).get("column", 0) or 0),
                            )
                        )
            except json.JSONDecodeError:
                # Ruff occasionally prints non-JSON with --no-fix; surface it as-is.
                return LintResult(
                    returncode=proc.returncode or 1,
                    output=out,
                    stderr=err,
                )
        return LintResult(
            returncode=proc.returncode or 0,
            issues=issues,
            output=out,
            stderr=err,
        )


__all__ = ["LintResult", "LintIssue", "LintRunner"]
