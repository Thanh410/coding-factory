# coding-factory

A dependency-free Python (3.11+) pipeline that turns tasks (GitHub issues,
JSON, or markdown) into **verified pull requests**, 24/7. Pluggable coding-agent
backends: OpenAI Codex (default), Google Antigravity, and a built-in `llm`
backend with a provider fallback chain (OpenRouter, Gemini, or a local Ollama).

```
task source -> SQLite queue -> spec pass (architect, read-only) -> agent (Codex/Antigravity/llm) -> checks -> commit -> push -> PR -> [wait for CI -> auto-merge]
                    ^                                                                              |
                    +------------------------------ repair loop ------------------------------------+
```

The **spec pass** is a read-only planning step: the agent reads the code and
returns a plan, which is handed to the coding agent. It is on by default and can
be turned off with `FACTORY_SPEC_STAGE=false`.

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

## LLM backend: provider fallback (OpenRouter + Gemini) and self-hosted Ollama

Besides Codex and Antigravity, the factory ships an `llm` backend: a small,
standard-library-only agent that talks to **any OpenAI-compatible endpoint**.
OpenRouter, Google Gemini (OpenAI-compat), and Ollama share that API, so one
client drives all three - and the **fallback chain** moves to the next provider
when one is unconfigured, rate-limited, or failing.

```bash
export FACTORY_BACKEND=llm
export FACTORY_LLM_CHAIN=openrouter,gemini,ollama   # order to try
export OPENROUTER_API_KEY=sk-or-...                 # if you use OpenRouter
export GEMINI_API_KEY=...                           # if you use Gemini
factory backends                                    # 'llm available=True'
factory run-once --backend llm --verbose
```

How it works:

- Providers **without a key are skipped**, so you only set the keys you have and
  the chain shrinks automatically.
- A network/HTTP/rate-limit error on the active provider **falls through to the
  next one**; the whole run is recorded in `agent.log`.
- You can **pin a model per step**: `FACTORY_LLM_CHAIN=openrouter:anthropic/claude-3.5-sonnet,gemini`.
- The agent only has file tools (`read_file`, `write_file`, `delete_file`,
  `list_files`) and is **blocked from escaping the worktree** (any `../` path is
  rejected). It never runs git - the engine does.

### Free models ($0) on OpenRouter

A `free` alias expands to a curated list of OpenRouter models that are **priced
at $0 and support tool calling** (required for the agent). Run at no cost:

```bash
export FACTORY_BACKEND=llm
export FACTORY_LLM_CHAIN=free          # the whole list, in priority order
export FACTORY_LLM_CHAIN=free:3        # just the top 3
export FACTORY_LLM_CHAIN=free,ollama   # free first, local Ollama as fallback
export OPENROUTER_API_KEY=sk-or-...    # a (free) key is still required

factory models        # print the curated list
```

The curated list (`FREE_MODELS` in `src/factory/providers.py`) puts
coding-focused models first, e.g. `nvidia/nemotron-3-ultra-550b-a55b:free`,
`cohere/north-mini-code:free`, `recursive/flint-v1.0:free`, `google/gemma-4-31b-it:free`.

> Free models are often **rate-limited**; the fallback chain handles that - a
> 429 on the first model moves on to the next.
>
> **Important:** OpenRouter `:free` models are blocked when your account has not
> enabled data sharing. If you see *"guardrail restrictions and data policy"*,
> enable free endpoints at https://openrouter.ai/settings/privacy, or use a paid
> model (e.g. `openrouter:openai/gpt-4o-mini`) or Gemini.
>
> The free lineup rotates; `factory models` prints the curated list, and you can
> check the live catalogue with
> `curl -s https://openrouter.ai/api/v1/models | python -m json.tool`.

### Ollama (self-hosted, free, no API key)

```bash
bash deploy/ollama/setup-ollama.sh                          # install + pull qwen2.5:3b
MODEL=qwen2.5-coder:7b bash deploy/ollama/setup-ollama.sh   # a different model

export FACTORY_BACKEND=llm
export FACTORY_LLM_CHAIN=ollama
export OLLAMA_MODEL=qwen2.5:3b
factory backends        # 'llm available=True'
```

Ollama listens on `127.0.0.1:11434` by default. To reach it from another machine
(LAN), install with `OLLAMA_HOST=0.0.0.0` and point `OLLAMA_BASE_URL` at its IP.

