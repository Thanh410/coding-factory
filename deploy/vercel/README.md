# Staging deploys on Vercel

`deploy-staging.yml` deploys a **preview** (staging) build on every push to
`main` and smoke-tests the URL. Production is separate (`deploy-prod.yml`, P3)
and gated by a GitHub Environment approval.

The workflow is generic: copy it into any Vercel-backed repo.

## One-time setup

1. **Create a Vercel token** at https://vercel.com/account/tokens and add it as a
   repository secret named `VERCEL_TOKEN`. Never commit it, and rotate it if it
   ever appears in a log, chat, or issue.

   ```bash
   gh secret set VERCEL_TOKEN --repo <owner>/<repo>
   ```

2. **Set two repository variables** (Settings → Secrets and variables → Actions
   → Variables):

   | Variable | Where to find it |
   |----------|------------------|
   | `VERCEL_ORG_ID` | `vercel link` writes it to `.vercel/project.json` (`orgId`) |
   | `VERCEL_PROJECT_ID` | same file (`projectId`) |

   ```bash
   gh variable set VERCEL_ORG_ID     --repo <owner>/<repo>
   gh variable set VERCEL_PROJECT_ID --repo <owner>/<repo>
   ```

3. **Optional** — pin a stable staging URL and the smoke path:

   ```bash
   gh variable set STAGING_URL        --repo <owner>/<repo>   # https://app-staging.vercel.app
   gh variable set STAGING_SMOKE_PATH --repo <owner>/<repo>   # default "/"
   ```

   With `STAGING_URL` set, each deploy is aliased to it, so the smoke test always
   hits the same host.

## What it does

1. `vercel pull --environment=preview` — fetch the project's build settings.
2. `vercel build` — build the prebuilt output on the runner.
3. `vercel deploy --prebuilt` — upload and get a preview URL.
4. `vercel alias set` — point `STAGING_URL` at the new deployment (if set).
5. Smoke test — retries `curl -L` up to 5 times; fails the job unless it gets a
   `200`.

## Rotating the token

Rotate immediately if the token is ever exposed:

1. Revoke the old token at https://vercel.com/account/tokens.
2. Create a new one and `gh secret set VERCEL_TOKEN --repo <owner>/<repo>`.
3. Re-run the workflow to confirm.

A leaked token can deploy to, and read, every project the account can reach — so
treat exposure as an incident, not a chore.
