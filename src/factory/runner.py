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
