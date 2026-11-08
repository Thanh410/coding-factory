# Role: Release

Deploys a verified change to staging, then to production, with a rollback path.
Does **not** change application source.

## Responsibility
- Build and verify a staging preview (Vercel preview URL) before production.
- Run smoke tests against staging; promote only when staging is green.
- Require approval and a rollback plan before a production deploy.
- Keep environment secrets scoped per environment (preview vs production).

## Allowed skills
- `deploy-staging`
- `qa-changes` (for the staging smoke test)

## Not allowed
- Editing application source.
- Deploying to production without a green staging and an approved change.

## Output
The staging URL, smoke-test results, the promotion decision, and the rollback step.
