"""run-loop must exit non-zero when a task ends blocked or failed.

A silent green on a broken task is what hid a real failure before: the scheduled
run reported success while every agent attempt had failed. These tests pin the
opposite: an idle run is success, a shipped task is success, a blocked task is a
failure exit code.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from factory import cli
from factory.adapters import base as adapters
from factory.config import Settings
from factory.models import AgentResult, Task, TaskState
from factory.pr import PullRequest
from factory.runner import run_loop
from factory.sources import JsonFileSource
from factory.state import Store


@adapters.register("fake_exit")
class _FakeAdapter(adapters.AgentAdapter):
    name = "fake_exit"

    def run(self, task: Task, worktree: Path, prompt: str) -> AgentResult:
        (worktree / "generated.txt").write_text("from the agent\n")
        return AgentResult(ok=True, summary="SUMMARY: wrote generated.txt")


def _git(args: list[str]) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    _git(["init", "--bare", "-b", "main", str(remote)])
    seed = tmp_path / "seed"
    _git(["clone", str(remote), str(seed)])
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        _git(["-C", str(seed), "config", k, v])
    (seed / "README.md").write_text("seed\n")
    _git(["-C", str(seed), "add", "-A"])
    _git(["-C", str(seed), "commit", "-m", "init"])
    _git(["-C", str(seed), "push", "-u", "origin", "main"])
    return seed


def _write_tasks(tmp_path: Path, ids: list[str]) -> Path:
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps([{"id": i, "title": f"task {i}"} for i in ids]))
    return path


def _settings(tmp_path: Path, seed: Path) -> Settings:
    return Settings(
        repo=seed,
        remote="origin",
        base_branch="main",
        work_root=tmp_path / "work",
        db_path=tmp_path / "work" / "state.db",
        branch_prefix="factory/",
        git_author_name="factory",
        git_author_email="f@f",
        max_repairs=1,
        task_timeout_seconds=120,
        agent_timeout_seconds=120,
    )


def _env(tmp_path: Path, seed: Path, tasks: Path, checks: str) -> dict[str, str]:
    return {
        "FACTORY_REPO": str(seed),
        "FACTORY_REMOTE": "origin",
        "FACTORY_BASE_BRANCH": "main",
        "FACTORY_WORK_ROOT": str(tmp_path / "work"),
        "FACTORY_DB": str(tmp_path / "work" / "state.db"),
        "FACTORY_SOURCE": "json",
        "FACTORY_TASKS_FILE": str(tasks),
        "FACTORY_CHECKS": checks,
        "FACTORY_MAX_REPAIRS": "1",
    }


def test_run_loop_returns_processed_tasks(tmp_path, monkeypatch):
    seed = _init_repo(tmp_path)
    monkeypatch.setenv("FACTORY_CHECKS", "test -f generated.txt")
    monkeypatch.setattr(
        "factory.engine.pr_mod.create_pr",
        lambda **kw: PullRequest(url="https://example.test/pr/1", number=1),
    )
    settings = _settings(tmp_path, seed)
    settings.ensure_dirs()
    store = Store(settings.db_path)
    source = JsonFileSource(_write_tasks(tmp_path, ["a", "b"]))

    processed = run_loop(
        settings, store, source, "fake_exit", max_tasks=2, stop_when_empty=True
    )
    store.close()

    assert [t.external_id for t in processed] == ["a", "b"]
    assert all(t.state is TaskState.PR_OPEN for t in processed)


def test_run_loop_exits_zero_when_queue_is_empty(tmp_path, monkeypatch):
    seed = _init_repo(tmp_path)
    tasks = _write_tasks(tmp_path, [])
    for k, v in _env(tmp_path, seed, tasks, "true").items():
        monkeypatch.setenv(k, v)

    assert cli.main(["run-loop", "--backend", "fake_exit", "--stop-when-empty"]) == 0


def test_run_loop_exits_zero_when_task_ships(tmp_path, monkeypatch, capsys):
    seed = _init_repo(tmp_path)
    tasks = _write_tasks(tmp_path, ["ok-1"])
    for k, v in _env(tmp_path, seed, tasks, "test -f generated.txt").items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(
        "factory.engine.pr_mod.create_pr",
        lambda **kw: PullRequest(url="https://example.test/pr/1", number=1),
    )

    code = cli.main(["run-loop", "--backend", "fake_exit", "--stop-when-empty"])
    out = capsys.readouterr().out

    assert code == 0
    assert "processed 1 task(s)" in out


def test_run_loop_exits_nonzero_when_task_blocked(tmp_path, monkeypatch, capsys):
    seed = _init_repo(tmp_path)
    tasks = _write_tasks(tmp_path, ["bad-1"])
    # Checks always fail -> the task exhausts its repairs and ends BLOCKED.
    for k, v in _env(tmp_path, seed, tasks, "false").items():
        monkeypatch.setenv(k, v)

    code = cli.main(["run-loop", "--backend", "fake_exit", "--stop-when-empty"])
    out = capsys.readouterr().out

    assert code == 1
    assert "processed 1 task(s)" in out
    assert "FAILED bad-1: blocked" in out


def test_run_loop_exits_nonzero_when_task_failed(tmp_path, monkeypatch, capsys):
    seed = _init_repo(tmp_path)
    tasks = _write_tasks(tmp_path, [])
    for k, v in _env(tmp_path, seed, tasks, "true").items():
        monkeypatch.setenv(k, v)

    # FAILED is produced when the engine crashes mid-task; drive the CLI's exit
    # mapping directly rather than relying on that path staying reachable.
    failed = Task(external_id="boom-1", title="boom")
    failed.state = TaskState.FAILED
    failed.detail = "RuntimeError: kaboom"
    monkeypatch.setattr("factory.cli.run_loop", lambda *a, **kw: [failed])

    code = cli.main(["run-loop", "--backend", "fake_exit", "--stop-when-empty"])

    assert code == 1
    assert "FAILED boom-1: failed - RuntimeError: kaboom" in capsys.readouterr().out
