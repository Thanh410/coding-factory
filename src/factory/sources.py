"""Task intake sources.

A source turns some external queue (GitHub issues, a JSON file, a directory of
markdown files) into ``Task`` objects. Add new sources by implementing
``TaskSource`` and registering them in ``build_source``.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from .models import Task


class TaskSource:
    def fetch(self) -> list[Task]:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# File-based sources (no credentials; good for cron + git-committed backlogs)
# --------------------------------------------------------------------------- #
class JsonFileSource(TaskSource):
    """Read tasks from a JSON array file.

    Each item: {"id", "title", "body", "labels", "base_branch"}.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def fetch(self) -> list[Task]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        tasks = []
        for item in data:
            tasks.append(
                Task(
                    external_id=str(item["id"]),
                    title=item["title"],
                    body=item.get("body", ""),
                    base_branch=item.get("base_branch", "main"),
                    labels=item.get("labels", []),
                )
            )
        return tasks


class MarkdownDirSource(TaskSource):
    """One task per .md file. Title = first heading; id = filename stem."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def fetch(self) -> list[Task]:
        if not self.directory.exists():
            return []
        tasks = []
        for path in sorted(self.directory.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            title, body = _split_title(text, fallback=path.stem)
            tasks.append(Task(external_id=path.stem, title=title, body=body))
        return tasks


def _split_title(text: str, fallback: str) -> tuple[str, str]:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            return title, "\n".join(lines[i + 1:]).strip()
    return fallback, text.strip()


# --------------------------------------------------------------------------- #
# GitHub issues
# --------------------------------------------------------------------------- #
class GitHubIssuesSource(TaskSource):
    """Pull open issues carrying a trigger label from a GitHub repo."""

    def __init__(self, repo: str, label: str, token: str) -> None:
        self.repo = repo
        self.label = label
        self.token = token

    def fetch(self) -> list[Task]:
        if not self.token:
            raise RuntimeError("GITHUB_TOKEN is required for the github source")
        url = (
            f"https://api.github.com/repos/{self.repo}/issues"
            f"?state=open&labels={self.label}&per_page=50"
        )
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        tasks = []
        for issue in data:
            if "pull_request" in issue:  # skip PRs
                continue
            labels = [lbl["name"] for lbl in issue.get("labels", [])]
            tasks.append(
                Task(
                    external_id=f"gh-{issue['number']}",
                    title=issue["title"],
                    body=issue.get("body") or "",
                    labels=labels,
                )
            )
        return tasks


# --------------------------------------------------------------------------- #
def build_source(kind: str | None = None) -> TaskSource:
    kind = (kind or os.environ.get("FACTORY_SOURCE", "json")).lower()
    if kind == "json":
        return JsonFileSource(Path(os.environ.get("FACTORY_TASKS_FILE", "tasks.json")))
    if kind == "markdown":
        return MarkdownDirSource(Path(os.environ.get("FACTORY_TASKS_DIR", "tasks")))
    if kind == "github":
        return GitHubIssuesSource(
            repo=os.environ["FACTORY_GITHUB_REPO"],
            label=os.environ.get("FACTORY_TRIGGER_LABEL", "factory"),
            token=os.environ.get("GITHUB_TOKEN", ""),
        )
    raise ValueError(f"unknown source kind: {kind}")
