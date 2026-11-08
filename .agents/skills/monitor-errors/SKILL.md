---
name: monitor-errors
description: Watch production for errors, latency, and uptime regressions, triage alerts, and turn confirmed defects into tracked GitHub issues. Use for production monitoring, incident triage, and closing the loop from alert to fix.
---

# Monitor production

Keep the product healthy and turn incidents into tracked work. Restore service
first; root-cause after.

## 1. Watch

- Errors and traces: Sentry (or the project's error sink) for new/rising issues.
- Uptime and latency: an uptime check on the primary routes and the AI endpoint.
- Deploys: correlate a new error burst with the last production deploy.

## 2. Triage

For each alert, decide: real incident, known issue, or noise (cold start, a
single flaky request). Establish the blast radius and the first-seen time.

- If a deploy correlates, consider rollback as the first mitigation.
- Reproduce with the smallest steps; capture request/response and stack evidence.

## 3. Close the loop

- For a confirmed defect, open a GitHub issue labeled `factory` with: symptom,
  reproduction, evidence, environment, and suspected owner file.
- The harness picks up `factory`-labeled issues and drives the fix.
- Do not edit application source, push, or merge from this role.

## Deliver

Incident notes, the `factory`-labeled issue (or the decision that it is noise),
and the mitigation or rollback taken.
