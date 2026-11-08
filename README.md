## Harness: skills and roles

The pipeline runs one **role** per stage, and each role draws on reusable
**skills**. See [`roles/README.md`](roles/README.md) and `.agents/skills/`.

```
Idea -> Build -> Coding -> Testing -> Staging -> Deploy -> Monitor
 pm    architect  coder      qa       release   release    sre
                                                            |
       +------------- factory-labeled issue ---------------+
```

- Skills (`.agents/skills/`): `write-prd`, `implement-feature`, `ci-tests-audit`,
  `qa-changes`, `deploy-staging`, `monitor-errors`.
- Roles (`roles/`): `pm`, `architect`, `coder`, `qa`, `release`, `sre`.
- Only `coder` edits source (in a worktree); only `release` deploys; no role runs
  git - the engine owns commit/push/PR.

## Tests

```bash
python -m pytest -q
python -m ruff check src tests
```

_Automation built with OpenHands._
