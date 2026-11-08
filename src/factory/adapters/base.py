"""Agent adapter interface + a registry so backends are swappable by name."""

from __future__ import annotations

import abc
from pathlib import Path

from ..models import AgentResult, Task

# Registry populated by importing the built-in adapters.
_REGISTRY: dict[str, type[AgentAdapter]] = {}


def register(name: str):
    def _wrap(cls: type[AgentAdapter]) -> type[AgentAdapter]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return _wrap


def available() -> list[str]:
    _load_builtins()
    return sorted(_REGISTRY)


def build(name: str, **kwargs) -> AgentAdapter:
    _load_builtins()
    if name not in _REGISTRY:
        raise KeyError(f"unknown agent backend {name!r}; available: {available()}")
    return _REGISTRY[name](**kwargs)


def _load_builtins() -> None:
    # Import for side effects (registration).
    from . import antigravity, codex, llm  # noqa: F401


class AgentAdapter(abc.ABC):
    """Contract every coding-agent backend must satisfy.

    Implementations receive an already-checked-out worktree and are expected to
    modify files in place. They must never commit, push, or open PRs - the
    factory engine owns all git/remote side effects.
    """

    name: str = "abstract"

    def __init__(self, timeout: int = 1800) -> None:
        self.timeout = timeout

    @abc.abstractmethod
    def run(self, task: Task, worktree: Path, prompt: str) -> AgentResult:
        """Execute the agent against ``worktree`` and return its result."""

    def is_available(self) -> bool:
        """Return True when the backend's CLI/credentials are usable here."""
        return True
