# Evals: golden tasks for the coding factory

An eval measures **pass-rate**: of a fixed set of tasks, how many does the
pipeline drive to the expected outcome? Run it after changing prompts, skills,
roles, or the engine so you can tell an improvement from a regression.

```bash
factory eval --backend llm                 # run evals/cases, print a report
factory eval --backend llm --json          # machine-readable
factory eval --backend llm --min-pass-rate 0.8   # exit 1 below 80% (for CI)
factory eval --backend llm --record        # also append the run to the history
factory dashboard                          # render evals/history.json -> HTML
```

Each case runs the **real engine** against a throwaway git repo seeded with the
case's files. PR creation is stubbed, so no GitHub auth is needed. Use any
backend (`codex`, `antigravity`, `llm`).

## Pass-rate dashboard

`--record` appends one point to `evals/history.json`; `factory dashboard` renders
that history as a self-contained HTML page (inline SVG, no CDN):

```bash
factory eval --backend llm --record --history evals/history.json
factory dashboard --history evals/history.json --out dashboard/index.html
```

The `dashboard` workflow runs the suite daily and publishes the page to GitHub
Pages (`gh-pages`), so the pass-rate trend is visible without opening CI.

## Case schema

A suite is a directory of `*.json` files (one case each), or a single JSON file
holding a list. Fields:

| Field | Required | Meaning |
|-------|----------|---------|
| `id` | yes | Case id (used in the report) |
| `title` | no | Task title handed to the agent |
| `body` | no | Task description handed to the agent |
| `labels` | no | Task labels |
| `seed_files` | no | `{ "path": "content" }` committed as the starting repo |
| `checks` | no | Verification command (`;`-separated); default `python -m pytest -q` |
| `max_repairs` | no | Repair attempts (default 1) |
| `spec_stage` | no | Run the architect pass (default true) |
| `agent_timeout` | no | Per-agent-call timeout in seconds (default 120) |
| `expect.state` | no | Expected terminal task state (default `pr_open`) |
| `expect.files_changed_contains` | no | Paths that must be in the diff |
| `expect.files_changed_excludes` | no | Paths that must not be in the diff |

## Bundled cases

- `add-file` — create a new module; checks that the file exists and matches.
- `fix-bug` — fix an off-by-one so the seeded test passes; minimal diff.
- `must-block` — an unsatisfiable task must end `blocked`, not `pr_open`.

Keep cases small and deterministic. A flaky case is worse than no case: it makes
the pass-rate meaningless.
