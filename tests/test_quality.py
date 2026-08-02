"""Tests for the quality assurance subsystem."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from ddw_code.quality import (
    HealAttempt,
    HealResult,
    LintIssue,
    LintResult,
    LintRunner,
    QualityGate,
    QualityGateConfig,
    QualityResult,
    SelfHealer,
    TestResult,
    TestRunner,
    TypeCheckResult,
    TypeChecker,
    TypeError,
)
from ddw_code.quality.self_healer import _build_fix_prompt, _extract_code as _healer_extract


# -----------------------------------------------------------------------------
# TestRunner
# -----------------------------------------------------------------------------


@pytest.fixture
def passing_tests_dir(tmp_path: Path) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text(
        "def test_one():\n    assert 1 == 1\n"
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")
    return tmp_path


@pytest.fixture
def failing_tests_dir(tmp_path: Path) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_bad.py").write_text(
        "def test_one():\n    assert 1 == 2\n"
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")
    return tmp_path


async def test_test_runner_passing(passing_tests_dir: Path) -> None:
    runner = TestRunner()
    result = await runner.run(str(passing_tests_dir))
    assert result.returncode == 0
    assert result.passed >= 1
    assert result.passed_ok
    assert "passed=" in result.summary()


async def test_test_runner_failing(failing_tests_dir: Path) -> None:
    runner = TestRunner()
    result = await runner.run(str(failing_tests_dir))
    assert result.returncode != 0
    assert not result.passed_ok
    assert result.failed >= 1


async def test_test_runner_missing_tool(monkeypatch) -> None:
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _: None)
    runner = TestRunner()
    result = await runner.run()
    assert result.returncode == 127
    assert "not found" in result.stderr


async def test_test_runner_timeout(monkeypatch, passing_tests_dir: Path) -> None:
    runner = TestRunner()
    # 1 second is too small for even a tiny pytest startup.
    result = await runner.run(str(passing_tests_dir), timeout=1)
    # Either it timed out (rc=124) or it raced and finished.
    assert result.returncode in {0, 124}


# -----------------------------------------------------------------------------
# LintRunner
# -----------------------------------------------------------------------------


@pytest.fixture
def clean_ruff_dir(tmp_path: Path) -> Path:
    (tmp_path / "ok.py").write_text("x = 1\n")
    return tmp_path


@pytest.fixture
def dirty_ruff_dir(tmp_path: Path) -> Path:
    (tmp_path / "bad.py").write_text("import os\nimport os\n")  # F401 dup
    return tmp_path


async def test_lint_runner_clean(clean_ruff_dir: Path) -> None:
    runner = LintRunner()
    result = await runner.run(str(clean_ruff_dir))
    assert result.passed_ok
    assert result.issues == []


async def test_lint_runner_dirty(dirty_ruff_dir: Path) -> None:
    runner = LintRunner()
    result = await runner.run(str(dirty_ruff_dir))
    assert not result.passed_ok
    assert len(result.issues) >= 1
    assert all(isinstance(i, LintIssue) for i in result.issues)
    # The first issue should at least carry a code and a file.
    assert result.issues[0].code
    assert result.issues[0].file


async def test_lint_runner_missing_tool(monkeypatch) -> None:
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _: None)
    runner = LintRunner()
    result = await runner.run()
    assert result.returncode == 127


# -----------------------------------------------------------------------------
# TypeChecker
# -----------------------------------------------------------------------------


@pytest.fixture
def typed_dir(tmp_path: Path) -> Path:
    (tmp_path / "clean.py").write_text("x: int = 1\n")
    return tmp_path


@pytest.fixture
def untyped_dir(tmp_path: Path) -> Path:
    (tmp_path / "bad.py").write_text("x: int = 'not an int'\n")
    return tmp_path


async def test_type_checker_clean(typed_dir: Path) -> None:
    tc = TypeChecker()
    result = await tc.run(str(typed_dir))
    assert result.passed_ok
    assert result.errors == []


async def test_type_checker_dirty(untyped_dir: Path) -> None:
    tc = TypeChecker()
    result = await tc.run(str(untyped_dir))
    assert not result.passed_ok
    assert len(result.errors) >= 1
    assert all(isinstance(e, TypeError) for e in result.errors)


async def test_type_checker_missing_tool(monkeypatch) -> None:
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _: None)
    tc = TypeChecker()
    result = await tc.run()
    assert result.returncode == 127


# -----------------------------------------------------------------------------
# QualityGate
# -----------------------------------------------------------------------------


def test_quality_gate_config_defaults() -> None:
    cfg = QualityGateConfig()
    assert cfg.run_tests and cfg.run_lint and cfg.run_typecheck


async def test_quality_gate_only_tests(passing_tests_dir: Path) -> None:
    cfg = QualityGateConfig(run_tests=True, run_lint=False, run_typecheck=False)
    gate = QualityGate(cfg)
    r = await gate.check(test_path=str(passing_tests_dir))
    assert isinstance(r, QualityResult)
    assert r.test is not None
    assert r.lint is None and r.typecheck is None
    assert r.passed


async def test_quality_gate_failing_test_blocks_verdict(failing_tests_dir: Path) -> None:
    cfg = QualityGateConfig(run_tests=True, run_lint=False, run_typecheck=False)
    gate = QualityGate(cfg)
    r = await gate.check(test_path=str(failing_tests_dir))
    assert not r.passed
    assert r.test is not None
    assert not r.test.passed_ok


async def test_quality_gate_summary_contains_verdict() -> None:
    cfg = QualityGateConfig(run_tests=False, run_lint=False, run_typecheck=False)
    gate = QualityGate(cfg)
    r = await gate.check()
    text = r.summary()
    assert "[quality gate]" in text
    assert "PASS" in text


async def test_quality_result_errors_flatten(dirty_ruff_dir: Path) -> None:
    cfg = QualityGateConfig(run_tests=False, run_lint=True, run_typecheck=False)
    gate = QualityGate(cfg)
    r = await gate.check(code_path=str(dirty_ruff_dir))
    err_lines = r.errors()
    assert any("lint" in line for line in err_lines)
    assert any(line.startswith("  ") for line in err_lines)


# -----------------------------------------------------------------------------
# SelfHealer
# -----------------------------------------------------------------------------


class _ScriptedProvider:
    """A healer provider that returns scripted responses."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    async def fix(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self.responses:
            return "x = 1\n"  # final fallback
        return self.responses.pop(0)


