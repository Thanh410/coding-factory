"""Runner: wires intake -> queue -> engine, in one-shot or continuous mode."""

from __future__ import annotations

import logging
import time

from .config import Settings
from .engine import Engine
from .models import Task, TaskState
from .sources import TaskSource
from .state import Store

log = logging.getLogger("factory.runner")


def ingest(store: Store, source: TaskSource) -> int:
    """Fetch from the source and enqueue anything new. Returns count added."""
    added = 0
    for task in source.fetch():
        if store.upsert(task):
            added += 1
            log.info("enqueued %s: %s", task.external_id, task.title)
    return added


def run_once(settings: Settings, store: Store, source: TaskSource, backend: str) -> Task | None:
    """Ingest, then process exactly one pending task. Returns it (or None)."""
    ingest(store, source)
    task = store.next_pending()
    if task is None:
        log.info("no pending tasks")
        return None
    engine = Engine(settings, store, backend)
    return engine.process(task)


def run_loop(
    settings: Settings,
    store: Store,
    source: TaskSource,
    backend: str,
    *,
    interval: int = 60,
    max_tasks: int | None = None,
    stop_when_empty: bool = False,
) -> list[Task]:
    """Continuous worker. Never dies on a single task failure.

    Returns every task it processed, so the caller can inspect the final states
    (a task may end BLOCKED or FAILED even though the loop itself succeeded).
    """
    processed: list[Task] = []
    while True:
        try:
            ingest(store, source)
            task = store.next_pending()
            if task is None:
                if stop_when_empty:
                    log.info("queue empty; exiting (stop_when_empty)")
                    break
                time.sleep(interval)
                continue
            processed.append(Engine(settings, store, backend).process(task))
            if max_tasks is not None and len(processed) >= max_tasks:
                break
        except KeyboardInterrupt:
            log.info("interrupted; shutting down")
            break
        except Exception:
            log.exception("loop iteration failed; continuing in %ss", interval)
            time.sleep(interval)
    return processed


def blocked(store: Store) -> list[Task]:
    return store.by_state(TaskState.BLOCKED)
