"""Command-line entry point: python -m factory <command> ..."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .adapters import base as adapters
from .config import Settings
from .models import Task
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
    n = run_loop(
        settings,
        store,
        build_source(args.source),
        backend,
        interval=args.interval,
        max_tasks=args.max_tasks,
        stop_when_empty=args.stop_when_empty,
    )
    store.close()
    print(f"processed {n} task(s)")
    return 0


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


def _default_backend() -> str:
    import os

    return os.environ.get("FACTORY_BACKEND", "codex")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))
    handlers = {
        "run-once": cmd_run_once,
        "run-loop": cmd_run_loop,
        "status": cmd_status,
        "enqueue": cmd_enqueue,
        "backends": cmd_backends,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
