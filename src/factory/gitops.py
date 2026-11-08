"""Git operations used by the factory engine.

Every mutation happens in an isolated worktree; the engine alone commits,
pushes, and opens the PR. This keeps concurrent tasks from stepping on the
primary checkout.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .config import Settings
from .proc import run


class GitError(RuntimeError):
    pass


def _git(settings: Settings, args: list[str], *, cwd: Path | None = None) -> str:
    code, out = run(["git", *args], cwd=cwd or settings.repo, timeout=300)
    if code != 0:
        raise GitError(f"git {' '.join(args)} failed ({code}):\n{out}")
    return out


def ensure_repo(settings: Settings) -> None:
    """Verify the target is a git repo and fetch the latest base branch."""
    if not (settings.repo / ".git").exists():
        raise GitError(f"{settings.repo} is not a git repository")
    _git(settings, ["fetch", settings.remote, settings.base_branch, "--prune"])


def prepare_worktree(settings: Settings, branch: str) -> Path:
    """Create (or refresh) a worktree at <work_root>/wt/<branch>."""
    worktree = settings.work_root / "wt" / branch.replace("/", "_")
    base_ref = f"{settings.remote}/{settings.base_branch}"

    if worktree.exists():
        remove_worktree(settings, worktree)

    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git(settings, ["worktree", "add", "-B", branch, str(worktree), base_ref])
    return worktree


def remove_worktree(settings: Settings, worktree: Path) -> None:
    run(["git", "worktree", "remove", "--force", str(worktree)], cwd=settings.repo, timeout=120)
    if worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)


def changed_files(worktree: Path) -> list[str]:
    code, out = run(["git", "status", "--porcelain"], cwd=worktree, timeout=60)
    if code != 0:
        return []
    files = []
    for line in out.splitlines():
        if len(line) > 3:
            files.append(line[3:].strip())
    return files


def has_changes(worktree: Path) -> bool:
    return bool(changed_files(worktree))


def discard_changes(worktree: Path) -> None:
    """Reset the worktree to HEAD and drop untracked files.

    Used after the read-only spec pass so the coding stage starts from a clean
    tree even if the architect agent left files behind.
    """
    run(["git", "reset", "--hard", "HEAD"], cwd=worktree, timeout=120)
    run(["git", "clean", "-fd"], cwd=worktree, timeout=120)


def commit_all(settings: Settings, worktree: Path, message: str) -> str:
    _git(settings, ["add", "-A"], cwd=worktree)
    code, out = run(
        [
            "git",
            "-c",
            f"user.name={settings.git_author_name}",
            "-c",
            f"user.email={settings.git_author_email}",
            "commit",
            "-m",
            message,
        ],
        cwd=worktree,
        timeout=120,
    )
    if code != 0:
        raise GitError(f"git commit failed ({code}):\n{out}")
    code, sha = run(["git", "rev-parse", "HEAD"], cwd=worktree, timeout=30)
    return sha.strip()


def push(settings: Settings, worktree: Path, branch: str) -> None:
    _git(settings, ["push", "-u", settings.remote, branch, "--force-with-lease"], cwd=worktree)


def diff_stat(worktree: Path) -> str:
    code, out = run(["git", "diff", "--stat", "HEAD"], cwd=worktree, timeout=60)
    return out if code == 0 else ""
