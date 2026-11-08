---
name: deploy-staging
description: Deploy the current revision to a staging (preview) environment and smoke-test it. Use when shipping to staging, validating a change end to end before production, or when the staging deploy or its smoke test failed.
---

# Deploy to staging

Ship the revision to staging, prove it is reachable, then stop. Production is a
separate, approval-gated step.

## Procedure

1. Confirm the revision is on `main` (staging deploys from `main`, never a
   feature branch) and CI is green.
2. Trigger the deploy:
   ```bash
   gh workflow run deploy-staging.yml --repo <owner>/<repo>
   gh run watch --repo <owner>/<repo>
   ```
3. The workflow deploys a Vercel preview, aliases it to `STAGING_URL` if set,
   and smoke-tests `STAGING_SMOKE_PATH` (default `/`).
4. Read the deploy URL from the run summary / environment. That is the artifact
   to hand to QA.

## Rules

- **Never deploy to production from here.** Production is `deploy-prod.yml` and
  requires an Environment approval.
- **A failed smoke test is a failed deploy.** Do not hand over a URL that did
  not return `200`; fix forward or roll back.
- **Rotate the token if it leaks.** `VERCEL_TOKEN` is a secret; if it appears in
  any log, chat, or issue, revoke and re-issue it (see `deploy/vercel/README.md`).
- **Keep staging and production separate.** They must not share a token scope or
  a project alias.

## When the deploy fails

- `vercel pull`/`build` errors: usually a missing `VERCEL_ORG_ID` /
  `VERCEL_PROJECT_ID` variable, or a build error in the app itself.
- Auth errors: the `VERCEL_TOKEN` secret is missing, expired, or revoked.
- Smoke test fails: the app deployed but is unhealthy — check the deployment
  logs at the preview URL, then the app's runtime logs.
