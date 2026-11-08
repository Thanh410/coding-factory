---
name: monitor-errors
description: Watch production for errors and downtime, and turn each new one into a factory issue. Use when setting up production monitoring, when triaging a spike in errors, or when an uptime probe is failing.
---

# Monitor production

Close the loop: production signal → issue → fix → PR → deploy. The `monitor`
command polls Sentry and an uptime URL, dedups against open issues, and opens a
`factory`-labeled issue for anything new. The coding-factory workflow then treats
that issue as a task.

## Procedure

1. Configure at least one source (see `deploy/monitoring/README.md`):
   ```bash
   export SENTRY_AUTH_TOKEN=... SENTRY_ORG=acme SENTRY_PROJECT=web
   export UPTIME_URL=https://app.example.com/health
   export FACTORY_GITHUB_REPO=owner/name GITHUB_TOKEN=...
   ```
2. Dry-run to see what would be opened, without creating anything:
   ```bash
   factory monitor --dry-run
   ```
3. Run it for real (the `monitor` workflow does this every 30 minutes):
   ```bash
   factory monitor
   ```

## Rules

- **One issue per signal.** Dedup is by a marker in the issue body. Do not strip
  the marker, and do not open a second issue for the same Sentry id or URL.
- **A fixed error must be closed.** Closing the issue clears its key, so if the
  error recurs the monitor reopens it. Do not leave fixed issues open — they
  hide the next occurrence.
- **Do not let monitors page a human directly.** They open issues; triage happens
  in the issue, and severity is decided there.
- **Keep the trigger label in sync.** `FACTORY_MONITOR_LABEL` must match
  `FACTORY_TRIGGER_LABEL` in the factory workflow, or issues never get picked up.

## Triage

For each monitor issue: reproduce, decide severity, then either fix (let the
factory open a PR) or close it as transient with a note. A recurring error that
keeps reopening is a real bug — fix the root cause, do not silence the monitor.
