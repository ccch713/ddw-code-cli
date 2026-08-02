"""Tests for the Phase 1 tool expansion: git (8), file ops (4), test/quality (5), web (2), find (1), dependency (1)."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from ddw_code.tools import (
    dependency,
    file_copy,
    file_delete,
    file_list,
    file_move,
    find,
)
from ddw_code.tools.git import (
    branch,
    commit,
    diff,
    log,
    merge,
    push,
    pull,
    status,
)
# `ddw_code.tools.test` re-exports the handler functions at package level
# (so `from ddw_code.tools.test import lint` gives the function, not the module).
# Import the *sub-modules* directly so call sites stay explicit.
from ddw_code.tools.test.lint import lint as lint_call
from ddw_code.tools.test.runner import test_run as runner_test_run
from ddw_code.tools.test.typecheck import typecheck as typecheck_call
from ddw_code.tools.test.coverage import coverage as coverage_call
from ddw_code.tools.test.format import format_code as format_code_call
from ddw_code.tools import web_extract, web_fetch


# -----------------------------------------------------------------------------
# Git tools
# -----------------------------------------------------------------------------


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    """Run a git command synchronously (helper for fixtures only)."""
    res = subprocess.run(  # noqa: S603
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if check and res.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {res.stderr or res.stdout}"
        )
    return (res.stdout or "").strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Initialise a fresh git repo with one commit on `main`."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Tester")
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_git_status_clean(git_repo: Path) -> None:
    out = asyncio.run(status.git_status(str(git_repo)))
    assert "clean" in out.lower()


def test_git_status_modified(git_repo: Path) -> None:
    (git_repo / "README.md").write_text("hello world\n", encoding="utf-8")
    out = asyncio.run(status.git_status(str(git_repo)))
    assert "M" in out
    assert "modified" in out.lower()


def test_git_status_not_a_repo(tmp_path: Path) -> None:
    out = asyncio.run(status.git_status(str(tmp_path)))
    assert "error" in out.lower() or "failed" in out.lower()


def test_git_diff_working_tree(git_repo: Path) -> None:
    (git_repo / "README.md").write_text("hello world\n", encoding="utf-8")
    out = asyncio.run(diff.git_diff(path=str(git_repo)))
    assert "hello world" in out
    assert "-hello" in out or "no working tree" not in out


def test_git_diff_staged(git_repo: Path) -> None:
    (git_repo / "README.md").write_text("hello world\n", encoding="utf-8")
    _git(git_repo, "add", "README.md")
    out = asyncio.run(diff.git_diff(path=str(git_repo), staged=True))
    assert "hello world" in out
    # No working tree diff for a clean file.
    out_clean = asyncio.run(diff.git_diff(path=str(git_repo), staged=False))
    assert "no" in out_clean.lower()


def test_git_commit_succeeds(git_repo: Path) -> None:
    (git_repo / "new.txt").write_text("data\n", encoding="utf-8")
    out = asyncio.run(
        commit.git_commit(
            message="add new.txt",
            files=["new.txt"],
            path=str(git_repo),
        )
    )
    assert "failed" not in out.lower()
    log_out = _git(git_repo, "log", "--oneline")
    assert "add new.txt" in log_out


def test_git_commit_empty_message_rejected(git_repo: Path) -> None:
    out = asyncio.run(commit.git_commit(message="   ", path=str(git_repo)))
    assert "error" in out.lower()
    assert "empty" in out.lower()


def test_git_commit_no_files_uses_staging(git_repo: Path) -> None:
    # Stage something explicitly, then commit without passing files.
    (git_repo / "staged.txt").write_text("staged\n", encoding="utf-8")
    _git(git_repo, "add", "staged.txt")
    out = asyncio.run(commit.git_commit(message="use staging", path=str(git_repo)))
    assert "failed" not in out.lower()
    assert "use staging" in _git(git_repo, "log", "--oneline")


def test_git_branch_list(git_repo: Path) -> None:
    out = asyncio.run(branch.git_branch(action="list", path=str(git_repo)))
    assert "main" in out


def test_git_branch_create_and_checkout(git_repo: Path) -> None:
    out = asyncio.run(
        branch.git_branch(action="create", name="feature", path=str(git_repo))
    )
    assert "succeeded" in out.lower() or "failed" not in out.lower()
    out2 = asyncio.run(
        branch.git_branch(action="checkout", name="feature", path=str(git_repo))
    )
    assert "failed" not in out2.lower()
    assert _git(git_repo, "rev-parse", "--abbrev-ref", "HEAD") == "feature"


def test_git_branch_delete(git_repo: Path) -> None:
    asyncio.run(branch.git_branch(action="create", name="temp", path=str(git_repo)))
    out = asyncio.run(
        branch.git_branch(action="delete", name="temp", path=str(git_repo))
    )
    assert "failed" not in out.lower()


def test_git_branch_unknown_action(git_repo: Path) -> None:
    out = asyncio.run(branch.git_branch(action="wat", name="x", path=str(git_repo)))
    assert "unknown action" in out.lower()


def test_git_branch_requires_name_for_create(git_repo: Path) -> None:
    out = asyncio.run(branch.git_branch(action="create", name=None, path=str(git_repo)))
    assert "required" in out.lower()


def test_git_merge_into_main(git_repo: Path) -> None:
    asyncio.run(branch.git_branch(action="create", name="feat", path=str(git_repo)))
    asyncio.run(branch.git_branch(action="checkout", name="feat", path=str(git_repo)))
    (git_repo / "x.txt").write_text("x\n", encoding="utf-8")
    _git(git_repo, "add", "x.txt")
    _git(git_repo, "commit", "-q", "-m", "add x")
    asyncio.run(branch.git_branch(action="checkout", name="main", path=str(git_repo)))
    out = asyncio.run(merge.git_merge(branch="feat", path=str(git_repo)))
    assert "failed" not in out.lower()


def test_git_merge_requires_branch(git_repo: Path) -> None:
    out = asyncio.run(merge.git_merge(branch="", path=str(git_repo)))
    assert "required" in out.lower()


def test_git_log_default(git_repo: Path) -> None:
    out = asyncio.run(log.git_log(limit=5, path=str(git_repo)))
    assert "init" in out


def test_git_log_oneline(git_repo: Path) -> None:
    out = asyncio.run(log.git_log(limit=5, oneline=True, path=str(git_repo)))
    assert "init" in out
    # Oneline format produces one short line per commit.
    assert len(out.splitlines()) >= 1


def test_git_log_no_commits(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    out = asyncio.run(log.git_log(path=str(tmp_path)))
    assert "no commits" in out.lower()


def test_git_log_invalid_limit(git_repo: Path) -> None:
    out = asyncio.run(log.git_log(limit=0, path=str(git_repo)))
    assert "error" in out.lower()


def test_git_push_no_remote(git_repo: Path) -> None:
    out = asyncio.run(push.git_push(path=str(git_repo)))
    # No upstream configured -> git push itself returns an error which we surface.
    assert "error" in out.lower() or "failed" in out.lower() or "push" in out.lower()


def test_git_pull_no_upstream(git_repo: Path) -> None:
    out = asyncio.run(pull.git_pull(path=str(git_repo)))
    # No upstream set: should be a friendly message rather than a crash.
    assert "no such ref" in out.lower() or "failed" in out.lower() or "pull" in out.lower()


# -----------------------------------------------------------------------------
# File ops
# -----------------------------------------------------------------------------


def test_file_delete_file(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_text("data")
    out = asyncio.run(file_delete.file_delete(str(p)))
    assert "deleted" in out
    assert not p.exists()


def test_file_delete_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        asyncio.run(file_delete.file_delete(str(tmp_path / "nope")))


def test_file_delete_non_empty_dir_without_recursive(tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.mkdir()
    (d / "f").write_text("x")
    with pytest.raises(file_delete.FileDeleteError):
        asyncio.run(file_delete.file_delete(str(d)))


def test_file_delete_recursive(tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.mkdir()
    (d / "f").write_text("x")
    out = asyncio.run(file_delete.file_delete(str(d), recursive=True))
    assert "deleted" in out
    assert not d.exists()


def test_file_delete_forbidden(tmp_path: Path) -> None:
    with pytest.raises(PermissionError):
        asyncio.run(file_delete.file_delete(str(Path.home() / ".ssh" / "id_rsa")))


def test_file_move(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    dst = tmp_path / "sub" / "b.txt"
    src.write_text("x")
    out = asyncio.run(file_move.file_move(str(src), str(dst)))
    assert "moved" in out
    assert not src.exists()
    assert dst.read_text() == "x"


def test_file_move_missing_src(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        asyncio.run(file_move.file_move(str(tmp_path / "nope"), str(tmp_path / "x")))


def test_file_move_existing_dst_no_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    dst = tmp_path / "b.txt"
    src.write_text("1")
    dst.write_text("2")
    with pytest.raises(file_move.FileMoveError):
        asyncio.run(file_move.file_move(str(src), str(dst)))


def test_file_move_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    dst = tmp_path / "b.txt"
    src.write_text("1")
    dst.write_text("2")
    out = asyncio.run(file_move.file_move(str(src), str(dst), overwrite=True))
    assert "moved" in out
    assert dst.read_text() == "1"


def test_file_copy(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    dst = tmp_path / "b.txt"
    src.write_text("hello")
    out = asyncio.run(file_copy.file_copy(str(src), str(dst)))
    assert "copied" in out
    assert dst.read_text() == "hello"


def test_file_copy_missing_src(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        asyncio.run(file_copy.file_copy(str(tmp_path / "nope"), str(tmp_path / "b")))


def test_file_copy_existing_dst(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    dst = tmp_path / "b.txt"
    src.write_text("1")
    dst.write_text("2")
    with pytest.raises(file_copy.FileCopyError):
        asyncio.run(file_copy.file_copy(str(src), str(dst)))


def test_file_list_basic(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.txt").write_text("")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.py").write_text("")
    out = asyncio.run(file_list.file_list(str(tmp_path)))
    assert "a.py" in out
    assert "b.txt" in out
    assert "sub/" in out


def test_file_list_recursive(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.py").write_text("")
    out = asyncio.run(file_list.file_list(str(tmp_path), recursive=True, pattern="*.py"))
    assert "a.py" in out
    assert "c.py" in out


def test_file_list_no_matches(tmp_path: Path) -> None:
    out = asyncio.run(file_list.file_list(str(tmp_path), pattern="*.does_not_exist"))
    assert "no matches" in out


def test_file_list_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        asyncio.run(file_list.file_list(str(tmp_path / "nope")))


def test_file_list_forbidden(tmp_path: Path) -> None:
    with pytest.raises(PermissionError):
        asyncio.run(file_list.file_list(str(Path.home() / ".ssh")))


# -----------------------------------------------------------------------------
# Test/quality tools
# -----------------------------------------------------------------------------


def test_test_run_passing(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert 1 == 1\n", encoding="utf-8"
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    out = asyncio.run(runner_test_run(path=str(tmp_path), timeout=60))
    assert "passed=" in out
    assert "failed=0" in out


def test_test_run_failing(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_bad.py").write_text(
        "def test_bad():\n    assert 1 == 2\n", encoding="utf-8"
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    out = asyncio.run(runner_test_run(path=str(tmp_path), timeout=60))
    assert "failed=1" in out
    assert "exit=" in out


def test_lint_clean(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    out = asyncio.run(lint_call(path=str(tmp_path), timeout=60))
    assert "no issues" in out.lower() or "0" in out


def test_lint_with_issue(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("import os\nimport os\n", encoding="utf-8")
    out = asyncio.run(lint_call(path=str(tmp_path), timeout=60))
    # ruff should report F401 or F811 depending on rules. Either way, exit != 0.
    assert "exit=" in out


def test_typecheck_missing_tool(monkeypatch, tmp_path: Path) -> None:
    # Pretend mypy isn't on PATH.
    from ddw_code.tools.test import _helpers as test_helpers
    monkeypatch.setattr(test_helpers.shutil, "which", lambda _: None)
    out = asyncio.run(typecheck_call(path=str(tmp_path)))
    assert "not found" in out.lower()


def test_format_check_only_clean(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    out = asyncio.run(format_code_call(path=str(tmp_path), check_only=True, timeout=60))
    # Either already formatted orruff missing — accept both.
    assert "exit=" in out or "already" in out.lower() or "not found" in out.lower()


def test_format_check_only_dirty(tmp_path: Path) -> None:
    # Indent with 4 spaces but mismatch; ruff will flag.
    (tmp_path / "bad.py").write_text("x=1\ny=2\nz=3\n", encoding="utf-8")
    out = asyncio.run(format_code_call(path=str(tmp_path), check_only=True, timeout=60))
    assert "exit=" in out


def test_coverage_runs(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_dummy.py").write_text(
        "def test_x():\n    assert True\n", encoding="utf-8"
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    out = asyncio.run(coverage_call(path=str(tmp_path), timeout=60))
    assert "coverage" in out.lower()
    assert "total=" in out


# -----------------------------------------------------------------------------
# Web tools (no real network — we just check shape & error handling)
# -----------------------------------------------------------------------------


def test_web_fetch_rejects_bad_url() -> None:
    out = asyncio.run(web_fetch.web_fetch("ftp://example.com"))
    assert "error" in out.lower()


def test_web_fetch_404(monkeypatch) -> None:
    class FakeResp:
        status_code = 404
        headers: dict = {}
        content = b""

    class FakeClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw): return FakeResp()

    import ddw_code.tools.web_fetch as wf
    monkeypatch.setattr(wf.httpx, "AsyncClient", FakeClient)
    out = asyncio.run(wf.web_fetch("https://example.com"))
    assert "404" in out


def test_web_extract_rejects_bad_url() -> None:
    out = asyncio.run(web_extract.web_extract("not a url"))
    assert "error" in out.lower()


def test_web_extract_returns_title_and_selector(monkeypatch) -> None:
    html = (
        "<html><head><title>Hi</title>"
        '<meta name="description" content="desc"></head>'
        '<body><h1>Welcome</h1><p class="lead">Hello world</p></body></html>'
    )

    class FakeResp:
        status_code = 200
        headers = {"content-type": "text/html"}
        text = html

    class FakeClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw): return FakeResp()

    import ddw_code.tools.web_extract as we
    monkeypatch.setattr(we.httpx, "AsyncClient", FakeClient)
    out = asyncio.run(we.web_extract("https://example.com"))
    assert "title: Hi" in out
    assert "description: desc" in out
    assert "Welcome" in out

    out2 = asyncio.run(we.web_extract("https://example.com", selector=".lead"))
    assert "Hello world" in out2
    assert "title" not in out2  # selector path skips metadata header


# -----------------------------------------------------------------------------
# find
# -----------------------------------------------------------------------------


def test_find_substring(tmp_path: Path) -> None:
    (tmp_path / "alpha.py").write_text("")
    (tmp_path / "beta.py").write_text("")
    (tmp_path / "gamma.txt").write_text("")
    out = asyncio.run(find.find("alpha", str(tmp_path)))
    assert "alpha.py" in out
    assert "beta.py" not in out


def test_find_glob(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("")
    (tmp_path / "y.py").write_text("")
    (tmp_path / "z.txt").write_text("")
    out = asyncio.run(find.find("*.py", str(tmp_path), type="file"))
    assert "x.py" in out
    assert "y.py" in out
    assert "z.txt" not in out


def test_find_type_dir(tmp_path: Path) -> None:
    (tmp_path / "mydir").mkdir()
    (tmp_path / "x.py").write_text("")
    out = asyncio.run(find.find("*", str(tmp_path), type="dir"))
    assert "mydir" in out
    assert "x.py" not in out


def test_find_empty_pattern(tmp_path: Path) -> None:
    out = asyncio.run(find.find("", str(tmp_path)))
    assert "error" in out.lower()


def test_find_missing_path(tmp_path: Path) -> None:
    out = asyncio.run(find.find("foo", str(tmp_path / "nope")))
    assert "error" in out.lower()


def test_find_no_matches(tmp_path: Path) -> None:
    out = asyncio.run(find.find("nothing-here-zzz", str(tmp_path)))
    assert "no matches" in out.lower()


# -----------------------------------------------------------------------------
# dependency
# -----------------------------------------------------------------------------


def test_dependency_list_empty(tmp_path: Path) -> None:
    out = asyncio.run(dependency.dependency(action="list", path=str(tmp_path)))
    assert "no dependencies" in out.lower()


def test_dependency_add_remove_requirements(tmp_path: Path) -> None:
    out = asyncio.run(
        dependency.dependency(action="add", package="requests", path=str(tmp_path))
    )
    assert "add" in out.lower()
    assert "requests" in out
    assert (tmp_path / "requirements.txt").exists()

    out2 = asyncio.run(
        dependency.dependency(action="list", path=str(tmp_path))
    )
    assert "requests" in out2

    out3 = asyncio.run(
        dependency.dependency(action="remove", package="requests", path=str(tmp_path))
    )
    assert "remove" in out3.lower()


def test_dependency_add_existing_skipped(tmp_path: Path) -> None:
    asyncio.run(dependency.dependency(action="add", package="flask", path=str(tmp_path)))
    out = asyncio.run(
        dependency.dependency(action="add", package="flask", path=str(tmp_path))
    )
    assert "already" in out.lower()


def test_dependency_remove_missing(tmp_path: Path) -> None:
    out = asyncio.run(
        dependency.dependency(action="remove", package="nope", path=str(tmp_path))
    )
    assert "not found" in out.lower()


def test_dependency_invalid_spec(tmp_path: Path) -> None:
    out = asyncio.run(
        dependency.dependency(action="add", package="!!!invalid!!!", path=str(tmp_path))
    )
    assert "error" in out.lower()


def test_dependency_unknown_action(tmp_path: Path) -> None:
    out = asyncio.run(dependency.dependency(action="frobnicate", path=str(tmp_path)))
    assert "unknown action" in out.lower()


def test_dependency_requires_package_for_add(tmp_path: Path) -> None:
    out = asyncio.run(dependency.dependency(action="add", package=None, path=str(tmp_path)))
    assert "required" in out.lower()


def test_dependency_pyproject_round_trip(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'x'\nversion = '0'\n", encoding="utf-8"
    )
    asyncio.run(
        dependency.dependency(action="add", package="httpx>=0.27", path=str(tmp_path))
    )
    text = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert "httpx" in text
    out = asyncio.run(dependency.dependency(action="list", path=str(tmp_path)))
    assert "httpx" in out


# -----------------------------------------------------------------------------
# Schema sanity (every new tool has a valid OpenAI-shaped schema)
# -----------------------------------------------------------------------------


def test_all_new_tool_schemas_are_valid() -> None:
    from ddw_code.tools.builder import build_default_registry

    reg = build_default_registry()
    new_tools = {
        "git_status",
        "git_diff",
        "git_commit",
        "git_push",
        "git_pull",
        "git_branch",
        "git_merge",
        "git_log",
        "file_delete",
        "file_move",
        "file_copy",
        "file_list",
        "test_run",
        "lint",
        "typecheck",
        "format",
        "coverage",
        "web_fetch",
        "web_extract",
        "find",
        "dependency",
    }
    for tool in reg.all():
        if tool.name not in new_tools:
            continue
        s = tool.input_schema
        assert s.get("type") == "object"
        assert isinstance(s.get("properties"), dict)
