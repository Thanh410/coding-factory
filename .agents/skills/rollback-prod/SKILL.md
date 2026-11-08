---
name: rollback-prod
description: Revert production to a previous deployment when a release is broken. Use when a production deploy or its smoke test fails, when an incident is traced to a deploy, or when asked to roll back production.
---

# Roll back production

Get production back to a known-good deployment, fast. The rollback is
approval-gated by the same `production` environment, so a human confirms it.

## Procedure

1. Confirm the breakage is a **deploy**, not infrastructure: check the smoke
   test, then the deployment logs.
2. Trigger the rollback:
   ```bash
   # revert to the previous production deployment
   gh workflow run rollback-prod.yml --repo <owner>/<repo>

   # or promote a specific known-good deployment
   gh workflow run rollback-prod.yml --repo <owner>/<repo> \
     -f to=https://app-abc123.vercel.app
   ```
3. Approve it (Actions → Review deployments → `production`).
4. Confirm the smoke test passes and the incident is contained.

## Rules

- **Roll back before root-causing.** A broken production costs more than a
  delayed diagnosis.
- **One known-good target.** Prefer promoting the last deployment that passed its
  smoke test over "the previous one" when unsure.
- **Record it.** Note the rollback (from/to, cause) on the incident so the
  post-mortem has the timeline.
- **Fix forward, then re-deploy through the gate.** Never hand-edit production;
  the next deploy will overwrite it anyway.

## When rollback does not fix it

If the smoke test still fails after a rollback, the fault is likely external
(bad env var, upstream outage, DNS/TLS). Check `PROD_URL`, the Vercel project's
environment variables, and the provider's status page before rolling back again.
