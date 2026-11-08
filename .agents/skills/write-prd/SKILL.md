---
name: write-prd
description: Turn a raw idea or issue into a concise, testable product requirements document with acceptance criteria. Use at the start of a feature, when a request is ambiguous, or before implementation planning.
---

# Write a PRD

Produce a short document a builder can implement without re-asking. Bias toward
testable statements over prose.

## 1. Frame the problem

- Who is the user and what job are they trying to do?
- What is broken or missing today, and what is the value of fixing it?
- What is explicitly out of scope for this change?

## 2. Define acceptance criteria

Write criteria as concrete, checkable statements ("Given X, when Y, then Z").
Each criterion should map to something QA can verify in the running app.

- Cover the happy path, the empty state, and one error path.
- For AI features, state the model/provider expectation, the streaming/loading
  behavior, and the failure behavior when the provider errors or rate-limits.

## 3. List open questions

Call out anything ambiguous instead of guessing. Stop and ask rather than
inventing requirements.

## Deliver

A PRD: problem, user, scope, acceptance criteria, and open questions. Do not
write code or open a pull request.
