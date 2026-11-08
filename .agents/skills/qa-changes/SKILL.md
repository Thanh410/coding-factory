---
name: qa-changes
description: Functionally verify a change by exercising the real running app (routes, API, AI assistant flows), not just reading the diff or trusting unit tests. Use to QA a feature before staging, reproduce a reported bug, or confirm a fix in the browser.
---

# QA a change

Confirm the change works in the running product, on the paths a user actually
takes. Reading the diff and passing unit tests are necessary, not sufficient.

## 1. Establish what to verify

Read the task and the diff. List the user-visible behaviors the change affects
and the acceptance condition. Identify how the app runs locally or in a preview
(`AGENTS.md` commands, `docker compose`, or a deployed preview URL).

Finish when you have a concrete checklist of behaviors and their expected result.

## 2. Run the real app

Start the app with the project's own command. Exercise each checklist item:

- Navigate the real routes; submit real forms; follow the primary actions.
- For AI features: send a real prompt and check streaming, error, and empty
  states. Verify the assistant cannot leak provider keys and degrades gracefully
  when the provider errors or rate-limits.
- Check responsive layout at desktop and mobile widths.
- Watch the console and network for errors, 4xx/5xx, and missing assets.

## 3. Reproduce failures precisely

When something fails, capture the smallest reproduction: URL, inputs, expected
vs actual, and any console/network evidence. Distinguish a product bug from an
environment problem (missing env var, cold start).

## Report

Return a pass/fail per checklist item, the exact steps to reproduce any failure,
and the evidence (screenshots or logs). State what you could not verify and why.
Do not commit, push, or merge; the harness owns those steps.
