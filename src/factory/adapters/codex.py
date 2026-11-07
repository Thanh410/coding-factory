"""OpenAI Codex CLI adapter.

Runs Codex in non-interactive/headless mode against a worktree. Codex is the
default backend because its CLI is scriptable and stable.

Install:  npm i -g @openai/codex
Auth:     export OPENAI_API_KEY=...   (or `codex login`)
Config:   FACTORY_CODEX_CMD overrides the base command (default: "codex exec").
          FACTORY_CODEX_ARGS appends raw flags.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

from ..models import AgentResult, Task
from ..proc import run
from .base import AgentAdapter, register


@register("codex")
class CodexAdapter(AgentAdapter):
    name = "codex"

    def is_available(self) -> bool:
        code, _ = run(["sh", "-c", "command -v codex"], timeout=10)
        return code == 0

    def run(self, task: Task, worktree: Path, prompt: str) -> AgentResult:
        base = shlex.split(os.environ.get("FACTORY_CODEX_CMD", "codex exec"))
        extra = shlex.split(os.environ.get("FACTORY_CODEX_ARGS", ""))
        # `codex exec` reads the task from stdin and edits the repo in cwd.
        args = [*base, *extra]
        code, out = run(args, cwd=worktree, timeout=self.timeout, stdin=prompt)

        log = worktree.parent / "agent.log"
        log.write_text(out, encoding="utf-8")
        summary = _extract_summary(out)
        return AgentResult(
            ok=(code == 0),
            summary=summary,
            log_path=str(log),
            exit_code=code,
        )


def _extract_summary(output: str) -> str:
    marker = "SUMMARY:"
    idx = output.rfind(marker)
    if idx == -1:
        return output.strip()[-1000:]
    return output[idx + len(marker):].strip()
