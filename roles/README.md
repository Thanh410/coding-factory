# Roles

Each role is a bounded agent: a system prompt, the skills it may use, and the
side effects it may cause. The harness runs one role per pipeline stage. A role
never does another role's job - that separation is what keeps the pipeline
auditable.

| Role | Stage | May use skills | Side effects |
|------|-------|----------------|--------------|
| [pm](pm.md) | Idea | `write-prd`, `ci-tests-audit` | none (writes a PRD) |
| [architect](architect.md) | Build | `implement-feature`, `ci-tests-audit` | none (writes a plan) |
| [coder](coder.md) | Coding | `implement-feature`, `ci-tests-audit` | edits files in a worktree |
| [qa](qa.md) | Testing | `qa-changes`, `ci-tests-audit` | none (writes a report) |
| [release](release.md) | Staging / Deploy | `deploy-staging`, `qa-changes` | deploys to staging/prod |
| [sre](sre.md) | Monitor | `monitor-errors`, `qa-changes` | opens `factory` issues |

## Invariants

- Only `coder` edits application source, and only inside an isolated worktree.
- Only `release` deploys; production deploys require a green staging and approval.
- No role runs `git commit`, `git push`, or opens a pull request - the harness
  (`src/factory/engine.py`) owns all git and remote side effects.
- `sre` turns incidents into `factory`-labeled issues, which re-enter the pipeline
  at the Idea stage. That closes the loop.

## Mapping to the pipeline

```
Idea -> Build -> Coding -> Testing -> Staging -> Deploy -> Monitor
 pm    architect  coder      qa       release   release    sre
                                                             |
        +-------------- factory-labeled issue ---------------+
```
