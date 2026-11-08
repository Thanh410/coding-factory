"""SQLite-backed task queue and state store.

Durable state is essential for a 24/7 loop: it lets the runner resume after a
crash, dedupe tasks, and expose status without scanning git.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .models import Task, TaskState

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    external_id TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    repo_url    TEXT NOT NULL DEFAULT '',
    base_branch TEXT NOT NULL DEFAULT 'main',
    labels      TEXT NOT NULL DEFAULT '[]',
    state       TEXT NOT NULL DEFAULT 'pending',
    attempts    INTEGER NOT NULL DEFAULT 0,
    branch      TEXT NOT NULL DEFAULT '',
    pr_url      TEXT NOT NULL DEFAULT '',
    pr_number   INTEGER NOT NULL DEFAULT 0,
    merged      INTEGER NOT NULL DEFAULT 0,
    detail      TEXT NOT NULL DEFAULT '',
    spec        TEXT NOT NULL DEFAULT '',
    updated_at  REAL NOT NULL
);
"""


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after the initial schema (idempotent)."""
        existing = {row["name"] for row in self.conn.execute("PRAGMA table_info(tasks)")}
        additions = {
            "pr_number": "INTEGER NOT NULL DEFAULT 0",
            "merged": "INTEGER NOT NULL DEFAULT 0",
            "spec": "TEXT NOT NULL DEFAULT ''",
        }
        for column, ddl in additions.items():
            if column not in existing:
                self.conn.execute(f"ALTER TABLE tasks ADD COLUMN {column} {ddl}")

    def close(self) -> None:
        self.conn.close()

    def upsert(self, task: Task) -> bool:
        """Insert a task if new. Returns True when it was newly added."""
        cur = self.conn.execute("SELECT 1 FROM tasks WHERE external_id=?", (task.external_id,))
        if cur.fetchone():
            return False
        self.conn.execute(
            """INSERT INTO tasks
               (external_id,title,body,repo_url,base_branch,labels,state,attempts,
                branch,pr_url,pr_number,merged,detail,spec,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task.external_id,
                task.title,
                task.body,
                task.repo_url,
                task.base_branch,
                json.dumps(task.labels),
                task.state.value,
                task.attempts,
                task.branch,
                task.pr_url,
                task.pr_number,
                int(task.merged),
                task.detail,
                task.spec,
                time.time(),
            ),
        )
        self.conn.commit()
        return True

    def save(self, task: Task) -> None:
        self.conn.execute(
            """UPDATE tasks
               SET state=?,attempts=?,branch=?,pr_url=?,pr_number=?,merged=?,
                   detail=?,spec=?,updated_at=?
               WHERE external_id=?""",
            (
                task.state.value,
                task.attempts,
                task.branch,
                task.pr_url,
                task.pr_number,
                int(task.merged),
                task.detail,
                task.spec,
                time.time(),
                task.external_id,
            ),
        )
        self.conn.commit()

    def get(self, external_id: str) -> Task | None:
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE external_id=?", (external_id,)
        ).fetchone()
        return _row_to_task(row) if row else None

    def next_pending(self) -> Task | None:
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE state=? ORDER BY updated_at LIMIT 1",
            (TaskState.PENDING.value,),
        ).fetchone()
        return _row_to_task(row) if row else None

    def by_state(self, state: TaskState) -> list[Task]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE state=? ORDER BY updated_at", (state.value,)
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT state, COUNT(*) c FROM tasks GROUP BY state").fetchall()
        return {r["state"]: r["c"] for r in rows}


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        external_id=row["external_id"],
        title=row["title"],
        body=row["body"],
        repo_url=row["repo_url"],
        base_branch=row["base_branch"],
        labels=json.loads(row["labels"]),
        state=TaskState(row["state"]),
        attempts=row["attempts"],
        branch=row["branch"],
        pr_url=row["pr_url"],
        pr_number=row["pr_number"],
        merged=bool(row["merged"]),
        detail=row["detail"],
        spec=row["spec"],
    )
