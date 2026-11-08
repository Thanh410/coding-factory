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

_SPEC_SYSTEM = """\
You are an autonomous software architect working inside a git worktree. Your job
is to PLAN, not to implement. Read the code that owns the behavior, then produce a
concrete implementation plan for the task below.

Rules:
- Do NOT modify, create, or delete any file. This is a read-only reconnaissance pass.
- Identify the single owning file per concern; name the exact files to change.
- Reuse existing helpers, clients, and conventions; call out anything new.
- Define the interfaces (types, props, API shape) and the test seams.
- State risks, migrations, and what is explicitly out of scope.
- If the task is ambiguous, say so and list the open questions instead of guessing.
- End your final message with a section titled "PLAN:" containing the plan as
  short bullet points (files to change, interfaces, test plan, risks).
"""


def build_spec_prompt(task: Task, *, checks: list[str]) -> str:
    """Compose the read-only planning prompt for the spec stage (architect)."""
    parts = [_SPEC_SYSTEM, "\n# TASK", f"Title: {task.title}"]
    if task.external_id:
        parts.append(f"Reference: {task.external_id}")
    if task.body.strip():
        parts.append("\nDescription:\n" + task.body.strip())
    if task.labels:
        parts.append("\nLabels: " + ", ".join(task.labels))
    if checks:
        parts.append("\n# CHECKS THE IMPLEMENTATION MUST PASS")
        parts.extend(f"- {c}" for c in checks)
    return "\n".join(parts) + "\n"


def build_prompt(
    task: Task,
    *,
    checks: list[str],
    spec: str = "",
    repairs: int = 0,
    feedback: str = "",
) -> str:
    """Compose the full prompt handed to the agent for one attempt."""
    parts = [_SYSTEM, "\n# TASK", f"Title: {task.title}"]
    if task.external_id:
        parts.append(f"Reference: {task.external_id}")
    if task.body.strip():
        parts.append("\nDescription:\n" + task.body.strip())
    if task.labels:
        parts.append("\nLabels: " + ", ".join(task.labels))

    if spec.strip():
        parts.append(
            "\n# PLAN (from the spec stage)\n"
            "Follow this plan; deviate only if the code proves it wrong, and say why.\n\n"
            f"{spec.strip()}"
        )

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
