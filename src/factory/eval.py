"""Eval harness: run golden tasks through the pipeline and measure pass-rate.

A *case* is a task, a starting repo (a handful of seed files), and assertions
about the outcome. The harness builds a throwaway git repo per case, runs the
real engine with any backend, and grades the result. This turns "does the
factory work?" into a number you can track over time and gate on.

Cases live in a suite: a directory of ``*.json`` files, or one JSON file holding
a list. See ``evals/cases/`` for examples and ``evals/README.md`` for the schema.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import pr as pr_mod
from .config import Settings
from .engine import Engine
from .models import Task
from .state import Store

_DEFAULT_CHECKS = "python -m pytest -q"


@dataclass
class CaseResult:
    """Grading outcome for one golden task."""

    case_id: str
    passed: bool
    state: str
    reasons: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    duration: float = 0.0


@dataclass
class SuiteResult:
    """Aggregate outcome for a whole suite."""

    cases: list[CaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.passed)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


def load_suite(path: Path) -> list[dict]:
    """Load cases from a directory of ``*.json`` files or a single JSON file."""
    path = Path(path)
    if path.is_dir():
        cases = []
        for f in sorted(path.glob("*.json")):
            cases.append(_read_case(f))
        return cases
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else [data]
    raise FileNotFoundError(f"suite not found: {path}")


def _read_case(path: Path) -> dict:
    case = json.loads(path.read_text(encoding="utf-8"))
    case.setdefault("id", path.stem)
    return case


def run_suite(cases: list[dict], backend: str, *, workdir: Path | None = None) -> SuiteResult:
    """Run every case and grade it. Uses a temp dir unless ``workdir`` is given."""
    result = SuiteResult()
    if workdir is not None:
        workdir.mkdir(parents=True, exist_ok=True)
        for case in cases:
            result.cases.append(_run_case(case, backend, workdir))
        return result

    with tempfile.TemporaryDirectory(prefix="factory-eval-") as tmp:
        root = Path(tmp)
        for case in cases:
            result.cases.append(_run_case(case, backend, root))
    return result


def _run_case(case: dict, backend: str, root: Path) -> CaseResult:
    case_id = str(case["id"])
    start = time.monotonic()
    case_dir = root / _slug(case_id)
    remote, seed = _build_repo(case, case_dir)

    task = Task(
        external_id=case_id,
        title=case.get("title", case_id),
        body=case.get("body", ""),
        labels=case.get("labels", []),
    )
    settings = Settings(**_settings_kwargs(case, case_dir, seed))
    settings.ensure_dirs()
    store = Store(settings.db_path)
    store.upsert(task)

    # Stub PR creation: an eval measures "would this become a PR", not the PR
    # itself, so no GitHub auth is needed.
    original = pr_mod.create_pr
    pr_mod.create_pr = lambda **kw: pr_mod.PullRequest(url="eval://pr", number=0)
    checks_before = os.environ.get("FACTORY_CHECKS")
    os.environ["FACTORY_CHECKS"] = case.get("checks", _DEFAULT_CHECKS)
    try:
        Engine(settings, store, backend).process(task)
    finally:
        pr_mod.create_pr = original
        if checks_before is None:
            os.environ.pop("FACTORY_CHECKS", None)
        else:
            os.environ["FACTORY_CHECKS"] = checks_before
        store.close()

    changed = _changed_files(remote, "main", task.branch)
    return _grade(case, task, changed, time.monotonic() - start)


def _grade(case: dict, task: Task, changed: list[str], duration: float) -> CaseResult:
    expect = case.get("expect", {})
    expected_state = expect.get("state", "pr_open")
    reasons: list[str] = []

    if task.state.value != expected_state:
        reasons.append(f"state {task.state.value!r} != expected {expected_state!r}")

    for path in expect.get("files_changed_contains", []):
        if path not in changed:
            reasons.append(f"expected change to {path!r}; changed={changed}")
    for path in expect.get("files_changed_excludes", []):
        if path in changed:
            reasons.append(f"unexpected change to {path!r}")

    return CaseResult(
        case_id=str(case["id"]),
        passed=not reasons,
        state=task.state.value,
        reasons=reasons,
        changed_files=changed,
        duration=duration,
    )


def _settings_kwargs(case: dict, case_dir: Path, seed: Path) -> dict:
    """Build Settings kwargs, dropping any the installed Settings does not know.

    Keeps the harness forward/backward compatible: a case may set fields (e.g.
    ``spec_stage``) that only newer Settings versions expose.
    """
    import dataclasses

    known = {f.name for f in dataclasses.fields(Settings)}
    wanted = {
        "repo": seed,
        "remote": "origin",
        "base_branch": "main",
        "work_root": case_dir / "work",
        "db_path": case_dir / "work" / "state.db",
        "branch_prefix": "factory/",
        "git_author_name": "factory-eval",
        "git_author_email": "eval@users.noreply.github.com",
        "max_repairs": int(case.get("max_repairs", 1)),
        "task_timeout_seconds": int(case.get("task_timeout", 120)),
        "agent_timeout_seconds": int(case.get("agent_timeout", 120)),
        "spec_stage": bool(case.get("spec_stage", True)),
    }
    return {k: v for k, v in wanted.items() if k in known}


def _build_repo(case: dict, case_dir: Path) -> tuple[Path, Path]:
    """Create a bare remote seeded with the case's files. Returns (remote, seed)."""
    remote = case_dir / "remote.git"
    seed = case_dir / "seed"
    case_dir.mkdir(parents=True, exist_ok=True)
    _git(["init", "--bare", "-b", "main", str(remote)])
    _git(["clone", str(remote), str(seed)])
    _git(["config", "user.name", "eval"], cwd=seed)
    _git(["config", "user.email", "eval@users.noreply.github.com"], cwd=seed)

    for rel, content in case.get("seed_files", {}).items():
        target = seed / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    if not case.get("seed_files"):
        (seed / "README.md").write_text("seed\n", encoding="utf-8")

    _git(["add", "-A"], cwd=seed)
    _git(["commit", "-m", "seed"], cwd=seed)
    _git(["push", "-u", "origin", "main"], cwd=seed)
    return remote, seed


def _changed_files(remote: Path, base: str, branch: str) -> list[str]:
    if not branch:
        return []
    proc = subprocess.run(
        ["git", "diff", "--name-only", base, branch],
        cwd=remote,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _git(args: list[str], cwd: Path | None = None) -> None:
    proc = subprocess.run(["git", *args], check=False, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{proc.stderr}")


def _slug(raw: str) -> str:
    keep = [c if c.isalnum() else "-" for c in raw.lower()]
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "case"


def format_report(result: SuiteResult) -> str:
    """Human-readable suite summary."""
    lines = []
    for case in result.cases:
        mark = "PASS" if case.passed else "FAIL"
        lines.append(f"[{mark}] {case.case_id} ({case.state}, {case.duration:.1f}s)")
        for reason in case.reasons:
            lines.append(f"       - {reason}")
    lines.append("")
    lines.append(f"pass-rate: {result.passed}/{result.total} ({result.pass_rate:.0%})")
    return "\n".join(lines)


def as_dict(result: SuiteResult) -> dict:
    """Machine-readable suite summary."""
    return {
        "total": result.total,
        "passed": result.passed,
        "pass_rate": result.pass_rate,
        "cases": [
            {
                "id": c.case_id,
                "passed": c.passed,
                "state": c.state,
                "reasons": c.reasons,
                "changed_files": c.changed_files,
                "duration": round(c.duration, 2),
            }
            for c in result.cases
        ],
    }
