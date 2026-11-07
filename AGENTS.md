# AGENTS.md - repository knowledge for coding agents

## What this repo is
`coding-factory` is a dependency-free Python (3.11+) pipeline that turns tasks
(GitHub issues / JSON / markdown) into verified pull requests by running a coding
agent (OpenAI Codex or Google Antigravity) inside an isolated git worktree.

## Golden rules for agents working in THIS repo
- Standard library only for runtime code. Do not add runtime dependencies.
- The agent adapter must NEVER run `git commit`, `git push`, or open PRs; the
  engine (`src/factory/engine.py`) owns all git/remote side effects.
- Keep the verification gate (`src/factory/checks.py`) as the single source of
  truth for "is this change acceptable".

## Commands
- Install:        `python -m pip install -e ".[dev]"`
- Test:           `python -m pytest -q`
- Lint:           `python -m ruff check src tests`
- CLI smoke:      `factory backends` / `factory status` / `factory enqueue ...`

## Layout
- `src/factory/adapters/` - agent backends; add one with `@register("name")`.
- `src/factory/engine.py`  - per-task orchestration (worktree -> agent -> verify -> PR -> auto-merge).
- `src/factory/automerge.py` - CI-gated merge; opt-in via `FACTORY_AUTO_MERGE`; fail-closed
  classification (`classify`) is pure and unit-tested. Never merges on fail/pending/timeout.
- `src/factory/runner.py`  - continuous loop + one-shot runner.
- `src/factory/state.py`   - SQLite queue (durable, dedupes by external_id).
- `src/factory/checks.py`  - convention-based check discovery; override with `FACTORY_CHECKS`.
- `deploy/`, `.github/workflows/` - 24/7 deployment targets (systemd, cron, Actions).

## Testing notes
- End-to-end tests create a real bare git remote in `tmp_path` and use a fake
  adapter registered in-test. They stub `factory.engine.pr_mod.create_pr` so no
  GitHub auth is needed. Keep it that way: no network in tests.

## Gotchas
- `StrEnum` requires Python 3.11+.
- Worktrees live under `FACTORY_WORK_ROOT/wt/`; the engine removes and recreates
  them per task, so never store state only in a worktree.
- `gh` is used for PR creation when present; otherwise the GitHub REST API is
  used with `GITHUB_TOKEN` + `FACTORY_GITHUB_REPO`.
