"""Tests for the production monitors (Sentry + uptime -> GitHub issues).

A local HTTP server stands in for both the Sentry API and the GitHub API, so the
real request/parse/dedup code path is exercised with no network and no mocks of
our own functions.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from factory import monitor
from factory.monitor import MonitorConfig


class _Server:
    """Serves scripted JSON and records requests."""

    def __init__(self, routes: dict[str, tuple[int, object]] | None = None) -> None:
        self.routes = routes or {}
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self, method: str):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw.decode() or "null") if raw else None
                outer.requests.append(
                    {"method": method, "path": self.path, "body": body,
                     "headers": dict(self.headers)}
                )
                key = self.path.split("?")[0]
                # Routes may be qualified by method ("POST /repos/o/r/issues")
                # or plain path; the method-qualified key wins.
                status, payload = outer.routes.get(
                    f"{method} {key}",
                    outer.routes.get(key, (404, {"error": "not found"})),
                )
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def _cfg(server: _Server, **over) -> MonitorConfig:
    base = dict(
        repo="o/r",
        token="gh-token",
        label="factory",
        sentry_base=server.base,
        sentry_token="sentry-token",
        sentry_org="acme",
        sentry_project="web",
        sentry_query="is:unresolved",
        sentry_period="24h",
        sentry_limit=10,
        uptime_url="",
        uptime_expect=200,
        uptime_timeout=5,
        api_base=server.base,
    )
    base.update(over)
    return MonitorConfig(**base)


_SENTRY_ISSUE = {
    "id": "12345",
    "title": "TypeError: cannot read property 'x' of undefined",
    "culprit": "app/handler.py in handle",
    "count": "42",
    "userCount": 7,
    "level": "error",
    "permalink": "https://sentry.example/issues/12345/",
    "firstSeen": "2026-11-01T00:00:00Z",
    "lastSeen": "2026-11-07T00:00:00Z",
}


def test_sentry_disabled_without_credentials():
    cfg = MonitorConfig.from_env()
    assert cfg.sentry_enabled is False
    assert monitor.sentry_issues(cfg) == []


def test_sentry_issues_shape_and_marker():
    with _Server({"/api/0/projects/acme/web/issues/": (200, [_SENTRY_ISSUE])}) as server:
        cfg = _cfg(server)
        (issue,) = monitor.sentry_issues(cfg)
    assert issue.key == "sentry:12345"
    assert issue.title.startswith("[sentry]")
    assert "42" in issue.body and "7" in issue.body
    assert issue.marker() in issue.body
    assert issue.labels == ["factory"]
    # The request carried the bearer token.
    assert server.requests[0]["headers"]["Authorization"] == "Bearer sentry-token"


def test_sentry_api_error_raises():
    with _Server({"/api/0/projects/acme/web/issues/": (403, {"detail": "nope"})}) as server:
        with pytest.raises(RuntimeError, match="Sentry API error 403"):
            monitor.sentry_issues(_cfg(server))


def test_uptime_ok_returns_none():
    with _Server({"/health": (200, "ok")}) as server:
        cfg = _cfg(server, uptime_url=f"{server.base}/health", uptime_expect=200)
        assert monitor.uptime_issue(cfg) is None


def test_uptime_down_returns_issue():
    with _Server({"/health": (503, "down")}) as server:
        cfg = _cfg(server, uptime_url=f"{server.base}/health", uptime_expect=200)
        issue = monitor.uptime_issue(cfg)
    assert issue is not None
    assert issue.key == f"uptime:{server.base}/health"
    assert "503" in issue.body
    assert issue.marker() in issue.body


def test_existing_keys_parses_markers_and_skips_prs():
    open_issues = [
        {"number": 1, "body": "text\n<!-- factory-monitor:sentry:1 -->\nmore"},
        {"number": 2, "body": "no marker here"},
        {"number": 3, "body": "<!-- factory-monitor:uptime:http://x -->",
         "pull_request": {"url": "..."}},
    ]
    with _Server({"/repos/o/r/issues": (200, open_issues)}) as server:
        keys = monitor.existing_keys(_cfg(server))
    assert keys == {"sentry:1"}


def test_create_issue_posts_title_body_labels():
    with _Server({"/repos/o/r/issues": (201, {"html_url": "https://gh/issues/9"})}) as server:
        cfg = _cfg(server)
        issue = monitor.MonitorIssue(
            source="sentry", key="sentry:9", title="t", body="b", labels=["factory"]
        )
        url = monitor.create_issue(cfg, issue)
    assert url == "https://gh/issues/9"
    sent = server.requests[0]["body"]
    assert sent["title"] == "t" and sent["labels"] == ["factory"]


def test_run_monitor_dedups_existing_issues():
    sentry = [_SENTRY_ISSUE]
    existing = [{"number": 5, "body": "<!-- factory-monitor:sentry:12345 -->"}]
    routes = {
        "/api/0/projects/acme/web/issues/": (200, sentry),
        "/repos/o/r/issues": (200, existing),
    }
    with _Server(routes) as server:
        cfg = _cfg(server)
        created = monitor.run_monitor(cfg)
    assert created == []  # the only found issue is already open


def test_run_monitor_creates_new_issue():
    routes = {
        "/api/0/projects/acme/web/issues/": (200, [_SENTRY_ISSUE]),
        "GET /repos/o/r/issues": (200, []),
        "POST /repos/o/r/issues": (201, {"html_url": "https://gh/issues/1"}),
    }
    with _Server(routes) as server:
        cfg = _cfg(server)
        created = monitor.run_monitor(cfg)
    assert created == ["https://gh/issues/1"]


def test_run_monitor_dry_run_does_not_post():
    routes = {
        "/api/0/projects/acme/web/issues/": (200, [_SENTRY_ISSUE]),
        "/repos/o/r/issues": (200, []),
    }
    with _Server(routes) as server:
        cfg = _cfg(server)
        created = monitor.run_monitor(cfg, dry_run=True)
    assert created and created[0].startswith("(dry-run)")
    # Only the two GETs happened; no POST.
    assert all(r["method"] == "GET" for r in server.requests)


def test_run_monitor_reports_nothing_when_healthy():
    with _Server({"/health": (200, "ok")}) as server:
        cfg = _cfg(server, sentry_token="", sentry_org="", sentry_project="",
                   uptime_url=f"{server.base}/health")
        assert monitor.run_monitor(cfg) == []


def test_cli_monitor_unconfigured(monkeypatch, capsys):
    from factory import cli

    for name in ("SENTRY_AUTH_TOKEN", "SENTRY_ORG", "SENTRY_PROJECT", "UPTIME_URL"):
        monkeypatch.delenv(name, raising=False)
    rc = cli.main(["monitor"])
    assert rc == 2
    assert "no monitors configured" in capsys.readouterr().out


def test_cli_monitor_dry_run(monkeypatch, capsys):
    from factory import cli

    with _Server({
        "/api/0/projects/acme/web/issues/": (200, [_SENTRY_ISSUE]),
        "/repos/o/r/issues": (200, []),
    }) as server:
        monkeypatch.setenv("FACTORY_GITHUB_REPO", "o/r")
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        monkeypatch.setenv("GITHUB_API_URL", server.base)
        monkeypatch.setenv("SENTRY_AUTH_TOKEN", "sentry-token")
        monkeypatch.setenv("SENTRY_ORG", "acme")
        monkeypatch.setenv("SENTRY_PROJECT", "web")
        monkeypatch.setenv("SENTRY_BASE_URL", server.base)
        monkeypatch.delenv("UPTIME_URL", raising=False)
        rc = cli.main(["monitor", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "(dry-run)" in out
