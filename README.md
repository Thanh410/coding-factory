# coding-factory

A dependency-free Python (3.11+) pipeline that turns tasks (GitHub issues,
JSON, or markdown) into **verified pull requests**, 24/7. Pluggable coding-agent
backends: OpenAI Codex (default), Google Antigravity, and a built-in `llm`
backend with a provider fallback chain (OpenRouter, Gemini, or a local Ollama).

```
task source -> SQLite queue -> agent (Codex/Antigravity/llm) -> checks -> commit -> push -> PR -> [wait for CI -> auto-merge]
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

_Automation built with OpenHands._