### Key environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `FACTORY_LLM_CHAIN` | `openrouter,gemini,ollama` | provider chain for the `llm` backend |
| `FACTORY_LLM_CHAIN=free` | - | alias: OpenRouter $0 models (tool calling); `free:3` caps the count |
| `OPENROUTER_MODEL` | `openai/gpt-4o-mini` | OpenRouter model |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Gemini model |
| `OLLAMA_MODEL` | `qwen2.5:3b` | Ollama model |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434/v1` | Ollama endpoint |
| `FACTORY_LLM_MAX_STEPS` | `30` | max tool-call rounds per run |
| `FACTORY_LLM_MAX_TOKENS` | `4096` | max tokens per model call |
| `FACTORY_SPEC_STAGE` | `true` | run the read-only architect pass before coding |

## Harness: skills and roles

The pipeline runs one **role** per stage, and each role draws on reusable
**skills**. See [`roles/README.md`](roles/README.md) and `.agents/skills/`.

```
Idea -> Build -> Coding -> Testing -> Staging -> Deploy -> Monitor
 pm    architect  coder      qa       release   release    sre
                                                            |
       +------------- factory-labeled issue ---------------+
```

- Skills (`.agents/skills/`): `write-prd`, `implement-feature`, `ci-tests-audit`,
  `qa-changes`, `deploy-staging`, `monitor-errors`.
- Roles (`roles/`): `pm`, `architect`, `coder`, `qa`, `release`, `sre`.
- Only `coder` edits source (in a worktree); only `release` deploys; no role runs
  git - the engine owns commit/push/PR.

## Tests

```bash
python -m pytest -q
python -m ruff check src tests
```

## Evals: golden-task pass-rate

A fixed set of tasks measures whether the pipeline actually works, so you can
tell an improvement from a regression.

```bash
factory eval --backend llm                       # run evals/cases, print a report
factory eval --backend llm --json                # machine-readable
factory eval --backend llm --min-pass-rate 0.8   # exit 1 below 80% (CI gate)
```

Each case runs the **real engine** against a throwaway git repo seeded with the
case's files; PR creation is stubbed, so no GitHub auth is needed. Cases live in
`evals/cases/` — see `evals/README.md` for the schema. The weekly `evals`
workflow runs the suite; set the `FACTORY_EVAL_MIN_PASS_RATE` repository variable
to gate merges on it.

## Dashboard: pass-rate over time

Record each run and render a self-contained HTML page (inline SVG, no CDN):

```bash
factory eval --backend llm --record --history evals/history.json
factory dashboard --history evals/history.json --out dashboard/index.html
```

The `dashboard` workflow runs the suite daily, appends a point to
`evals/history.json`, and publishes the page to GitHub Pages (`gh-pages`), so you
can see at a glance whether the pipeline is getting better or worse. One-time
setup: Settings → Pages → Source = *Deploy from a branch*, branch `gh-pages`.

## Monitoring: errors and uptime become issues

`monitor.yml` polls production every 30 minutes and opens a `factory`-labeled
issue for each **new** Sentry error or uptime failure. The factory then picks
those issues up like any other task, closing the loop:

```text
Sentry error / uptime failure ──▶ issue (label: factory) ──▶ agent fix ──▶ PR
```

```bash
export SENTRY_AUTH_TOKEN=... SENTRY_ORG=acme SENTRY_PROJECT=web   # Sentry
export UPTIME_URL=https://app.example.com/health                 # uptime
factory monitor --dry-run     # print what would be opened
factory monitor               # open the issues
```

Dedup is by a marker in the issue body, so a recurring error does not open a new
issue every run; closing the issue lets a still-broken signal reopen it. Setup is
in `deploy/monitoring/README.md`.

## Deployment: staging and production

Three workflows ship a change once it is on `main`:

- `.github/workflows/deploy-staging.yml` — deploys a Vercel **preview** on every
  push to `main`, aliases it to `STAGING_URL`, and smoke-tests the URL. Setup is
  in `deploy/vercel/README.md`.
- `.github/workflows/deploy-prod.yml` — deploys to **production**, bound to the
  `production` GitHub Environment, so it **waits for a required reviewer** before
  shipping. Setup is in `deploy/vercel/PRODUCTION.md`.
- `.github/workflows/rollback-prod.yml` — reverts production to a previous
  deployment, gated by the same environment.

Staging is automatic; production is deliberate. Production also triggers from a
`v*` release tag, or automatically after a successful staging deploy — but always
behind the approval gate.

Required for staging: the `VERCEL_TOKEN` secret and the `VERCEL_ORG_ID` /
`VERCEL_PROJECT_ID` variables. Optional: `STAGING_URL`, `STAGING_SMOKE_PATH`.
Production adds a `production` Environment with required reviewers and a
`PROD_URL` variable.

> A Vercel token can deploy to every project the account can reach. If it ever
> leaks, revoke it and re-issue it — see `deploy/vercel/README.md`. Keep the
> production token separate from staging.

_Automation built with OpenHands._
