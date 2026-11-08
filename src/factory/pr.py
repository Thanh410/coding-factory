"""Pull-request creation. Prefers the gh CLI, falls back to the GitHub API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from .models import Task
from .proc import run


@dataclass
class PullRequest:
    url: str = ""
    number: int = 0


def create_pr(
    *,
    worktree_path: str,
    base: str,
    branch: str,
    title: str,
    body: str,
) -> PullRequest:
    """Create a PR/MR and return its reference, or an empty one if not configured."""
    code, _ = run(["sh", "-c", "command -v gh"], timeout=10)
    if code == 0:
        return _create_with_gh(worktree_path, base, branch, title, body)
    return _create_with_api(base, branch, title, body)


def _create_with_gh(cwd: str, base: str, branch: str, title: str, body: str) -> PullRequest:
    code, out = run(
        ["gh", "pr", "create", "--base", base, "--head", branch, "--title", title, "--body", body],
        cwd=cwd,
        timeout=120,
    )
    if code != 0:
        raise RuntimeError(f"gh pr create failed ({code}):\n{out}")
    url = out.strip().splitlines()[-1]
    return PullRequest(url=url, number=_number_from_url(url))


def _number_from_url(url: str) -> int:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _create_with_api(base: str, branch: str, title: str, body: str) -> PullRequest:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("FACTORY_GITHUB_REPO")  # "owner/name"
    if not token or not repo:
        return PullRequest()
    url = f"https://api.github.com/repos/{repo}/pulls"
    payload = json.dumps({"title": title, "body": body, "head": branch, "base": base}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            return PullRequest(url=data.get("html_url", ""), number=int(data.get("number", 0)))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub API PR create failed: {exc.code} {exc.read()[:400]!r}") from exc


def pr_body(task: Task, *, checks_summary: str, agent_summary: str, diff_stat: str) -> str:
    lines = [
        f"Automated change for **{task.title}**.",
        "",
        f"- Task ref: `{task.external_id}`",
        f"- Agent backend: `{os.environ.get('FACTORY_BACKEND', 'codex')}`",
        f"- Attempts: {task.attempts}",
        "",
        "## Agent summary",
        agent_summary.strip() or "_none provided_",
        "",
    ]
    if task.spec.strip():
        lines += [
            "## Plan (spec stage)",
            task.spec.strip(),
            "",
        ]
    lines += [
        "## Verification",
        "```",
        checks_summary.strip() or "no checks configured",
        "```",
        "",
        "## Diff",
        "```",
        diff_stat.strip() or "(no diff)",
        "```",
        "",
        "---",
        "_Opened by the 24/7 coding factory. Review before merge; this PR was "
        "produced by an AI agent._",
    ]
    return "\n".join(lines)
