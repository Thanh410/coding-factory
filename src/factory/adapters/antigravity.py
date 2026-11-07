"""Google Antigravity adapter.

Antigravity is an agent-first IDE; its stable, automatable surface today is the
editor's task/agent runner invoked headlessly. Because the exact headless
contract may change, this adapter is intentionally thin and fully configurable
via ``FACTORY_ANTIGRAVITY_CMD``:

  export FACTORY_ANTIGRAVITY_CMD="antigravity run --prompt-file -"

The command is executed with the worktree as cwd and the prompt on stdin. If
your Antigravity build exposes a different entrypoint (e.g. an `agy` binary or
a JSON job file), point FACTORY_ANTIGRAVITY_CMD at it; the rest of the pipeline
is unchanged.

Antigravity is a strong *second* backend: run the same task with both and keep
the first result that passes verification (see `scripts/race.sh`).
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

from ..models import AgentResult, Task
from ..proc import run
from .base import AgentAdapter, register


@register("antigravity")
class AntigravityAdapter(AgentAdapter):
    name = "antigravity"

    def is_available(self) -> bool:
        cmd = os.environ.get("FACTORY_ANTIGRAVITY_CMD")
        if not cmd:
            return False
        binary = shlex.split(cmd)[0]
        code, _ = run(["sh", "-c", f"command -v {shlex.quote(binary)}"], timeout=10)
        return code == 0

    def run(self, task: Task, worktree: Path, prompt: str) -> AgentResult:
        raw = os.environ.get("FACTORY_ANTIGRAVITY_CMD")
        if not raw:
            return AgentResult(
                ok=False,
                summary=(
                    "Antigravity backend not configured. Set FACTORY_ANTIGRAVITY_CMD "
                    "to the headless entrypoint of your Antigravity build."
                ),
                exit_code=127,
            )
        args = shlex.split(raw)
        code, out = run(args, cwd=worktree, timeout=self.timeout, stdin=prompt)

        log = worktree.parent / "agent.log"
        log.write_text(out, encoding="utf-8")
        return AgentResult(
            ok=(code == 0),
            summary=_extract_summary(out),
            log_path=str(log),
            exit_code=code,
        )


def _extract_summary(output: str) -> str:
    marker = "SUMMARY:"
    idx = output.rfind(marker)
    if idx == -1:
        return output.strip()[-1000:]
    return output[idx + len(marker):].strip()
