"""Command-line entry point: python -m factory <command> ..."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .adapters import base as adapters
from .config import Settings
from .models import Task, TaskState
from .runner import run_loop, run_once
from .sources import build_source
from .state import Store


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--backend", default=None, help="agent backend (codex|antigravity)")
    parser.add_argument("--source", default=None, help="intake source (json|markdown|github)")
    parser.add_argument("--verbose", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="factory", description="24/7 automated coding factory")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run-once", help="ingest and process one task, then exit")
    _common(r)

    loop = sub.add_parser("run-loop", help="continuous worker (24/7)")
    _common(loop)
    loop.add_argument("--interval", type=int, default=60, help="seconds to wait when idle")
    loop.add_argument("--max-tasks", type=int, default=None, help="stop after N tasks")
    loop.add_argument(
        "--stop-when-empty",
        action="store_true",
        help="exit when the queue is empty (for cron/scheduled runs)",
    )

    s = sub.add_parser("status", help="print queue status")
    _common(s)

    e = sub.add_parser("enqueue", help="add one task to the queue")
    _common(e)
    e.add_argument("--id", required=True)
    e.add_argument("--title", required=True)
    e.add_argument("--body", default="")
    e.add_argument("--label", action="append", default=[])

    sub.add_parser("backends", help="list available agent backends")
    sub.add_parser("models", help="list curated free models (and their availability)")

    ev = sub.add_parser("eval", help="run golden tasks through the pipeline and report pass-rate")
    _common(ev)
    ev.add_argument(
        "--suite", default="evals/cases", help="suite dir of *.json cases, or one JSON file"
    )
    ev.add_argument("--json", action="store_true", help="emit a machine-readable report")
    ev.add_argument(
        "--min-pass-rate",
        type=float,
        default=0.0,
        help="exit non-zero when the pass-rate is below this (0..1)",
    )
    ev.add_argument(
        "--record",
        action="store_true",
        help="append this run to the pass-rate history (see `factory dashboard`)",
    )
    ev.add_argument(
        "--history",
        default="evals/history.json",
        help="history file to append to with --record (default evals/history.json)",
    )

    dash = sub.add_parser("dashboard", help="render the pass-rate history as an HTML page")
    _common(dash)
    dash.add_argument(
        "--history",
        default="evals/history.json",
        help="history file produced by `factory eval --record`",
    )
    dash.add_argument(
        "--out",
        default="dashboard/index.html",
        help="where to write the HTML page (default dashboard/index.html)",
    )

    mon = sub.add_parser("monitor", help="poll Sentry/uptime and open factory issues")
    _common(mon)
    mon.add_argument("--dry-run", action="store_true", help="print what would be opened")
    return p


def _settings_and_store() -> tuple[Settings, Store]:
    settings = Settings.from_env()
    settings.ensure_dirs()
    return settings, Store(settings.db_path)


def cmd_run_once(args: argparse.Namespace) -> int:
    settings, store = _settings_and_store()
    backend = args.backend or _default_backend()
    task = run_once(settings, store, build_source(args.source), backend)
    store.close()
    if task is None:
        print("no pending tasks")
        return 0
    suffix = " (merged)" if task.merged else ""
    print(f"{task.external_id}: {task.state.value} {task.pr_url or task.branch}{suffix}".strip())
    return 0 if task.state.value in {"pr_open", "merged", "done"} else 1


def cmd_run_loop(args: argparse.Namespace) -> int:
    settings, store = _settings_and_store()
    backend = args.backend or _default_backend()
    processed = run_loop(
        settings,
        store,
        build_source(args.source),
        backend,
        interval=args.interval,
        max_tasks=args.max_tasks,
        stop_when_empty=args.stop_when_empty,
    )
    store.close()
    print(f"processed {len(processed)} task(s)")

    # A run that processed nothing is idle, not a failure: the scheduled loop is
    # expected to find an empty queue most of the time. But if a task reached a
    # terminal *failure* state, surface it as a non-zero exit so CI turns red
    # instead of reporting a silent green.
    failed = [t for t in processed if t.state in (TaskState.BLOCKED, TaskState.FAILED)]
    for task in failed:
        first_line = task.detail.splitlines()[0] if task.detail else ""
        print(f"FAILED {task.external_id}: {task.state.value} - {first_line}")
    return 1 if failed else 0


def cmd_status(args: argparse.Namespace) -> int:
    _settings, store = _settings_and_store()
    print(json.dumps(store.counts(), indent=2, sort_keys=True))
    store.close()
    return 0


def cmd_enqueue(args: argparse.Namespace) -> int:
    _settings, store = _settings_and_store()
    task = Task(external_id=args.id, title=args.title, body=args.body, labels=args.label)
    added = store.upsert(task)
    store.close()
    print("enqueued" if added else "already present")
    return 0


def cmd_backends(_: argparse.Namespace) -> int:
    for name in adapters.available():
        adapter = adapters.build(name)
        print(f"{name:12s} available={adapter.is_available()}")
    return 0


def cmd_models(_: argparse.Namespace) -> int:
    """List the curated $0 tool-capable models and how to use them."""
    from . import providers

    configured = providers.resolve("openrouter") is not None
    print("Free models (OpenRouter, $0, tool calling supported):\n")
    for model in providers.FREE_MODELS:
        print(f"  {model}")
    print(
        "\nUse them with a chain alias (needs OPENROUTER_API_KEY):\n"
        "  export FACTORY_BACKEND=llm\n"
        "  export FACTORY_LLM_CHAIN=free          # all of the above, in order\n"
        "  export FACTORY_LLM_CHAIN=free:3        # just the top 3\n"
        "  export FACTORY_LLM_CHAIN=free,ollama   # free first, then local Ollama\n"
    )
    print(f"OPENROUTER_API_KEY set: {configured}")
    print("Tip: `factory backends` shows whether the llm backend is available.")
    return 0


def _default_backend() -> str:
    import os

    return os.environ.get("FACTORY_BACKEND", "codex")


def cmd_eval(args: argparse.Namespace) -> int:
    """Run the golden-task suite and report the pass-rate."""
    from pathlib import Path

    from . import eval as eval_mod

    backend = args.backend or _default_backend()
    try:
        cases = eval_mod.load_suite(Path(args.suite))
    except FileNotFoundError as exc:
        print(str(exc))
        return 2
    if not cases:
        print(f"no cases found in {args.suite}")
        return 2

    result = eval_mod.run_suite(cases, backend)
    report = eval_mod.as_dict(result)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(eval_mod.format_report(result))
    if args.record:
        from pathlib import Path

        from . import dashboard as dash_mod

        dash_mod.append_history(
            Path(args.history), dash_mod.run_record(report, backend=backend)
        )
        print(f"recorded run in {args.history}")
    if result.pass_rate < args.min_pass_rate:
        print(f"pass-rate {result.pass_rate:.0%} is below the required {args.min_pass_rate:.0%}")
        return 1
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Render the eval history as a static HTML page."""
    from pathlib import Path

    from . import dashboard as dash_mod

    runs = dash_mod.load_history(Path(args.history))
    if not runs:
        print(f"no runs in {args.history}; run `factory eval --record` first")
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dash_mod.render_dashboard(runs), encoding="utf-8")
    print(f"wrote {out} ({len(runs)} run(s))")
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    """Poll Sentry and uptime, then open GitHub issues for what is new."""
    from . import monitor as monitor_mod

    cfg = monitor_mod.MonitorConfig.from_env()
    if not cfg.sentry_enabled and not cfg.uptime_enabled:
        print("no monitors configured (set SENTRY_AUTH_TOKEN/ORG/PROJECT or UPTIME_URL)")
        return 2

    created = monitor_mod.run_monitor(cfg, dry_run=args.dry_run)
    if not created:
        print("nothing new to report")
        return 0
    for item in created:
        print(item)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))
    handlers = {
        "run-once": cmd_run_once,
        "run-loop": cmd_run_loop,
        "status": cmd_status,
        "enqueue": cmd_enqueue,
        "backends": cmd_backends,
        "models": cmd_models,
        "eval": cmd_eval,
        "dashboard": cmd_dashboard,
        "monitor": cmd_monitor,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