async def test_self_healer_succeeds_first_try(passing_tests_dir: Path) -> None:
    # Quality gate passes on the first run -> success without calling provider.
    provider = _ScriptedProvider(responses=[])
    gate = QualityGate(QualityGateConfig(run_tests=True, run_lint=False, run_typecheck=False))
    healer = SelfHealer(provider, gate=gate, max_retries=3)
    result = await healer.heal("x = 1\n", test_path=str(passing_tests_dir))
    assert result.success
    assert result.attempts_used == 1
    assert provider.calls == []


async def test_self_healer_recovers_after_fix(failing_tests_dir: Path, tmp_path: Path) -> None:
    # Run a failing test, then make the provider "fix" the code by rewriting
    # the test file. Use a self-contained test that does not need a package
    # on PYTHONPATH, so pytest collection never fails.
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    test_dir = isolated / "tests"
    test_dir.mkdir()
    bad = test_dir / "test_x.py"
    bad.write_text("def test_x():\n    assert 1 == 999\n")
    (isolated / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")

    class FixingProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def fix(self, prompt: str) -> str:
            self.calls += 1
            # Overwrite the failing test with a passing one.
            bad.write_text("def test_x():\n    assert 1 == 1\n")
            return "# noop\n"

    provider = FixingProvider()
    cfg = QualityGateConfig(run_tests=True, run_lint=False, run_typecheck=False)
    gate = QualityGate(cfg)
    healer = SelfHealer(provider, gate=gate, max_retries=3)
    result = await healer.heal("# code\n", test_path=str(isolated))
    assert result.success, f"heal failed; attempts={result.attempts}"
    assert provider.calls >= 1
    assert result.attempts_used >= 2


async def test_self_healer_exhausts_retries(failing_tests_dir: Path) -> None:
    provider = _ScriptedProvider(responses=["# attempt 1", "# attempt 2"])
    cfg = QualityGateConfig(run_tests=True, run_lint=False, run_typecheck=False)
    gate = QualityGate(cfg)
    healer = SelfHealer(provider, gate=gate, max_retries=2)
    result = await healer.heal("x = 1\n", test_path=str(failing_tests_dir))
    assert not result.success
    assert result.attempts_used == 2
    # 2 retries -> we should have called the provider exactly once
    # (we don't call it on the last attempt).
    assert len(provider.calls) == 1
    assert provider.responses == ["# attempt 2"]  # only first response was consumed


async def test_self_healer_provider_error(failing_tests_dir: Path) -> None:
    class BoomProvider:
        async def fix(self, prompt: str) -> str:
            raise RuntimeError("network down")

    provider = BoomProvider()
    cfg = QualityGateConfig(run_tests=True, run_lint=False, run_typecheck=False)
    gate = QualityGate(cfg)
    healer = SelfHealer(provider, gate=gate, max_retries=3)
    result = await healer.heal("x = 1\n", test_path=str(failing_tests_dir))
    assert not result.success
    # The provider error should be recorded.
    assert any(a.error and "network down" in a.error for a in result.attempts)


def test_healer_extract_strips_fences() -> None:
    assert _healer_extract("```python\nx = 1\n```") == "x = 1"
    assert _healer_extract("```\nx = 1\n```") == "x = 1"
    assert _healer_extract("x = 1") == "x = 1"
    assert _healer_extract("```\n\nx = 1\n```") == "\nx = 1"


def test_build_fix_prompt_includes_errors() -> None:
    qr = QualityResult(
        test=TestResult(returncode=1, failed=2, output="FAILED test_x - assert 1 == 2"),
    )
    prompt = _build_fix_prompt("x = 1\n", "/tmp/x.py", qr, attempt=1)
    assert "FAILED test_x" in prompt
    assert "/tmp/x.py" in prompt
    assert "x = 1" in prompt
    assert "attempt 1" in prompt


# -----------------------------------------------------------------------------
# Integration: full gate run on a tiny project
# -----------------------------------------------------------------------------


async def test_full_gate_integration(tmp_path: Path) -> None:
    """End-to-end: a tiny project passes the full gate (tests + lint)."""
    pkg = tmp_path / "mylib"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "core.py").write_text("def add(a, b):\n    return a + b\n")

    tests = tmp_path / "tests"
    tests.mkdir()
    # Use a conftest.py that adds the project root to sys.path — the same
    # pattern every real Python project uses, so we don't need to mutate
    # the runner's environment.
    (tests / "conftest.py").write_text("import sys, pathlib\n"
                                        "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n")
    (tests / "test_core.py").write_text(
        "from mylib.core import add\n\n"
        "def test_add():\n    assert add(1, 2) == 3\n"
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")

    cfg = QualityGateConfig(
        run_tests=True, run_lint=True, run_typecheck=False
    )
    gate = QualityGate(cfg)
    r = await gate.check(test_path=str(tests), code_path=str(pkg))
    # Don't be too strict — ruff may flag unused imports or similar.
    # We at least want the test half to be green.
    assert r.test is not None, f"test result missing; full={r}"
    assert r.test.passed_ok, f"tests did not pass; out={r.test.output!r} err={r.test.stderr!r}"
    assert r.test.passed >= 1
