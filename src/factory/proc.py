"""Subprocess helpers with timeouts, logging, and no shell surprises."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from .models import CheckResult


def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> tuple[int, str]:
    """Run ``args`` capturing combined output. Returns (exit_code, output).

    On timeout the process is killed and the exit code is -1.
    """
    merged_env = {**os.environ, **(env or {})}
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            env=merged_env,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or ""
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        return -1, f"{partial}\n[timeout after {timeout}s]"
    except FileNotFoundError as exc:
        return 127, f"[command not found: {exc}]"


def run_check(name: str, command: str, *, cwd: Path, timeout: int) -> CheckResult:
    """Run a shell check (lint/test/build) and capture the result."""
    start = time.monotonic()
    code, out = run(["/bin/sh", "-c", command], cwd=cwd, timeout=timeout)
    elapsed = time.monotonic() - start
    header = f"$ {command}\n(exit={code}, {elapsed:.1f}s)\n"
    return CheckResult(name=name, command=command, ok=(code == 0), output=header + out)
