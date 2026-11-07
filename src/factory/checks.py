"""Verification gate: detect the project's checks and run them after the agent.

The gate is what makes this "production": an agent's change only becomes a PR
if it passes lint/test/build. Detection is convention-based and can be fully
overridden with FACTORY_CHECKS (a ';'-separated list of shell commands).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .models import CheckResult
from .proc import run, run_check


def detect_checks(worktree: Path, timeout: int = 900) -> list[tuple[str, str]]:
    """Return an ordered list of (name, shell-command) checks for the project."""
    override = os.environ.get("FACTORY_CHECKS")
    if override:
        checks = []
        for i, cmd in enumerate(c.strip() for c in override.split(";")):
            if cmd:
                checks.append((f"check{i + 1}", cmd))
        return checks

    checks: list[tuple[str, str]] = []
    checks += _python_checks(worktree)
    checks += _node_checks(worktree)
    checks += _make_check(worktree)
    return checks


def _python_checks(worktree: Path) -> list[tuple[str, str]]:
    has_py = (worktree / "pyproject.toml").exists() or (worktree / "setup.cfg").exists()
    if not has_py and not any(worktree.glob("*.py")):
        return []
    checks: list[tuple[str, str]] = []
    if _has_module("ruff"):
        checks.append(("ruff", "ruff check ."))
    if (worktree / "tests").exists() or any(worktree.glob("test_*.py")):
        checks.append(("pytest", "python -m pytest -q"))
    return checks


def _node_checks(worktree: Path) -> list[tuple[str, str]]:
    pkg = worktree / "package.json"
    if not pkg.exists():
        return []
    scripts = {}
    try:
        scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {})
    except (ValueError, OSError):
        return []
    checks: list[tuple[str, str]] = []
    if "lint" in scripts:
        checks.append(("npm-lint", "npm run lint --silent"))
    if "test" in scripts:
        checks.append(("npm-test", "npm test --silent"))
    if "build" in scripts:
        checks.append(("npm-build", "npm run build --silent"))
    return checks


def _make_check(worktree: Path) -> list[tuple[str, str]]:
    if (worktree / "Makefile").exists():
        return [("make", "make")]
    return []


def run_checks(worktree: Path, timeout: int = 900) -> list[CheckResult]:
    specs = detect_checks(worktree, timeout)
    return [run_check(name, cmd, cwd=worktree, timeout=timeout) for name, cmd in specs]


def all_passed(results: list[CheckResult]) -> bool:
    return all(r.ok for r in results)


def failure_report(results: list[CheckResult]) -> str:
    failed = [r for r in results if not r.ok]
    if not failed:
        return ""
    return "\n\n".join(f"### {r.name} failed\n{r.output}" for r in failed)


def _has_module(name: str) -> bool:
    code, _ = run(["sh", "-c", f"command -v {name}"], timeout=10)
    return code == 0
