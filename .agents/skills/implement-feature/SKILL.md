---
name: implement-feature
description: Implement a scoped feature or fix in an existing web app from a task description, producing a focused diff that passes the project's own checks. Use for coding tasks that change application source (pages, components, API routes, agents), not for CI/test audits, deployment, or monitoring.
---

# Implement a feature

Deliver one complete, working change that satisfies the task. Match the existing
codebase before introducing a new pattern. A change ships only when the project's
own checks pass; the harness runs them, but you must run the checks you touched
before finishing.

## 1. Understand the task and the code

Read `AGENTS.md`, the framework and its real scripts, and the routes/components
the task touches. Open the files that own the behavior before editing anything.

- Identify the single owning file per concern; edit there instead of adding a
  parallel path.
- Read declared values (types, config, existing helpers) rather than inferring
  from one example.
- For an AI feature, find the existing model/provider client and reuse it; do not
  add a second client or a hardcoded key.

Finish when you can name the files you will change and why, and the acceptance
condition the task implies.

## 2. Make the smallest coherent change

Implement the behavior with the existing conventions (component style, naming,
error handling). Keep the diff focused on the task.

- No unrelated reformatting, renames, or dependency additions unless the task
  requires them.
- No secrets in code. Read keys from the environment.
- For an AI assistant/agent feature: stream or return errors the user can act on,
  validate inputs, and never expose provider keys to the client.
- Preserve accessibility and responsive behavior in UI changes.

## 3. Verify before finishing

Run the project's checks for the code you touched:

- Lint, type-check, and build (see `AGENTS.md` for exact commands).
- Tests: extend or add a focused test for the changed behavior.
- For UI: exercise the real route at desktop and mobile widths, including error
  and loading states.

Do not claim success without a passing run. If a check cannot run, say so
explicitly instead of guessing.

## Deliver

End with a `SUMMARY:` section (2-4 lines): what changed, how you verified it, and
any follow-ups. Leave the worktree with the change in place; do not commit, push,
or open a pull request - the harness owns those steps.
