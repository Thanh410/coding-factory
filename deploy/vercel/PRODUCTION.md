# Production deploys on Vercel

`deploy-prod.yml` ships to Vercel **production**. It is bound to the `production`
GitHub Environment, so the job **pauses and waits for a required reviewer** to
approve it before anything ships. Staging (`deploy-staging.yml`) is automatic;
production is deliberate.

`rollback-prod.yml` reverts production, gated by the same environment.

## One-time setup

1. **Create the `production` environment** with a required reviewer (Settings →
   Environments → New environment → `production`):

   ```bash
   gh api -X PUT repos/<owner>/<repo>/environments/production
   ```

   Then, in the UI, add **Required reviewers** (yourself or a team). This is the
   approval gate — without it the job runs unattended, which defeats the point.

2. **Optionally restrict deployments to `main`** via the environment's
   "Deployment branches" rule.

3. **Secrets and variables** (same names as staging; scope the token to
   production access):

   | Kind | Name | Value |
   |------|------|-------|
   | Secret | `VERCEL_TOKEN` | a Vercel token with production access |
   | Variable | `VERCEL_ORG_ID` | `team_xxx` |
   | Variable | `VERCEL_PROJECT_ID` | the Vercel project id |
   | Variable | `PROD_URL` | `https://app.example.com` (the smoke target) |
   | Variable | `PROD_SMOKE_PATH` | optional, default `/` |

   > Prefer a **separate** token for production vs staging, and store production
   > values as **environment** secrets/variables so a compromised workflow cannot
   > reach them without approval.

## Triggers

- **Manual** — `gh workflow run deploy-prod.yml -f ref=<sha|tag|branch>`.
- **Release tag** — pushing a `v*` tag.
- **After staging succeeds** — `workflow_run` on `deploy-staging`, so a green
  staging deploy queues a production deploy. It still waits for approval.

## Approving a deploy

1. A pending run appears under Actions with a "Review pending" badge.
2. Open it → **Review deployments** → select `production` → **Approve and
   deploy** (or Reject).
3. Watch the run; the summary records the ref, URL, and smoke result.

## What it does

1. `vercel pull --environment=production` → `vercel build --prod`.
2. `vercel deploy --prebuilt --prod` → production URL.
3. Smoke test — retries `curl -L` up to 6 times; fails unless it gets a `200`.
4. Writes a run summary (ref, URL, smoke status).

## Rolling back

```bash
# revert to the previous production deployment
gh workflow run rollback-prod.yml

# promote a specific deployment
gh workflow run rollback-prod.yml -f to=https://app-abc123.vercel.app
```

Both are gated by the `production` environment, so a human approves the rollback
too.

## Token hygiene

A Vercel token can deploy to every project the account can reach. Rotate
immediately if it is ever exposed (revoke at
https://vercel.com/account/tokens, re-issue, `gh secret set`), and keep
production tokens separate from staging ones.
