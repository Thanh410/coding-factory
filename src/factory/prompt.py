"""Prompt construction for coding agents.

Kept in one place so every backend (Codex, Antigravity, ...) receives the same
contract: implement, run the project's checks, keep the diff focused.
"""

from __future__ import annotations

from .models import Task

_SYSTEM = """\
You are an autonomous senior software engineer working inside a git worktree.
Deliver a complete, working change that satisfies the task below.

Rules:
- Modify files directly in the current working directory. Do not create a new branch.
- Do NOT run `git commit`, `git push`, or open a pull request; the harness does that.
- Keep the diff focused on the task. Do not reformat unrelated code.
- Run the project's linters and tests for the code you touched before finishing.
- If the task is ambiguous or impossible with the available information, stop and
  write a short explanation instead of guessing; leave the worktree unchanged.
- End your final message with a section titled "SUMMARY:" containing 2-4 lines:
  what changed, how you verified it, and any follow-ups.
"""


def build_prompt(task: Task, *, checks: list[str], repairs: int = 0, feedback: str = "") -> str:
    """Compose the full prompt handed to the agent for one attempt."""
    parts = [_SYSTEM, "\n# TASK", f"Title: {task.title}"]
    if task.external_id:
        parts.append(f"Reference: {task.external_id}")
    if task.body.strip():
        parts.append("\nDescription:\n" + task.body.strip())
    if task.labels:
        parts.append("\nLabels: " + ", ".join(task.labels))

    if checks:
        parts.append("\n# REQUIRED CHECKS (must pass)")
        parts.extend(f"- {c}" for c in checks)

    if repairs > 0 and feedback:
        parts.append(
            f"\n# REPAIR ATTEMPT {repairs}\n"
            "A previous attempt failed verification. Fix the root cause of the "
            "failure below, then re-run the checks. Do not restart from scratch.\n\n"
            "Failure output:\n"
            f"{feedback[-4000:]}"
        )

    return "\n".join(parts) + "\n"
