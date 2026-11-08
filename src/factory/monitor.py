"""Production monitors that feed the factory: Sentry errors and uptime probes.

Each monitor turns an external signal into a GitHub issue carrying the factory
trigger label, so the pipeline picks it up as a task and opens a PR. That closes
the loop: production error -> issue -> fix -> PR -> deploy.

Only the standard library is used. Dedup is by a marker embedded in the issue
body, so a recurring error or a flapping endpoint does not open a new issue every
run.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

_MARKER = "<!-- factory-monitor:{key} -->"
_MARKER_RE = re.compile(r"factory-monitor:(\S+?)\s*-->")
_DEFAULT_API = "https://api.github.com"


@dataclass
class MonitorIssue:
    """A GitHub issue the monitor wants to exist."""

    source: str  # "sentry" | "uptime"
    key: str  # stable dedup key, e.g. "sentry:12345"
    title: str
    body: str
    labels: list[str] = field(default_factory=list)

    def marker(self) -> str:
        return _MARKER.format(key=self.key)


@dataclass
class MonitorConfig:
    """Resolved monitor configuration from the environment."""

    repo: str  # "owner/name"
    token: str
    label: str
    sentry_base: str
    sentry_token: str
    sentry_org: str
    sentry_project: str
    sentry_query: str
    sentry_period: str
    sentry_limit: int
    uptime_url: str
    uptime_expect: int
    uptime_timeout: int
    api_base: str = _DEFAULT_API

    @classmethod
    def from_env(cls) -> MonitorConfig:
        return cls(
            repo=os.environ.get("FACTORY_GITHUB_REPO", ""),
            token=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", ""),
            label=os.environ.get("FACTORY_MONITOR_LABEL", "factory"),
            sentry_base=os.environ.get("SENTRY_BASE_URL", "https://sentry.io").rstrip("/"),
            sentry_token=os.environ.get("SENTRY_AUTH_TOKEN", ""),
            sentry_org=os.environ.get("SENTRY_ORG", ""),
            sentry_project=os.environ.get("SENTRY_PROJECT", ""),
            sentry_query=os.environ.get("SENTRY_QUERY", "is:unresolved"),
            sentry_period=os.environ.get("SENTRY_STATS_PERIOD", "24h"),
            sentry_limit=int(os.environ.get("SENTRY_LIMIT", "10")),
            uptime_url=os.environ.get("UPTIME_URL", ""),
            uptime_expect=int(os.environ.get("UPTIME_EXPECT_STATUS", "200")),
            uptime_timeout=int(os.environ.get("UPTIME_TIMEOUT", "10")),
            api_base=os.environ.get("GITHUB_API_URL", _DEFAULT_API).rstrip("/"),
        )

    @property
    def sentry_enabled(self) -> bool:
        return bool(self.sentry_token and self.sentry_org and self.sentry_project)

    @property
    def uptime_enabled(self) -> bool:
        return bool(self.uptime_url)


# --------------------------------------------------------------------------- #
# HTTP helper
# --------------------------------------------------------------------------- #
def _http(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict | None = None,
    timeout: int = 30,
) -> tuple[int, str]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        return 0, f"[network error: {exc.reason}]"


# --------------------------------------------------------------------------- #
# Sentry
# --------------------------------------------------------------------------- #
def sentry_issues(cfg: MonitorConfig) -> list[MonitorIssue]:
    """Fetch unresolved Sentry issues and shape them into GitHub issues."""
    if not cfg.sentry_enabled:
        return []
    params = urllib.parse.urlencode(
        {"query": cfg.sentry_query, "statsPeriod": cfg.sentry_period, "limit": cfg.sentry_limit}
    )
    url = f"{cfg.sentry_base}/api/0/projects/{cfg.sentry_org}/{cfg.sentry_project}/issues/?{params}"
    code, body = _http(url, headers={"Authorization": f"Bearer {cfg.sentry_token}"})
    if code != 200:
        raise RuntimeError(f"Sentry API error {code}: {body[:300]}")
    issues = []
    for item in json.loads(body):
        issues.append(_sentry_to_issue(item, cfg))
    return issues


def _sentry_to_issue(item: dict, cfg: MonitorConfig) -> MonitorIssue:
    issue_id = str(item.get("id", ""))
    title = item.get("title") or item.get("culprit") or "Sentry error"
    culprit = item.get("culprit") or ""
    count = item.get("count", "?")
    users = item.get("userCount", "?")
    level = item.get("level") or "error"
    permalink = item.get("permalink") or ""
    first_seen = item.get("firstSeen") or ""
    last_seen = item.get("lastSeen") or ""
    body = "\n".join(
        [
            f"Automated issue from Sentry ({level}).",
            "",
            f"- Sentry issue: `{issue_id}`",
            f"- Events: {count} | Users affected: {users}",
            f"- First seen: {first_seen}",
            f"- Last seen: {last_seen}",
            f"- Link: {permalink}",
            "",
            "## Culprit",
            culprit or "_unknown_",
            "",
            "## What to do",
            "Investigate the error, fix the root cause, and add a regression test.",
            "The factory will pick this up and open a PR for review.",
            "",
            _MARKER.format(key=f"sentry:{issue_id}"),
            "",
            "_Opened by the coding factory monitor._",
        ]
    )
    return MonitorIssue(
        source="sentry",
        key=f"sentry:{issue_id}",
        title=f"[sentry] {title}",
        body=body,
        labels=[cfg.label],
    )


# --------------------------------------------------------------------------- #
# Uptime
# --------------------------------------------------------------------------- #
def uptime_issue(cfg: MonitorConfig) -> MonitorIssue | None:
    """Return an issue when the endpoint is unhealthy, else None."""
    if not cfg.uptime_enabled:
        return None
    code, _ = _http(cfg.uptime_url, timeout=cfg.uptime_timeout)
    if code == cfg.uptime_expect:
        return None
    host = urllib.parse.urlparse(cfg.uptime_url).netloc or cfg.uptime_url
    body = "\n".join(
        [
            f"Automated issue: `{cfg.uptime_url}` returned HTTP {code} "
            f"(expected {cfg.uptime_expect}).",
            "",
            f"- Endpoint: {cfg.uptime_url}",
            f"- Observed status: {code}",
            f"- Expected status: {cfg.uptime_expect}",
            "",
            "## What to do",
            "Check whether the service is down, then fix or roll back. If it is a",
            "transient blip, close this issue once the endpoint recovers.",
            "",
            _MARKER.format(key=f"uptime:{cfg.uptime_url}"),
            "",
            "_Opened by the coding factory monitor._",
        ]
    )
    return MonitorIssue(
        source="uptime",
        key=f"uptime:{cfg.uptime_url}",
        title=f"[uptime] {host} is down (HTTP {code})",
        body=body,
        labels=[cfg.label],
    )


# --------------------------------------------------------------------------- #
# GitHub issues
# --------------------------------------------------------------------------- #
def _gh_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }


def existing_keys(cfg: MonitorConfig) -> set[str]:
    """Dedup keys already present on open issues carrying the label."""
    if not (cfg.repo and cfg.token):
        return set()
    url = (
        f"{cfg.api_base}/repos/{cfg.repo}/issues"
        f"?state=open&labels={urllib.parse.quote(cfg.label)}&per_page=100"
    )
    code, body = _http(url, headers=_gh_headers(cfg.token))
    if code != 200:
        raise RuntimeError(f"GitHub API error {code} listing issues: {body[:300]}")
    keys: set[str] = set()
    for issue in json.loads(body):
        if "pull_request" in issue:
            continue
        for match in _MARKER_RE.finditer(issue.get("body") or ""):
            keys.add(match.group(1))
    return keys


def create_issue(cfg: MonitorConfig, issue: MonitorIssue) -> str | None:
    """Create the GitHub issue. Returns its URL, or None when not configured."""
    if not (cfg.repo and cfg.token):
        return None
    url = f"{cfg.api_base}/repos/{cfg.repo}/issues"
    payload = {"title": issue.title, "body": issue.body, "labels": issue.labels}
    code, body = _http(
        url, method="POST", headers=_gh_headers(cfg.token), payload=payload, timeout=60
    )
    if code not in (200, 201):
        raise RuntimeError(f"GitHub API error {code} creating issue: {body[:300]}")
    return json.loads(body).get("html_url")


def run_monitor(cfg: MonitorConfig, *, dry_run: bool = False) -> list[str]:
    """Collect monitor issues, dedup against open ones, and open what is new."""
    found: list[MonitorIssue] = []
    if cfg.sentry_enabled:
        found += sentry_issues(cfg)
    up = uptime_issue(cfg)
    if up is not None:
        found.append(up)
    if not found:
        return []

    known = existing_keys(cfg)
    created: list[str] = []
    for issue in found:
        if issue.key in known:
            continue
        if dry_run:
            created.append(f"(dry-run) {issue.title}")
            continue
        url = create_issue(cfg, issue)
        if url:
            created.append(url)
        known.add(issue.key)
    return created
