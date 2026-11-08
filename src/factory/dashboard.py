"""Pass-rate dashboard: render the eval history as a self-contained HTML page.

The eval harness (`factory eval`) produces a pass-rate per run. This module
records those runs and renders them as a static, dependency-free HTML dashboard
(inline CSS + SVG), so a scheduled workflow can publish it to GitHub Pages and
a human can see at a glance whether the pipeline is getting better or worse.

Only the standard library is used.
"""

from __future__ import annotations

import html
import json
import time
from pathlib import Path

DEFAULT_HISTORY = Path("evals/history.json")


def load_history(path: Path) -> list[dict]:
    """Load run records. A missing file is an empty history, not an error."""
    path = Path(path)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("runs", [])
    return list(data)


def append_history(path: Path, run: dict) -> list[dict]:
    """Append one run record and return the full history."""
    path = Path(path)
    runs = load_history(path)
    runs.append(run)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return runs


def run_record(report: dict, *, backend: str = "", when: float | None = None) -> dict:
    """Turn a ``factory eval --json`` report into a history record."""
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(when or time.time())),
        "backend": backend,
        "total": int(report.get("total", 0)),
        "passed": int(report.get("passed", 0)),
        "pass_rate": float(report.get("pass_rate", 0.0)),
        "cases": [
            {"id": str(c.get("id", "")), "passed": bool(c.get("passed"))}
            for c in report.get("cases", [])
        ],
    }


def _sparkline(values: list[float], *, width: int = 640, height: int = 140, pad: int = 12) -> str:
    """A line chart of pass-rate values (0..1) as inline SVG."""
    if not values:
        return f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="no runs"></svg>'
    n = len(values)
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad

    def x(i: int) -> float:
        return pad + (inner_w * i / (n - 1) if n > 1 else inner_w / 2)

    def y(v: float) -> float:
        return pad + inner_h * (1 - max(0.0, min(1.0, v)))

    points = [(x(i), y(v)) for i, v in enumerate(values)]
    poly = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
    base = pad + inner_h
    area = f"{points[0][0]:.1f},{base:.1f} " + poly + f" {points[-1][0]:.1f},{base:.1f}"
    dots = "".join(
        f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="#2563eb"/>' for px, py in points
    )
    # A dashed guide at the 80% line.
    guide_y = y(0.8)
    guide = (
        f'<line x1="{pad}" y1="{guide_y:.1f}" x2="{width - pad}" y2="{guide_y:.1f}" '
        'stroke="#94a3b8" stroke-dasharray="4 4" stroke-width="1"/>'
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        'aria-label="pass-rate over runs" preserveAspectRatio="none">'
        f"{guide}"
        f'<polygon points="{area}" fill="#2563eb" fill-opacity="0.12"/>'
        f'<polyline points="{poly}" fill="none" stroke="#2563eb" stroke-width="2"/>'
        f"{dots}</svg>"
    )


def _case_matrix(runs: list[dict]) -> str:
    """Latest status per case id, as a compact pass/fail grid."""
    latest: dict[str, bool] = {}
    for run in runs:
        for case in run.get("cases", []):
            latest[str(case.get("id", ""))] = bool(case.get("passed"))
    if not latest:
        return "<p class='muted'>No per-case data recorded yet.</p>"
    cells = []
    for case_id, ok in sorted(latest.items()):
        cls = "pass" if ok else "fail"
        mark = "PASS" if ok else "FAIL"
        cells.append(
            f"<li class='{cls}'><span class='dot'></span>"
            f"<code>{html.escape(case_id)}</code><span class='tag'>{mark}</span></li>"
        )
    return "<ul class='cases'>" + "".join(cells) + "</ul>"


def _runs_table(runs: list[dict], limit: int = 15) -> str:
    rows = []
    for run in reversed(runs[-limit:]):
        rate = float(run.get("pass_rate", 0.0))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(run.get('timestamp', '')))}</td>"
            f"<td><code>{html.escape(str(run.get('backend', '') or '-'))}</code></td>"
            f"<td>{int(run.get('passed', 0))}/{int(run.get('total', 0))}</td>"
            f"<td class='num'>{rate:.0%}</td>"
            "</tr>"
        )
    if not rows:
        return "<p class='muted'>No runs recorded yet.</p>"
    return (
        "<table><thead><tr><th>When (UTC)</th><th>Backend</th>"
        "<th>Passed</th><th>Pass-rate</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_dashboard(runs: list[dict], *, title: str = "coding-factory eval dashboard") -> str:
    """Render the whole history as one self-contained HTML document."""
    rates = [float(r.get("pass_rate", 0.0)) for r in runs]
    latest = runs[-1] if runs else {}
    latest_rate = float(latest.get("pass_rate", 0.0))
    trend = ""
    if len(rates) >= 2:
        delta = rates[-1] - rates[-2]
        arrow = "up" if delta > 0 else ("down" if delta < 0 else "flat")
        trend = f"<span class='trend {arrow}'>{delta:+.0%} vs previous</span>"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font: 15px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background: #f8fafc; color: #0f172a; }}
  main {{ max-width: 880px; margin: 0 auto; padding: 32px 20px 64px; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .muted {{ color: #64748b; }}
  .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
           padding: 20px; margin: 16px 0; }}
  .hero {{ display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap; }}
  .big {{ font-size: 56px; font-weight: 700; letter-spacing: -0.02em; }}
  .trend {{ font-size: 13px; padding: 2px 8px; border-radius: 999px; }}
  .trend.up {{ background: #dcfce7; color: #166534; }}
  .trend.down {{ background: #fee2e2; color: #991b1b; }}
  .trend.flat {{ background: #e2e8f0; color: #334155; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ text-align: left; padding: 8px 6px; border-bottom: 1px solid #eef2f7; }}
  th {{ color: #64748b; font-weight: 600; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  ul.cases {{ list-style: none; padding: 0; margin: 0; display: grid;
              grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; }}
  ul.cases li {{ display: flex; align-items: center; gap: 8px; padding: 8px 10px;
                 border: 1px solid #e2e8f0; border-radius: 8px; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; flex: none; }}
  li.pass .dot {{ background: #22c55e; }}
  li.fail .dot {{ background: #ef4444; }}
  .tag {{ margin-left: auto; font-size: 11px; font-weight: 700; letter-spacing: .04em; }}
  li.pass .tag {{ color: #166534; }}
  li.fail .tag {{ color: #991b1b; }}
  footer {{ margin-top: 24px; font-size: 13px; }}
</style>
</head>
<body>
<main>
  <h1>{html.escape(title)}</h1>
  <p class="muted">Golden-task pass-rate over time. Generated {html.escape(_now())}.</p>

  <div class="card">
    <div class="hero">
      <span class="big">{latest_rate:.0%}</span>
      <span class="muted">{int(latest.get("passed", 0))}/{int(latest.get("total", 0))} cases
        &middot; {html.escape(str(latest.get("backend", "") or "no runs yet"))}</span>
      {trend}
    </div>
    {_sparkline(rates)}
    <p class="muted" style="font-size:13px;margin:0">
      {len(runs)} run(s) recorded. Dashed line marks the 80% target.</p>
  </div>

  <div class="card">
    <h2 style="font-size:15px;margin:0 0 12px">Latest status per case</h2>
    {_case_matrix(runs)}
  </div>

  <div class="card">
    <h2 style="font-size:15px;margin:0 0 12px">Recent runs</h2>
    {_runs_table(runs)}
  </div>

  <footer class="muted">_Automation built with OpenHands._</footer>
</main>
</body>
</html>
"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
