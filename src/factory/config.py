"""Runtime configuration, resolved from environment variables with defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    """Raised when the environment cannot produce a usable configuration."""


def _env(name: str, default: str | None = None, *, required: bool = False) -> str:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        # CI passes "" for undeclared vars; treat blank like unset so a default
        # (branch name, merge method, ...) is not silently erased.
        if required:
            raise ConfigError(f"missing required environment variable: {name}")
        return default or ""
    return raw


def int_env(name: str, default: int) -> int:
    """Read an integer env var, tolerating an unset OR empty value.

    CI systems (GitHub Actions) pass ``""`` for an undeclared ``vars.*`` entry,
    which ``int("")`` rejects; treat blank the same as unset so a missing optional
    variable never crashes a run.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


_int_env = int_env  # backwards-compatible private alias


def str_env(name: str, default: str) -> str:
    """Read a string env var, treating an unset OR empty value as the default.

    Same rationale as :func:`int_env`: CI passes ``""`` for undeclared vars, and a
    blank must fall back to the default rather than erase it (e.g. the Sentry base
    URL or query).
    """
    raw = os.environ.get(name)
    return default if raw is None or not raw.strip() else raw


def _bool_env(name: str, default: bool) -> bool:
    """Read a boolean env var, treating an unset OR empty value as the default.

    CI passes ``""`` for undeclared ``vars.*``; blank must not silently flip a
    default-on flag (e.g. the spec stage) to off.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
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
    # Spec stage: an architect pass (read-only) runs before coding and its plan
    # is handed to the coding agent. ON by default; disable with FACTORY_SPEC_STAGE=false.
    spec_stage: bool = True

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
            spec_stage=_bool_env("FACTORY_SPEC_STAGE", True),
        )

    def ensure_dirs(self) -> None:
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
