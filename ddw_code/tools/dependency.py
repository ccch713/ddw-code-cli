"""`dependency` — list / add / remove Python dependencies.

The tool is deliberately small. It supports two ecosystems out of the box:

- `requirements.txt` (when present, with no `pyproject.toml`)
- `pyproject.toml` (PEP 621 format, when present)

For `add`/`remove` the file is rewritten in place. Unknown actions return a
friendly error rather than crashing the agent.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal


class DependencyError(RuntimeError):
    """Raised for malformed dependency input."""


_ACTION = Literal["list", "add", "remove"]


_REQ_LINE = re.compile(r"^([A-Za-z0-9_.\-]+)\s*(\[.*\])?\s*([<>=!~].*)?$")


def _detect_manifest(workspace: Path) -> tuple[Path, str]:
    """Return (manifest_path, kind) where kind is 'requirements' or 'pyproject'.

    Prefers `pyproject.toml` if both exist.
    """
    pyproject = workspace / "pyproject.toml"
    if pyproject.exists():
        return pyproject, "pyproject"
    req = workspace / "requirements.txt"
    if req.exists():
        return req, "requirements"
    # Default: create one in the workspace if listing is asked.
    return req, "requirements"


def _list_requirements(path: Path) -> list[str]:
    if not path.exists():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def _write_requirements(path: Path, deps: list[str]) -> None:
    text = "\n".join(deps) + ("\n" if deps else "")
    path.write_text(text, encoding="utf-8")


def _parse_pyproject_deps(text: str) -> list[str]:
    """Very small PEP 621 parser: pulls strings out of project.dependencies."""
    out: list[str] = []
    m = re.search(r"\[project\](.*?)(?=\n\[|\Z)", text, re.DOTALL)
    if not m:
        return out
    block = m.group(1)
    dm = re.search(r"dependencies\s*=\s*\[(.*?)\]", block, re.DOTALL)
    if not dm:
        return out
    for raw in re.findall(r"['\"]([^'\"]+)['\"]", dm.group(1)):
        out.append(raw.strip())
    return out


def _replace_pyproject_deps(text: str, deps: list[str]) -> str:
    """Replace the `project.dependencies = [...]` block with a new list."""
    rendered = "[\n" + "".join(f'    "{d}",\n' for d in deps) + "]"
    pattern = re.compile(r"(dependencies\s*=\s*)\[(.*?)\]", re.DOTALL)
    if pattern.search(text):
        return pattern.sub(lambda _m: f"{_m.group(1)}{rendered}", text, count=1)
    # No block yet — inject after `[project]\n`.
    inject_after = re.compile(r"(\[project\][^\n]*\n)", re.MULTILINE)
    if inject_after.search(text):
        return inject_after.sub(
            lambda m: f"{m.group(1)}dependencies = {rendered}\n",
            text,
            count=1,
        )
    # Append a brand-new [project] table.
    block = f"[project]\ndependencies = {rendered}\n"
    return text.rstrip() + "\n\n" + block


def _normalise_package(package: str) -> str:
    """Strip whitespace and surrounding quotes; ensure no inline comments."""
    p = package.strip()
    if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
        p = p[1:-1]
    if "#" in p:
        p = p.split("#", 1)[0].strip()
    if not p or not _REQ_LINE.match(p):
        raise DependencyError(f"invalid dependency spec: {package!r}")
    return p


async def dependency(
    action: str = "list",
    package: str | None = None,
    path: str = ".",
) -> str:
    """Inspect or modify a Python project's dependencies.

    Args:
        action: One of `list`, `add`, `remove`.
        package: Required for `add`/`remove` (e.g. `requests>=2.31`).
        path: Workspace root containing the manifest (default `.`).

    Returns:
        A short human-readable summary.
    """
    act: str = (action or "list").lower().strip()
    if act not in {"list", "add", "remove"}:
        return f"dependency error: unknown action {action!r} (expected list/add/remove)"
    workspace = Path(path)
    if not workspace.exists() or not workspace.is_dir():
        return f"dependency error: not a directory: {workspace}"
    manifest, kind = _detect_manifest(workspace)
    if act == "list":
        if kind == "pyproject":
            text = manifest.read_text(encoding="utf-8", errors="replace") if manifest.exists() else ""
            deps = _parse_pyproject_deps(text)
        else:
            deps = _list_requirements(manifest)
        if not deps:
            return f"[no dependencies] in {manifest}"
        return "\n".join(deps)
    if not package:
        return f"dependency error: 'package' is required for action={act}"
    try:
        normalised = _normalise_package(package)
    except DependencyError as e:
        return f"dependency error: {e}"
    if kind == "pyproject":
        text = manifest.read_text(encoding="utf-8", errors="replace") if manifest.exists() else ""
        deps = _parse_pyproject_deps(text)
    else:
        deps = _list_requirements(manifest)
    if act == "add":
        if any(d.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].split("!=")[0].split(">")[0].split("<")[0].strip().lower() == normalised.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].split("!=")[0].split(">")[0].split("<")[0].strip().lower() for d in deps):
            return f"dependency: {normalised} already in {manifest}"
        deps.append(normalised)
    else:  # remove
        new_deps = []
        removed = False
        for d in deps:
            head = d.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].split("!=")[0].split(">")[0].split("<")[0].strip().lower()
            if not removed and head == normalised.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].split("!=")[0].split(">")[0].split("<")[0].strip().lower():
                removed = True
                continue
            new_deps.append(d)
        if not removed:
            return f"dependency: {normalised} not found in {manifest}"
        deps = new_deps
    if kind == "pyproject":
        text = manifest.read_text(encoding="utf-8", errors="replace") if manifest.exists() else ""
        new_text = _replace_pyproject_deps(text, deps)
        manifest.write_text(new_text, encoding="utf-8")
    else:
        _write_requirements(manifest, deps)
    return f"dependency: {act} {normalised} -> {manifest}\nnow:\n" + "\n".join(deps)


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "add", "remove"],
                "description": "Operation to perform.",
                "default": "list",
            },
            "package": {
                "type": "string",
                "description": "Dependency spec (e.g. 'requests>=2.31'). Required for add/remove.",
            },
            "path": {
                "type": "string",
                "description": "Workspace root containing the manifest.",
                "default": ".",
            },
        },
    }
