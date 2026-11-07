#!/usr/bin/env bash
# race.sh - run the SAME task with two backends and keep the first verified PR.
#
# This is the "Codex vs Antigravity" mode: give both agents the same task in
# separate worktrees, let whichever produces a passing change win, and discard
# the loser. Useful while you decide which backend you trust for a given repo.
#
# Usage:  ./scripts/race.sh <task-id>
# Requires: FACTORY_REPO (or run from the repo), a configured queue.
set -uo pipefail

TASK_ID="${1:?usage: race.sh <task-id>}"
BACKENDS=(codex antigravity)
export FACTORY_WORK_ROOT="$HOME/.factory"

winner=""
for backend in "${BACKENDS[@]}"; do
  echo "== racing backend: $backend =="
  if FACTORY_BACKEND="$backend" factory run-once --backend "$backend" --verbose; then
    echo "== backend $backend produced a verified change =="
    winner="$backend"
    break
  fi
done

if [[ -z "$winner" ]]; then
  echo "no backend produced a verified change for $TASK_ID" >&2
  exit 1
fi
echo "winner: $winner"
