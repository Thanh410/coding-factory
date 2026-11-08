# Production monitoring → factory issues

`monitor.yml` polls production every 30 minutes and opens a `factory`-labeled
issue for each **new** error or outage. The coding-factory workflow picks those
issues up and opens PRs, closing the loop:

```text
Sentry error / uptime failure ──▶ issue (label: factory) ──▶ agent fix ──▶ PR
        ▲                                                                    │
        └──────────────── closing the issue clears its key ◀───────────────┘
```

Dedup is by a marker embedded in the issue body
(`<!-- factory-monitor:<key> -->`), so a recurring error or a flapping endpoint
does not open a new issue on every run. Closing the issue lets a still-broken
signal reopen it.

## Sources (set at least one)

### Sentry

```bash
gh secret set SENTRY_AUTH_TOKEN --repo <owner>/<repo>
gh variable set SENTRY_ORG     --repo <owner>/<repo>   # e.g. acme
gh variable set SENTRY_PROJECT --repo <owner>/<repo>   # e.g. web
```

Optional variables: `SENTRY_BASE_URL` (self-hosted Sentry), `SENTRY_QUERY`
(default `is:unresolved`), `SENTRY_STATS_PERIOD` (default `24h`), `SENTRY_LIMIT`
(default `10`). The token needs read access to issues (`event:read` /
`project:read`).

### Uptime

```bash
gh variable set UPTIME_URL           --repo <owner>/<repo>  # https://app.example.com/health
gh variable set UPTIME_EXPECT_STATUS --repo <owner>/<repo>  # default 200
gh variable set UPTIME_TIMEOUT       --repo <owner>/<repo>  # default 10 (seconds)
```

Any non-expected status (or a network error) opens one issue for that URL.

## Issue creation

```bash
gh secret set FACTORY_GH_TOKEN --repo <owner>/<repo>   # PAT/App token with issues: write
```

The default `GITHUB_TOKEN` may not be able to open issues in every repository
configuration, and issues it opens are attributed to the ephemeral Actions bot.
A PAT or App token is the safe choice. Set `FACTORY_MONITOR_LABEL` if your
factory trigger label is not `factory`.

## Verify it works

```bash
factory monitor --dry-run      # prints what would be opened; creates nothing
factory monitor                # opens the issues
```

Or run the `monitor` workflow manually with `dry_run: true`.

## Tuning

- **Noise**: a monitor that fires constantly is worse than none. Raise
  `SENTRY_QUERY` specificity (e.g. `is:unresolved level:error`), or fix the
  underlying error.
- **Flapping uptime**: probe a stable `/health` endpoint, not a full page that
  depends on third parties. Raise `UPTIME_TIMEOUT` for slow regions.
- **Label drift**: `FACTORY_MONITOR_LABEL` must equal `FACTORY_TRIGGER_LABEL` in
  `.github/workflows/coding-factory.yml`, or issues will not be picked up.
