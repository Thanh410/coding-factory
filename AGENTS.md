# AGENTS.md - repository knowledge for coding agents

## What this repo is
`coding-factory` is a dependency-free Python (3.11+) pipeline that turns tasks
(GitHub issues / JSON / markdown) into verified pull requests by running a coding
agent (OpenAI Codex, Google Antigravity, or the built-in `llm` provider-fallback
backend) inside an isolated git worktree.

The product this pipeline ships is **AI-assisted web apps**: web applications
that embed an AI agent or assistant. The harness therefore targets the full
lifecycle of such an app, not just "open a PR".

## Product and authority
- The pipeline has one authority per stage (see `roles/README.md`). Only the
  `coder` role edits application source, and only inside an isolated worktree.
- Only the `release` role deploys; production deploys require a green staging
  preview and an approved change. No role runs `git commit`, `git push`, or opens
  a pull request - the engine (`src/factory/engine.py`) owns those side effects.
- Investigation alone does not authorize edits. A skill does not grant
  permission to push, deploy, or merge; existing user authorization still applies.
- Do not expand scope for a speculative edge case without stating the concrete
  failure mode and getting the user's buy-in.

## Golden rules for agents working in THIS repo
- Standard library only for runtime code. Do not add runtime dependencies.
- The agent adapter must NEVER run `git commit`, `git push`, or open PRs; the
  engine owns all git/remote side effects.
- Keep the verification gate (`src/factory/checks.py`) as the single source of
  truth for "is this change acceptable".
- Secrets come from the environment (per-environment in Vercel/Actions), never
  from code or committed files.

## Commands
- Install:        `python -m pip install -e ".[dev]"`
- Test:           `python -m pytest -q`
- Lint:           `python -m ruff check src tests`
- CLI smoke:      `factory backends` / `factory status` / `factory enqueue ...`

## Layout
- `src/factory/adapters/` - agent backends; add one with `@register("name")`.
  `llm.py` is the provider-fallback agent; `providers.py` holds the
  OpenRouter/Gemini/Ollama registry and chain resolution (`FACTORY_LLM_CHAIN`).
  Unconfigured providers are skipped; failures fall through to the next one.
  The `free` chain alias expands to `FREE_MODELS` (OpenRouter $0, tool-capable);
  refresh that list from the live /models API when OpenRouter rotates it.
- `src/factory/engine.py`  - per-task orchestration (worktree -> spec pass -> agent -> verify -> PR -> auto-merge).
  The spec pass (`_spec`) is a read-only architect step, gated by
  `FACTORY_SPEC_STAGE` (on by default); its plan is stored on the task and handed
  to the coding agent. The pass must not leave files behind - `gitops.discard_changes`
  resets the worktree after it.
- `src/factory/automerge.py` - CI-gated merge; opt-in via `FACTORY_AUTO_MERGE`; fail-closed
  classification (`classify`) is pure and unit-tested. Never merges on fail/pending/timeout.
- `src/factory/runner.py`  - continuous loop + one-shot runner.
- `src/factory/state.py`   - SQLite queue (durable, dedupes by external_id).
- `src/factory/checks.py`  - convention-based check discovery; override with `FACTORY_CHECKS`.
- `src/factory/eval.py`    - golden-task harness: `factory eval` runs cases from
  `evals/cases/` through the real engine (PR stubbed) and reports a pass-rate.
  Case schema is in `evals/README.md`. Keep cases small and deterministic.
- `src/factory/monitor.py` - production monitors: poll Sentry + an uptime URL and
  open `factory` issues for anything new (dedup by a marker in the issue body).
  Closes the loop: production error -> issue -> fix -> PR. `factory monitor`.
- `.agents/skills/`        - reusable skills (progressive disclosure; see below).
- `roles/`                 - bounded agents, one per pipeline stage.
- `deploy/`, `.github/workflows/` - 24/7 deployment targets (systemd, cron, Actions).

## Skills and roles
- A **skill** is a `SKILL.md` with YAML frontmatter (`name`, `description` with a
  "use when" clause) plus optional `references/` read only when needed. Keep the
  body a procedure, not prose. Skills live in `.agents/skills/<name>/`.
- A **role** (`roles/<name>.md`) is a bounded agent: a system prompt, the skills
  it may use, and the side effects it may cause. Roles map 1:1 to pipeline stages
  (Idea -> Build -> Coding -> Testing -> Staging -> Deploy -> Monitor).
- Plugins are declared in `.claude-plugin/plugin.json` and
  `.codex-plugin/plugin.json`; the marketplace entry is `.agents/plugins/marketplace.json`.
- When adding a skill, add its frontmatter `description` with concrete triggers,
  then wire it into the role(s) that may use it.

## Testing notes
- End-to-end tests create a real bare git remote in `tmp_path` and use a fake
  adapter registered in-test. They stub `factory.engine.pr_mod.create_pr` so no
  GitHub auth is needed. Keep it that way: no network in tests.
- LLM-provider tests (`tests/test_llm_provider.py`) start a real local HTTP server
  that speaks the OpenAI chat-completions protocol, so the client path is exercised
  end to end without any network or API key.
- Monitor tests (`tests/test_monitor.py`) likewise run a local HTTP server that
  stands in for Sentry and the GitHub API.
- Eval tests (`tests/test_eval.py`) build a throwaway git repo and run the real
  engine with a fake adapter; PR creation is stubbed, so no network.

## Cleanup and maintainability
- Fix the producing boundary before adding downstream repairs; normalize once at
  the owning boundary. Remove superseded helpers, aliases, and redundant tests
  after verifying their consumers.
- When fixing a bug, search sibling adapters and similar workflows for the same
  failure; group findings by root cause instead of filing duplicates.
- Introduce an abstraction only when it removes observed complexity.

## Performance
- Design agent interfaces for efficiency from the first implementation: return
  the smallest sufficient answer, bound concurrency, and keep the whole task
  (including retries and extra calls) in mind.
- Optimize in order: agent tokens/context, then wall-clock analysis time, then
  CPU/memory. Reserve synthetic benchmarks for changes that target performance.

## Gotchas
- `StrEnum` requires Python 3.11+.
- Worktrees live under `FACTORY_WORK_ROOT/wt/`; the engine removes and recreates
  them per task, so never store state only in a worktree.
- `gh` is used for PR creation when present; otherwise the GitHub REST API is
  used with `GITHUB_TOKEN` + `FACTORY_GITHUB_REPO`.
- In a GitHub Actions `env:` block at job level, the `runner` context does not
  exist (use a literal path or move the value into a step).
