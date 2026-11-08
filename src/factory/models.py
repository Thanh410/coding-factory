"""Core data types shared across the factory."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TaskState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"          # agent could not finish (budget/errors) -> human
    PR_OPEN = "pr_open"
    MERGED = "merged"
    FAILED = "failed"
    DONE = "done"


@dataclass
class Task:
    """A unit of work: one issue/request to implement end to end."""

    external_id: str
    title: str
    body: str = ""
    repo_url: str = ""
    base_branch: str = "main"
    labels: list[str] = field(default_factory=list)
    state: TaskState = TaskState.PENDING
    attempts: int = 0
    branch: str = ""
    pr_url: str = ""
    pr_number: int = 0
    merged: bool = False
    detail: str = ""
    # Plan produced by the spec stage (architect pass); empty when disabled.
    spec: str = ""

    @property
    def slug(self) -> str:
        raw = f"{self.external_id}-{self.title}".lower()
        keep = [c if c.isalnum() else "-" for c in raw]
        slug = "".join(keep).strip("-")
        while "--" in slug:
            slug = slug.replace("--", "-")
        return slug[:60] or "task"


@dataclass
class AgentResult:
    """Outcome of one agent invocation."""

    ok: bool
    summary: str = ""
    log_path: str = ""
    exit_code: int = 0
    changed_files: list[str] = field(default_factory=list)


@dataclass
class CheckResult:
    """Outcome of one verification command."""

    name: str
    command: str
    ok: bool
    output: str = ""
