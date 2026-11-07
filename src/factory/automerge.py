"""Auto-merge: merge a factory PR only after its CI checks go green.

Design rules that keep this safe:

- Opt-in. Nothing here runs unless ``FACTORY_AUTO_MERGE`` is enabled.
- The factory's own local verification gate has already passed before we get
  here; this module waits for the *repository's* CI (GitHub Actions etc.).
- Merging only happens when every relevant check has completed successfully.
  A failing, cancelled, timed-out, or merely pending state never merges - it
  leaves the PR open for a human.
- The status classification is a pure function so it is unit-testable without
  touching GitHub.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import StrEnum

from .proc import run


class MergeDecision(StrEnum):
    MERGE = "merge"
    WAIT = "wait"
    FAIL = "fail"
    UNKNOWN = "unknown"


@dataclass
class MergeOutcome:
    merged: bool
    detail: str


# Terminal GitHub check states. `success`/`skipped`/`neutral` are acceptable;
# everything else blocks a merge.
_PASS_STATES = {"success", "skipped", "neutral"}
_FAIL_STATES = {"failure", "error", "timed_out", "action_required", "cancelled"}
_PENDING_STATES = {"queued", "in_progress", "pending", "requested", "waiting", "expected"}


def classify(states: list[str], *, require_checks: bool) -> MergeDecision:
    """Decide whether to merge given the set of check states on the PR.

    Fails closed: any unknown state is treated as not-yet-safe to merge.
    """
    if not states:
        # No CI configured. Merging without any signal is dangerous, so only
        # proceed when the operator explicitly relaxed the requirement.
        return MergeDecision.MERGE if not require_checks else MergeDecision.WAIT
    if any(s in _FAIL_STATES for s in states):
        return MergeDecision.FAIL
    if all(s in _PASS_STATES for s in states):
        return MergeDecision.MERGE
    if any(s in _PENDING_STATES for s in states):
        return MergeDecision.WAIT
    return MergeDecision.UNKNOWN


def wait_and_merge(
    *,
    pr_number: int,
    repo: str,
    base: str,
    method: str,
    timeout: int,
    poll: int,
    require_checks: bool,
) -> MergeOutcome:
    """Poll CI until it resolves, then merge. Never merges on failure/timeout."""
    deadline = time.monotonic() + timeout
    last = "no status yet"
    while time.monotonic() < deadline:
        states = _check_states(pr_number, repo)
        decision = classify(states, require_checks=require_checks)

        if decision is MergeDecision.MERGE:
            return _merge(pr_number, repo, method)
        if decision is MergeDecision.FAIL:
            return MergeOutcome(False, f"CI failed: {sorted(set(states))}")
        if decision is MergeDecision.UNKNOWN:
            return MergeOutcome(False, f"unrecognised check states: {sorted(set(states))}")

        last = f"waiting on: {sorted(set(states))}" if states else "no checks reported yet"
        time.sleep(poll)

    return MergeOutcome(False, f"CI did not go green within {timeout}s ({last})")


# --------------------------------------------------------------------------- #
# GitHub access: gh CLI when available, REST API otherwise.
# --------------------------------------------------------------------------- #
def _use_gh() -> bool:
    code, _ = run(["sh", "-c", "command -v gh"], timeout=10)
    return code == 0


def _check_states(pr_number: int, repo: str) -> list[str]:
    if _use_gh():
        return _check_states_gh(pr_number, repo)
    return _check_states_api(pr_number, repo)


def _check_states_gh(pr_number: int, repo: str) -> list[str]:
    code, out = run(
        ["gh", "pr", "checks", str(pr_number), "--repo", repo, "--json", "state"],
        timeout=60,
    )
    if code != 0:
        # `gh pr checks` exits non-zero when checks are failing/pending, but it
        # still prints JSON. Only treat empty output as "no data".
        out = out.strip()
        if not out.startswith("["):
            return []
    try:
        return [c["state"].lower() for c in json.loads(out)]
    except (ValueError, KeyError, TypeError):
        return []


def _check_states_api(pr_number: int, repo: str) -> list[str]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return []
    # Check-runs are attached to the PR head SHA; fetch it first.
    sha = _pr_head_sha(pr_number, repo, token)
    if not sha:
        return []
    url = f"https://api.github.com/repos/{repo}/commits/{sha}/check-runs"
    data = _api_get(url, token)
    if not data:
        return []
    states = []
    for run_item in data.get("check_runs", []):
        if run_item.get("status") != "completed":
            states.append("pending")
        else:
            states.append((run_item.get("conclusion") or "unknown").lower())
    # Combine with legacy commit statuses for older setups.
    states += _legacy_statuses(sha, repo, token)
    return states


def _legacy_statuses(sha: str, repo: str, token: str) -> list[str]:
    data = _api_get(f"https://api.github.com/repos/{repo}/commits/{sha}/status", token)
    if not data:
        return []
    return [s.get("state", "unknown").lower() for s in data.get("statuses", [])]


def _pr_head_sha(pr_number: int, repo: str, token: str) -> str:
    data = _api_get(f"https://api.github.com/repos/{repo}/pulls/{pr_number}", token)
    return (data or {}).get("head", {}).get("sha", "")


def _api_get(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
        return {}


def _merge(pr_number: int, repo: str, method: str) -> MergeOutcome:
    if _use_gh():
        code, out = run(
            ["gh", "pr", "merge", str(pr_number), "--repo", repo, f"--{method}", "--delete-branch"],
            timeout=120,
        )
        if code == 0:
            return MergeOutcome(True, f"merged via gh ({method})")
        return MergeOutcome(False, f"gh pr merge failed: {out.strip()[:400]}")

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return MergeOutcome(False, "no gh CLI and no GITHUB_TOKEN; cannot merge")
    payload = json.dumps({"merge_method": method}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/pulls/{pr_number}/merge",
        data=payload,
        method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode())
        return MergeOutcome(bool(body.get("merged")), body.get("message", "merged"))
    except urllib.error.HTTPError as exc:
        return MergeOutcome(False, f"merge API failed: {exc.code} {exc.read()[:300]!r}")
