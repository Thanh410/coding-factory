---
name: run-evals
description: Measure the coding factory's pass-rate on golden tasks and gate changes on it. Use when validating a prompt, skill, role, or engine change, before merging harness changes, or when the pipeline's reliability is in question.
---

# Run evals

Turn "does the factory still work?" into a number. Run the golden-task suite
through the real engine and compare the pass-rate to the last known value.

## Procedure

1. Pick the backend that matches what you are validating (`llm`, `codex`,
   `antigravity`). Use the same backend across runs so the number is comparable.
2. Run the suite:
   ```bash
   factory eval --backend llm --suite evals/cases
   ```
3. Read the report. For every `FAIL`, the reason lines say whether it was the
   terminal state or the changed files that diverged.
4. For a gate (CI), require a floor:
   ```bash
   factory eval --backend llm --min-pass-rate 0.8
   ```
   Exit code is non-zero when the pass-rate is below the floor.

## Rules

- **Fix the cause, not the case.** If a case fails, decide whether the case's
  expectation is wrong or the pipeline regressed. Only edit the case when its
  expectation was wrong, and say why in the commit.
- **Keep cases small and deterministic.** A flaky case makes the pass-rate
  meaningless.
- **Never raise the floor to hide a regression.** Lower it only to record a
  known, accepted drop, and note it.
- **Compare like with like.** A pass-rate from `llm` is not comparable to one
  from `codex`; keep the backend fixed when tracking over time.

## Adding a case

Add a `*.json` file under `evals/cases/` (see `evals/README.md` for the schema).
Give it a stable `id`, a `checks` command that decides success, and `expect`
fields for the terminal state and the files that must (or must not) change.
