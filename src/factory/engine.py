"""The factory engine: drives one task from intake to an open (optionally
auto-merged) pull request.

Pipeline:  prepare worktree -> agent run -> verify -> (repair loop) ->
           commit -> push -> open PR -> [wait for CI -> merge] -> record state.
"""

from __future__ import annotations

import logging
import os
import time

from . import automerge, gitops
from . import checks as checks_mod
from . import pr as pr_mod
from .adapters import base as adapters
from .config import Settings
from .models import Task, TaskState
from .prompt import build_prompt
from .state import Store

log = logging.getLogger("factory.engine")


class Engine:
    def __init__(self, settings: Settings, store: Store, backend: str) -> None:
        self.settings = settings
        self.store = store
        self.backend_name = backend
        self.agent = adapters.build(backend, timeout=settings.agent_timeout_seconds)

    # -- public API ---------------------------------------------------------
    def process(self, task: Task) -> Task:
        """Run a single task to a terminal state and persist it."""
        task.state = TaskState.RUNNING
        self.store.save(task)
        start = time.monotonic()
        log.info("start task %s (%s) via %s", task.external_id, task.title, self.backend_name)
        try:
            self._run(task)
        except Exception as exc:
            task.state = TaskState.FAILED
            task.detail = f"{type(exc).__name__}: {exc}"
            log.exception("task %s crashed", task.external_id)
        finally:
            self.store.save(task)
            log.info(
                "task %s -> %s in %.0fs",
                task.external_id,
                task.state.value,
                time.monotonic() - start,
            )
        return task

    # -- internals ----------------------------------------------------------
    def _run(self, task: Task) -> None:
        branch = f"{self.settings.branch_prefix}{task.slug}"
        task.branch = branch

        gitops.ensure_repo(self.settings)
        worktree = gitops.prepare_worktree(self.settings, branch)

        check_list = [cmd for _, cmd in checks_mod.detect_checks(worktree)]
        feedback = ""
        result = None

        for attempt in range(1, self.settings.max_repairs + 2):
            task.attempts = attempt
            prompt = build_prompt(task, checks=check_list, repairs=attempt - 1, feedback=feedback)
            result = self.agent.run(task, worktree, prompt)

            if not result.ok:
                feedback = f"Agent exited {result.exit_code}.\n{result.summary}"
                log.warning("agent attempt %d failed for %s", attempt, task.external_id)
                continue

            if not gitops.has_changes(worktree):
                task.state = TaskState.BLOCKED
                task.detail = "agent made no file changes"
                log.warning("task %s: no changes produced", task.external_id)
                return

            check_results = checks_mod.run_checks(
                worktree, timeout=self.settings.task_timeout_seconds
            )
            if checks_mod.all_passed(check_results):
                return self._ship(task, worktree, result, check_results)

            feedback = checks_mod.failure_report(check_results)
            log.warning("checks failed for %s (attempt %d)", task.external_id, attempt)

        task.state = TaskState.BLOCKED
        task.detail = (
            f"verification failed after {self.settings.max_repairs + 1} attempt(s).\n"
            + (feedback[:2000] if feedback else "no details")
        )

    def _ship(self, task: Task, worktree, result, check_results) -> None:
        diff_stat = gitops.diff_stat(worktree)
        checks_summary = "\n".join(
            f"[{'ok' if r.ok else 'FAIL'}] {r.name}: {r.command}" for r in check_results
        )

        gitops.commit_all(self.settings, worktree, self._commit_message(task))
        gitops.push(self.settings, worktree, task.branch)

        body = pr_mod.pr_body(
            task,
            checks_summary=checks_summary,
            agent_summary=result.summary,
            diff_stat=diff_stat,
        )
        try:
            pr_ref = pr_mod.create_pr(
                worktree_path=str(worktree),
                base=self.settings.base_branch,
                branch=task.branch,
                title=task.title,
                body=body,
            )
            task.pr_url = pr_ref.url
            task.pr_number = pr_ref.number
        except Exception as exc:  # noqa: BLE001 - branch is pushed; record and continue
            task.state = TaskState.BLOCKED
            task.detail = f"pushed branch {task.branch} but PR creation failed: {exc}"
            log.error("PR creation failed for %s: %s", task.external_id, exc)
            return

        task.state = TaskState.PR_OPEN
        task.detail = f"branch {task.branch} verified by {len(check_results)} check(s)"
        log.info("task %s shipped: %s", task.external_id, task.pr_url or task.branch)

        if self.settings.auto_merge:
            self._maybe_auto_merge(task)

    def _maybe_auto_merge(self, task: Task) -> None:
        """Wait for the repo's CI on the PR and merge when it is green."""
        repo = self._github_repo()
        if not repo or not task.pr_number:
            task.detail += "; auto-merge skipped (no GitHub repo/number resolved)"
            log.warning(
                "auto-merge skipped for %s: repo=%r pr=%s",
                task.external_id,
                repo,
                task.pr_number,
            )
            return

        log.info("auto-merge: waiting on CI for PR #%s", task.pr_number)
        outcome = automerge.wait_and_merge(
            pr_number=task.pr_number,
            repo=repo,
            base=self.settings.base_branch,
            method=self.settings.merge_method,
            timeout=self.settings.ci_timeout_seconds,
            poll=self.settings.ci_poll_seconds,
            require_checks=self.settings.require_checks,
        )
        if outcome.merged:
            task.merged = True
            task.state = TaskState.MERGED
            task.detail += f"; auto-merged: {outcome.detail}"
            log.info("task %s auto-merged: %s", task.external_id, outcome.detail)
        else:
            # Stay in PR_OPEN: the PR exists and is correct, CI just did not
            # (yet) allow a merge. A human can take it from here.
            task.detail += f"; auto-merge deferred: {outcome.detail}"
            log.warning("task %s not auto-merged: %s", task.external_id, outcome.detail)

    def _github_repo(self) -> str:
        return os.environ.get("FACTORY_GITHUB_REPO", "").strip()

    def _commit_message(self, task: Task) -> str:
        header = task.title.strip() or f"factory: {task.external_id}"
        body = (
            f"Automated change for task {task.external_id}.\n\n"
            f"Backend: {self.backend_name}\n"
            "Opened by the 24/7 coding factory."
        )
        return f"{header}\n\n{body}"
