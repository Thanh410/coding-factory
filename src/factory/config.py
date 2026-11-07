"""Runtime configuration, resolved from environment variables with defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    """Raised when the environment cannot produce a usable configuration."""


def _env(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        raise ConfigError(f"missing required environment variable: {name}")
    return value or ""


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Immutable, fully-resolved configuration for one factory run."""

    repo: Path
    remote: str
    base_branch: str
    work_root: Path
    db_path: Path
    branch_prefix: str
    git_author_name: str
    git_author_email: str
    max_repairs: int
    task_timeout_seconds: int
    agent_timeout_seconds: int
    # Auto-merge is OFF by default: merging is destructive and must be opted into.
    auto_merge: bool = False
    merge_method: str = "squash"
    ci_timeout_seconds: int = 1800
    ci_poll_seconds: int = 20
    require_checks: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        repo = Path(_env("FACTORY_REPO", os.getcwd())).expanduser().resolve()
        work_root = Path(_env("FACTORY_WORK_ROOT", str(Path.home() / ".factory"))).expanduser()
        db_path = Path(_env("FACTORY_DB", str(work_root / "state.db"))).expanduser()
        return cls(
            repo=repo,
            remote=_env("FACTORY_REMOTE", "origin"),
            base_branch=_env("FACTORY_BASE_BRANCH", "main"),
            work_root=work_root,
            db_path=db_path,
            branch_prefix=_env("FACTORY_BRANCH_PREFIX", "factory/"),
            git_author_name=_env("FACTORY_GIT_NAME", "openhands-factory"),
            git_author_email=_env("FACTORY_GIT_EMAIL", "factory@users.noreply.github.com"),
            max_repairs=_int_env("FACTORY_MAX_REPAIRS", 2),
            task_timeout_seconds=_int_env("FACTORY_TASK_TIMEOUT", 3600),
            agent_timeout_seconds=_int_env("FACTORY_AGENT_TIMEOUT", 1800),
            auto_merge=_bool_env("FACTORY_AUTO_MERGE", False),
            merge_method=_env("FACTORY_MERGE_METHOD", "squash"),
            ci_timeout_seconds=_int_env("FACTORY_CI_TIMEOUT", 1800),
            ci_poll_seconds=_int_env("FACTORY_CI_POLL", 20),
            require_checks=_bool_env("FACTORY_REQUIRE_CHECKS", True),
        )

    def ensure_dirs(self) -> None:
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
