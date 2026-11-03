"""Idempotent SQLite schema migrations for the Todo app."""
import sqlite3
from datetime import datetime, timezone


def migrate_sqlite_schema(conn: sqlite3.Connection) -> None:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    if "created_at" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
    ts = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE tasks SET created_at = ? WHERE created_at IS NULL OR created_at = ''",
        (ts,),
    )
