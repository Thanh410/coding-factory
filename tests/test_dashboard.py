"""Tests for the pass-rate dashboard (history record + HTML render)."""

from __future__ import annotations

import json

from factory import dashboard as dash


def _report(total: int, passed: int, ids: list[tuple[str, bool]] | None = None) -> dict:
    cases = [{"id": cid, "passed": ok} for cid, ok in (ids or [])]
    return {
        "total": total,
        "passed": passed,
        "pass_rate": passed / total if total else 0.0,
        "cases": cases,
    }


def test_load_history_missing_file_is_empty(tmp_path):
    assert dash.load_history(tmp_path / "nope.json") == []


def test_append_and_load_roundtrip(tmp_path):
    path = tmp_path / "history.json"
    dash.append_history(path, dash.run_record(_report(4, 3), backend="llm", when=0))
    dash.append_history(path, dash.run_record(_report(4, 4), backend="llm", when=3600))
    runs = dash.load_history(path)
    assert len(runs) == 2
    assert runs[0]["pass_rate"] == 0.75
    assert runs[1]["backend"] == "llm"
    assert runs[1]["timestamp"].endswith("Z")


def test_run_record_shapes_cases():
    rec = dash.run_record(_report(2, 1, [("add-file", True), ("fix-bug", False)]))
    assert rec["total"] == 2 and rec["passed"] == 1
    assert rec["cases"] == [
        {"id": "add-file", "passed": True},
        {"id": "fix-bug", "passed": False},
    ]


def test_load_history_accepts_wrapped_object(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"runs": [{"pass_rate": 1.0}]}))
    assert dash.load_history(path) == [{"pass_rate": 1.0}]


def test_render_dashboard_contains_key_facts():
    runs = [
        dash.run_record(_report(3, 2, [("a", True), ("b", True), ("c", False)]), backend="llm"),
        dash.run_record(_report(3, 3, [("a", True), ("b", True), ("c", True)]), backend="llm"),
    ]
    html = dash.render_dashboard(runs, title="My dashboard")
    assert "<!doctype html>" in html
    assert "My dashboard" in html
    assert "100%" in html  # latest pass-rate
    assert "+33% vs previous" in html  # 2/3 -> 3/3
    assert "<svg" in html and "polyline" in html
    assert "<code>c</code>" in html
    assert "PASS" in html


def test_render_dashboard_handles_empty_history():
    html = dash.render_dashboard([])
    assert "No runs recorded yet." in html
    assert "0%" in html


def test_render_dashboard_escapes_title():
    html = dash.render_dashboard([], title="<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_cli_eval_record_then_dashboard(tmp_path, capsys):
    from factory import cli

    suite = tmp_path / "suite.json"
    suite.write_text(json.dumps([{
        "id": "cli-case",
        "title": "Create a module file",
        "checks": "test -f created.py",
        "expect": {"state": "pr_open"},
    }]))
    history = tmp_path / "history.json"
    out = tmp_path / "dashboard" / "index.html"

    rc = cli.main([
        "eval", "--backend", "eval_fake", "--suite", str(suite),
        "--record", "--history", str(history),
    ])
    assert rc == 0
    assert history.exists()

    rc = cli.main(["dashboard", "--history", str(history), "--out", str(out)])
    assert rc == 0
    assert out.exists()
    assert "pass-rate" in out.read_text().lower() or "PASS" in out.read_text()
    assert "wrote" in capsys.readouterr().out


def test_cli_dashboard_without_history(tmp_path, capsys):
    from factory import cli

    rc = cli.main([
        "dashboard", "--history", str(tmp_path / "missing.json"),
        "--out", str(tmp_path / "out.html"),
    ])
    assert rc == 2
    assert "no runs" in capsys.readouterr().out
