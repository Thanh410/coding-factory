---
name: deploy-prod
description: Ship an approved revision to production and verify it. Use when promoting a change to production, when a release tag is pushed, or when a production deploy needs a smoke check.
---

# Deploy to production

Production is **approval-gated**. The job pauses on the `production` GitHub
Environment until a required reviewer approves it — you do not merge to ship, you
approve to ship.

## Procedure

1. Confirm staging is green (`deploy-staging` on `main`) and the change is
   reviewed and merged.
2. Trigger the deploy (or let the staging `workflow_run` trigger queue it):
   ```bash
   gh workflow run deploy-prod.yml --repo <owner>/<repo> -f ref=main
   ```
3. **Approve it.** Open the pending run in Actions → Review deployments →
   `production` → Approve and deploy. Nothing ships before this.
4. Watch the run. It deploys, then smoke-tests `PROD_URL` and fails unless it
   gets a `200`. Read the run summary for the ref, URL, and smoke status.

## Rules

- **Never bypass the environment approval.** No admin merge, no pushing a
  workflow that deploys without the `production` environment.
- **Never deploy an unmerged or unreviewed ref.** Production ships reviewed
  `main` (or a release tag).
- **Deploy and verify are one step.** If the smoke test fails, roll back
  (`rollback-prod.yml`) rather than leaving a broken production.
- **Keep production credentials separate.** Use environment-scoped secrets so
  an unapproved run cannot reach them.

## If production is broken

1. Roll back first, diagnose second:
   ```bash
   gh workflow run rollback-prod.yml --repo <owner>/<repo>
   ```
2. Approve the rollback (same environment gate), confirm the smoke test passes.
3. Diagnose from the deployment logs, then fix forward on `main` and re-deploy
   through the normal gate.
