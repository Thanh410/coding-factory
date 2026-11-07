# coding-factory

A dependency-free Python (3.11+) pipeline that turns tasks (GitHub issues,
JSON, or markdown) into **verified pull requests**, 24/7. Pluggable coding-agent
backends: OpenAI Codex (default) and Google Antigravity.

```
task source -> SQLite queue -> agent (Codex/Antigravity) -> checks -> commit -> push -> PR -> [wait for CI -> auto-merge]
                    ^                                                        |
                    +----------------- repair loop ---------------------------+
```

## Why it is built this way

- **Safe by construction**: the agent only edits files in an isolated git
  worktree. Commit/push/PR are done by the engine, never the agent. The agent
  never touches the base branch.
- **Verification gate**: a change becomes a PR only after lint/test/build pass.
  On failure the engine feeds the logs back to the agent (repair loop).
- **Auto-merge is opt-in and CI-gated**: off by default. When enabled, the
  factory waits for the repo's CI to go green, then merges. A failing, pending,
  or timed-out CI never merges - the PR is left for a human.
- **Durable**: state lives in SQLite, so the runner survives restarts and
  dedupes tasks.
- **No runtime dependencies**: standard library + `git` + (optional) `gh`.

## Install

```bash
python -m pip install -e ".[dev]"

# Codex backend (default)
npm install -g @openai/codex
export OPENAI_API_KEY=...

factory backends
```

## Quick start

```bash
factory enqueue --id demo-1 --title "Add a /health endpoint" --body "with a test"
factory run-once --backend codex --verbose
factory run-loop --backend codex --interval 60     # daemon
factory status
```

## Using it on another repository

This repo is the *engine*. To run it against a target repo, drop
`.github/workflows/coding-factory.yml` into the target repo and set the
repository variable `FACTORY_REPO_SLUG=Thanh410/coding-factory` so the workflow
installs the engine from here. Then add the `OPENAI_API_KEY` secret and (for
auto-merge) a `FACTORY_GH_TOKEN` PAT/App token plus `FACTORY_AUTO_MERGE=true`.

Alternatively run it on a VPS with systemd or cron - see `deploy/`.

## Tests

```bash
python -m pytest -q
python -m ruff check src tests
```

_Automation built with OpenHands._
