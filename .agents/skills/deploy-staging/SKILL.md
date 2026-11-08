---
name: deploy-staging
description: Deploy a change to a free staging environment (Vercel preview) and verify it end to end before production. Use to stand up a preview URL for a PR, run smoke tests against it, or gate promotion to production.
---

# Deploy to staging (Vercel preview)

Staging is a real, reachable copy of the change on a preview URL. A change is
staging-ready when the preview builds, the app loads, and the primary flows work
against it.

## 1. Build the preview

- Vercel builds a preview deployment for every push to a non-production branch.
  Confirm the project is linked (`vercel link`) and the repo is connected.
- If there is no Git integration, deploy explicitly:

  ```bash
  vercel            # preview deployment for the current branch
  vercel --prod     # production - only after staging passes
  ```

- Required environment variables for the preview (AI provider keys, database
  URL) live in the Vercel project's Preview environment, not in the repo.

## 2. Access a protected preview

Preview deployments may have Deployment Protection enabled, which blocks
automated checks. If a preview URL redirects to login or returns 401/403:

- Ask the owner to create a **Protection Bypass for Automation** secret
  (Settings -> Deployment Protection) and pass it as:
  `curl -H "x-vercel-protection-bypass: $VERCEL_BYPASS" https://<preview-url>`
- Or, for browser checks, append `?x-vercel-protection-bypass=<secret>` once.
- Do not repeatedly retry a protected URL without the bypass secret.

## 3. Smoke test the preview

Against the preview URL:

- Load the changed routes; confirm 200 and no console errors.
- Exercise the primary user flow and the AI assistant flow (real prompt,
  streaming, error state).
- Check a cold start and one error path.
- Verify the preview uses preview env vars, not production secrets.

## Deliver

Return the preview URL, the smoke-test results per flow, and any failure with
steps to reproduce. Promote to production only after staging is green and the
change is approved.
