import sqlite3
from contextlib import contextmanager
from typing import Optional

from .config import config
from .models import Task

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    issue_number INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    agent TEXT NOT NULL,
    status TEXT NOT NULL,
    branch TEXT,
    pr_url TEXT,
    error TEXT
);
"""


class TaskStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path or config.db_path)
        with self._conn() as conn:
            conn.execute(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def is_tracked(self, issue_number: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM tasks WHERE issue_number = ?", (issue_number,)
            ).fetchone()
            return row is not None

    def save(self, task: Task) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO tasks (issue_number, title, agent, status, branch, pr_url, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(issue_number) DO UPDATE SET
                    title = excluded.title,
                    agent = excluded.agent,
                    status = excluded.status,
                    branch = excluded.branch,
                    pr_url = excluded.pr_url,
                    error = excluded.error
                """,
                (
                    task.issue_number,
                    task.title,
                    task.agent.value,
                    task.status.value,
                    task.branch,
                    task.pr_url,
                    task.error,
                ),
            )
