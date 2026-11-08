"""Tests for the eval harness: golden tasks -> pass-rate.

These exercise the real engine against throwaway git repos with a fake adapter,
so no network, no GitHub auth, and no real LLM is involved.
"""

from __future__ import annotations

import json
from pathlib import Path

from factory import eval as eval_mod
from factory.adapters import base as adapters
from factory.models import AgentResult, Task


@adapters.register("eval_fake")
class _EvalFakeAdapter(adapters.AgentAdapter):
    """Writes ``created.py`` (satisfies add-file) and never touches seed files."""

    name = "eval_fake"

    def run(self, task: Task, worktree: Path, prompt: str) -> AgentResult:
        (worktree / "created.py").write_text("def answer():\n    return 42\n")
        return AgentResult(ok=True, summary="SUMMARY: wrote created.py")


@adapters.register("eval_noop")
class _EvalNoopAdapter(adapters.AgentAdapter):
    """Makes no changes, so the engine blocks the task."""

    name = "eval_noop"

    def run(self, task: Task, worktree: Path, prompt: str) -> AgentResult:
        return AgentResult(ok=True, summary="SUMMARY: nothing to do")


def test_load_suite_from_directory(tmp_path):
    (tmp_path / "a.json").write_text('{"id": "a", "title": "A"}')
    (tmp_path / "b.json").write_text('{"id": "b", "title": "B"}')
    cases = eval_mod.load_suite(tmp_path)
    assert [c["id"] for c in cases] == ["a", "b"]


def test_load_suite_from_single_file(tmp_path):
    f = tmp_path / "suite.json"
    f.write_text('[{"id": "x"}, {"id": "y"}]')
    assert [c["id"] for c in eval_mod.load_suite(f)] == ["x", "y"]


def test_load_suite_id_defaults_to_filename(tmp_path):
    (tmp_path / "my-case.json").write_text('{"title": "T"}')
    assert eval_mod.load_suite(tmp_path)[0]["id"] == "my-case"


def test_load_suite_missing_path_raises(tmp_path):
    try:
        eval_mod.load_suite(tmp_path / "nope")
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")


def test_run_suite_passes_when_expectations_met(tmp_path):
    case = {
        "id": "add-file",
        "title": "Create a module file",
        "checks": "test -f created.py",
        "expect": {"state": "pr_open", "files_changed_contains": ["created.py"]},
    }
    result = eval_mod.run_suite([case], "eval_fake", workdir=tmp_path)
    assert result.total == 1
    assert result.passed == 1
    assert result.pass_rate == 1.0
    assert result.cases[0].passed is True
    assert "created.py" in result.cases[0].changed_files


def test_run_suite_fails_on_state_mismatch(tmp_path):
    case = {
        "id": "blocked-expected",
        "title": "No changes",
        "checks": "true",
        "expect": {"state": "blocked"},
    }
    # eval_fake always writes a file -> PR opens -> state != blocked.
    result = eval_mod.run_suite([case], "eval_fake", workdir=tmp_path)
    assert result.passed == 0
    assert any("state" in r for r in result.cases[0].reasons)


def test_run_suite_blocks_when_agent_makes_no_changes(tmp_path):
    case = {
        "id": "noop",
        "title": "Do nothing",
        "checks": "true",
        "expect": {"state": "blocked"},
    }
    result = eval_mod.run_suite([case], "eval_noop", workdir=tmp_path)
    assert result.passed == 1
    assert result.cases[0].state == "blocked"


def test_run_suite_detects_unexpected_file_change(tmp_path):
    case = {
        "id": "excludes",
        "title": "Create a module file",
        "checks": "test -f created.py",
        "expect": {"state": "pr_open", "files_changed_excludes": ["created.py"]},
    }
    result = eval_mod.run_suite([case], "eval_fake", workdir=tmp_path)
    assert result.passed == 0
    assert any("unexpected change" in r for r in result.cases[0].reasons)


def test_format_and_dict_reports(tmp_path):
    case = {"id": "add-file", "title": "t", "checks": "test -f created.py",
            "expect": {"state": "pr_open"}}
    result = eval_mod.run_suite([case], "eval_fake", workdir=tmp_path)
    report = eval_mod.format_report(result)
    assert "[PASS] add-file" in report
    assert "pass-rate: 1/1 (100%)" in report

    data = eval_mod.as_dict(result)
    assert data["passed"] == 1 and data["total"] == 1
    assert data["cases"][0]["id"] == "add-file"
    json.dumps(data)  # must be JSON-serialisable


def test_bundled_suite_loads():
    suite = Path(__file__).resolve().parents[1] / "evals" / "cases"
    cases = eval_mod.load_suite(suite)
    ids = {c["id"] for c in cases}
    assert {"add-file", "fix-bug", "must-block"} <= ids


def test_cli_eval_runs_suite(tmp_path, capsys):
    from factory import cli

    suite = tmp_path / "suite.json"
    suite.write_text(json.dumps([{
        "id": "cli-case",
        "title": "Create a module file",
        "checks": "test -f created.py",
        "expect": {"state": "pr_open"},
    }]))
    rc = cli.main(["eval", "--backend", "eval_fake", "--suite", str(suite)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "pass-rate: 1/1" in out


def test_cli_eval_min_pass_rate_gate(tmp_path, capsys):
    from factory import cli

    suite = tmp_path / "suite.json"
    suite.write_text(json.dumps([{
        "id": "will-fail",
        "title": "Create a module file",
        "checks": "test -f created.py",
        "expect": {"state": "blocked"},  # eval_fake opens a PR -> fails
    }]))
    rc = cli.main(
        ["eval", "--backend", "eval_fake", "--suite", str(suite), "--min-pass-rate", "0.9"]
    )
    assert rc == 1
    assert "below the required" in capsys.readouterr().out
