"""End-to-end and unit tests for the coding factory (standard library + pytest)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from factory import checks, prompt
from factory.adapters import base as adapters
from factory.automerge import MergeDecision, classify, wait_and_merge
from factory.config import Settings
from factory.engine import Engine
from factory.models import AgentResult, Task, TaskState
from factory.pr import PullRequest
from factory.sources import JsonFileSource, MarkdownDirSource
from factory.state import Store


# --------------------------------------------------------------------------- #
# Unit tests
# --------------------------------------------------------------------------- #
def test_task_slug_is_filesystem_safe():
    t = Task(external_id="gh-42", title="Fix: parser / crash!! on empty input")
    assert t.slug.startswith("gh-42")
    assert "/" not in t.slug and " " not in t.slug and "!" not in t.slug


def test_prompt_includes_task_and_checks():
    t = Task(external_id="x", title="Do the thing", body="details here", labels=["factory"])
    text = prompt.build_prompt(t, checks=["pytest -q"])
    assert "Do the thing" in text
    assert "details here" in text
    assert "pytest -q" in text
    assert "Do NOT run `git commit`" in text


def test_prompt_repair_section_only_on_repair():
    t = Task(external_id="x", title="t")
    assert "REPAIR ATTEMPT" not in prompt.build_prompt(t, checks=[])
    repaired = prompt.build_prompt(t, checks=[], repairs=1, feedback="boom")
    assert "REPAIR ATTEMPT 1" in repaired and "boom" in repaired


def test_store_roundtrip(tmp_path):
    store = Store(tmp_path / "s.db")
    t = Task(external_id="a", title="hello", labels=["x"])
    assert store.upsert(t) is True
    assert store.upsert(t) is False  # dedupe
    t.state = TaskState.PR_OPEN
    t.pr_url = "http://pr"
    store.save(t)
    got = store.get("a")
    assert got.state is TaskState.PR_OPEN
    assert got.pr_url == "http://pr"
    assert store.counts() == {"pr_open": 1}
    store.close()


def test_json_source(tmp_path):
    f = tmp_path / "tasks.json"
    f.write_text('[{"id": "1", "title": "T", "labels": ["factory"]}]')
    tasks = JsonFileSource(f).fetch()
    assert tasks[0].external_id == "1" and tasks[0].labels == ["factory"]


def test_markdown_source(tmp_path):
    d = tmp_path / "tasks"
    d.mkdir()
    (d / "abc.md").write_text("# Real Title\n\nbody line\n")
    tasks = MarkdownDirSource(d).fetch()
    assert tasks[0].title == "Real Title"
    assert "body line" in tasks[0].body


def test_detect_checks_node(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"lint": "x", "test": "y"}}')
    names = [n for n, _ in checks.detect_checks(tmp_path)]
    assert "npm-lint" in names and "npm-test" in names


def test_detect_checks_override(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_CHECKS", "echo a; echo b")
    got = checks.detect_checks(tmp_path)
    assert [c for _, c in got] == ["echo a", "echo b"]


# --------------------------------------------------------------------------- #
# End-to-end engine test with a fake agent against a real temp git repo
# --------------------------------------------------------------------------- #
@adapters.register("fake")
class _FakeAdapter(adapters.AgentAdapter):
    name = "fake"

    def run(self, task: Task, worktree: Path, prompt: str) -> AgentResult:
        (worktree / "generated.txt").write_text("hello from the agent\n")
        return AgentResult(ok=True, summary="SUMMARY: wrote generated.txt")


def _init_repo(tmp_path: Path) -> tuple[Path, Path]:
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
    return remote, seed


def _git(args: list[str]) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True)


def test_engine_ships_verified_change(tmp_path, monkeypatch):
    remote, seed = _init_repo(tmp_path)
    monkeypatch.setenv("FACTORY_CHECKS", "test -f generated.txt")  # passes only after agent writes

    settings = Settings(
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
    settings.ensure_dirs()
    store = Store(settings.db_path)
    task = Task(external_id="e2e-1", title="Generate a file")
    store.upsert(task)

    # Avoid needing gh auth in the test: stub PR creation.
    monkeypatch.setattr(
        "factory.engine.pr_mod.create_pr",
        lambda **kw: PullRequest(url="https://example.test/pr/1", number=1),
    )

    Engine(settings, store, "fake").process(task)

    assert task.state is TaskState.PR_OPEN, task.detail
    assert task.pr_url == "https://example.test/pr/1"

    # The branch must exist on the remote with the agent's file committed.
    shown = subprocess.run(
        ["git", "-C", str(remote), "show", "factory/e2e-1-generate-a-file:generated.txt"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert shown.returncode == 0 and "hello from the agent" in shown.stdout
    store.close()


def test_engine_blocks_when_checks_fail(tmp_path, monkeypatch):
    _remote, seed = _init_repo(tmp_path)
    monkeypatch.setenv("FACTORY_CHECKS", "false")  # always fails

    settings = Settings(
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
    settings.ensure_dirs()
    store = Store(settings.db_path)
    task = Task(external_id="e2e-2", title="Will fail checks")
    store.upsert(task)

    Engine(settings, store, "fake").process(task)
    assert task.state is TaskState.BLOCKED
    assert task.attempts == 2  # initial + 1 repair
    store.close()


# --------------------------------------------------------------------------- #
# Auto-merge
# --------------------------------------------------------------------------- #
def test_classify_merges_only_when_all_green():
    assert classify(["success", "success"], require_checks=True) is MergeDecision.MERGE
    assert classify(["success", "skipped"], require_checks=True) is MergeDecision.MERGE
    assert classify(["success", "neutral"], require_checks=True) is MergeDecision.MERGE


def test_classify_fails_on_any_failure():
    assert classify(["success", "failure"], require_checks=True) is MergeDecision.FAIL
    assert classify(["cancelled"], require_checks=True) is MergeDecision.FAIL
    assert classify(["timed_out", "success"], require_checks=True) is MergeDecision.FAIL


def test_classify_waits_while_pending_or_unknown():
    assert classify(["success", "in_progress"], require_checks=True) is MergeDecision.WAIT
    assert classify(["queued"], require_checks=True) is MergeDecision.WAIT
    assert classify(["some_new_state"], require_checks=True) is MergeDecision.UNKNOWN


def test_classify_no_checks_fails_closed_unless_relaxed():
    assert classify([], require_checks=True) is MergeDecision.WAIT
    assert classify([], require_checks=False) is MergeDecision.MERGE


def test_wait_and_merge_times_out_without_merging(monkeypatch):
    monkeypatch.setattr("factory.automerge._check_states", lambda *a, **k: ["pending"])
    merged_called = {"n": 0}
    monkeypatch.setattr(
        "factory.automerge._merge",
        lambda *a, **k: merged_called.__setitem__("n", merged_called["n"] + 1),
    )
    outcome = wait_and_merge(
        pr_number=1, repo="o/r", base="main", method="squash",
        timeout=0, poll=0, require_checks=True,
    )
    assert outcome.merged is False
    assert merged_called["n"] == 0
    assert "did not go green" in outcome.detail


def test_wait_and_merge_merges_when_green(monkeypatch):
    monkeypatch.setattr("factory.automerge._check_states", lambda *a, **k: ["success"])
    monkeypatch.setattr(
        "factory.automerge._merge",
        lambda *a, **k: type("O", (), {"merged": True, "detail": "merged via gh (squash)"})(),
    )
    outcome = wait_and_merge(
        pr_number=7, repo="o/r", base="main", method="squash",
        timeout=30, poll=0, require_checks=True,
    )
    assert outcome.merged is True


def _auto_merge_settings(tmp_path, seed) -> Settings:
    return Settings(
        repo=seed,
        remote="origin",
        base_branch="main",
        work_root=tmp_path / "work",
        db_path=tmp_path / "work" / "state.db",
        branch_prefix="factory/",
        git_author_name="factory",
        git_author_email="f@f",
        max_repairs=0,
        task_timeout_seconds=120,
        agent_timeout_seconds=120,
        auto_merge=True,
        merge_method="squash",
        ci_timeout_seconds=30,
        ci_poll_seconds=0,
    )


def test_engine_marks_merged_when_ci_green(tmp_path, monkeypatch):
    _remote, seed = _init_repo(tmp_path)
    monkeypatch.setenv("FACTORY_CHECKS", "test -f generated.txt")
    monkeypatch.setenv("FACTORY_GITHUB_REPO", "owner/name")
    monkeypatch.setattr(
        "factory.engine.pr_mod.create_pr",
        lambda **kw: PullRequest(url="https://example.test/pr/9", number=9),
    )
    monkeypatch.setattr(
        "factory.engine.automerge.wait_and_merge",
        lambda **kw: type("O", (), {"merged": True, "detail": "merged via gh (squash)"})(),
    )

    settings = _auto_merge_settings(tmp_path, seed)
    settings.ensure_dirs()
    store = Store(settings.db_path)
    task = Task(external_id="am-1", title="Auto merge me")
    store.upsert(task)

    Engine(settings, store, "fake").process(task)
    assert task.state is TaskState.MERGED
    assert task.merged is True
    store.close()


def test_engine_stays_open_when_ci_not_green(tmp_path, monkeypatch):
    _remote, seed = _init_repo(tmp_path)
    monkeypatch.setenv("FACTORY_CHECKS", "test -f generated.txt")
    monkeypatch.setenv("FACTORY_GITHUB_REPO", "owner/name")
    monkeypatch.setattr(
        "factory.engine.pr_mod.create_pr",
        lambda **kw: PullRequest(url="https://example.test/pr/10", number=10),
    )
    monkeypatch.setattr(
        "factory.engine.automerge.wait_and_merge",
        lambda **kw: type("O", (), {"merged": False, "detail": "CI failed: ['failure']"})(),
    )

    settings = _auto_merge_settings(tmp_path, seed)
    settings.ensure_dirs()
    store = Store(settings.db_path)
    task = Task(external_id="am-2", title="Do not merge me")
    store.upsert(task)

    Engine(settings, store, "fake").process(task)
    assert task.state is TaskState.PR_OPEN
    assert task.merged is False
    assert "auto-merge deferred" in task.detail
    store.close()
