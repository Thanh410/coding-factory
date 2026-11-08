---
name: ci-tests-audit
description: Audit CI workflows and test suites for correctness, fixture drift, false passes, and measured performance; use for suite or workflow investigations and efficiency changes, rather than ordinary feature testing or a single test failure.
---

# CI and tests audit

Establish which checks still catch real regressions and which costs can be
removed without losing that protection. The outcome may be a verified fix, an
evidence-backed recommendation, or an explicit decision to stop.

Follow the checkout's `AGENTS.md` and contribution rules. Use their current
commands and pinned toolchain, not commands remembered from an earlier audit.
Investigation alone does not authorize edits; this skill does not grant
permission to push or merge. Keep audit notes outside the tracked tree, normally
in a task-specific `/tmp` directory.

## Establish the executed baseline

Pin the baseline SHA and the inspected workflow revision; use an isolated
worktree when comparing code. Record dirty changes and the exact command,
toolchain, and selected tests. An old run is evidence for its executed revision,
even if `main` advances.

Trace workflow triggers, changed-path selection, job dependencies, reusable
actions, package scripts, test discovery, and report gates through to the
commands that actually execute. Include scripts and generated data missing from
import graphs. Check positive and negative selection paths: required files must
be discovered once per intended configuration. A missing explicit test or a
missing required report must not turn green. Optional lanes may skip; preserve
their stated prerequisites.

## Prove the failure or protection

For each candidate, state the expected observable behavior and its owner, then
build the smallest reproduction against production behavior.

- For drift, compare fixtures with current admission requirements, contracts,
  tool versions, and actual entrypoints. Search the whole affected fixture family.
- For a suspicious green test, perturb the behavior in an isolated copy and
  verify the existing assertion detects it. A test may merely repeat its mock or
  hide a subprocess failure. Restore mutations after the experiment.
- For shared setup or pruning, map distinct assertions to retained scenarios.
  Preserve malformed inputs, cancellation, cleanup failure, permissions, and
  meaningful concurrency interactions. A faster run that skips a case or weakens
  its oracle is not an improvement.

## Report

State the baseline SHA, what you ran, what you found, and the evidence. Separate
verified fixes from recommendations. Do not push or merge; hand the change to the
harness.
