import os
import tempfile
import sqlite3
from datetime import datetime, timedelta

os.environ["TODO_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

from fastapi.testclient import TestClient  # noqa: E402
from backend.main import app  # noqa: E402
from backend.main import init_db  # noqa: E402
from backend.migrations import migrate_sqlite_schema  # noqa: E402

client = TestClient(app)


def test_empty_list():
    assert client.get("/api/tasks").json() == []


def test_add_toggle_delete():
    r = client.post("/api/tasks", json={"title": "  Buy milk "})
    assert r.status_code == 201
    task = r.json()
    assert task["title"] == "Buy milk" and task["completed"] is False

    r = client.patch(f"/api/tasks/{task['id']}/toggle")
    assert r.json()["completed"] is True
    r = client.patch(f"/api/tasks/{task['id']}/toggle")
    assert r.json()["completed"] is False

    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    assert client.get("/api/tasks").json() == []


def test_blank_title_rejected():
    assert client.post("/api/tasks", json={"title": "   "}).status_code == 422


def test_missing_task_404():
    assert client.patch("/api/tasks/9999/toggle").status_code == 404
    assert client.delete("/api/tasks/9999").status_code == 404


def test_home_page_served():
    r = client.get("/")
    assert r.status_code == 200 and "Todo App" in r.text
    assert client.get("/static/app.js").status_code == 200


def make_old_schema_db(rows: int) -> sqlite3.Connection:
    path = os.path.join(tempfile.mkdtemp(), "old.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0)")
    for i in range(rows):
        conn.execute("INSERT INTO tasks (title, completed) VALUES (?, 0)", (f"Old task {i + 1}",))
    conn.commit()
    return conn


def test_migration_adds_created_at_to_old_schema_db():
    conn = make_old_schema_db(1)
    migrate_sqlite_schema(conn)
    conn.commit()
    assert "created_at" in [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    rows = conn.execute("SELECT title, completed, created_at FROM tasks").fetchall()
    assert len(rows) == 1
    title, completed, created_at = rows[0]
    assert title == "Old task 1"
    assert completed == 0
    assert created_at is not None and created_at != ""
    conn.close()


def test_migration_is_idempotent():
    conn = make_old_schema_db(1)
    migrate_sqlite_schema(conn)
    conn.commit()
    first_value = conn.execute("SELECT created_at FROM tasks").fetchone()[0]
    migrate_sqlite_schema(conn)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    title, created_at = conn.execute("SELECT title, created_at FROM tasks").fetchone()
    assert title == "Old task 1"
    assert created_at == first_value
    cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    assert cols.count("created_at") == 1
    conn.close()


def test_migration_backfill_uses_one_timestamp():
    conn = make_old_schema_db(3)
    migrate_sqlite_schema(conn)
    conn.commit()
    distinct = conn.execute("SELECT DISTINCT created_at FROM tasks").fetchall()
    assert len(distinct) == 1
    value = distinct[0][0]
    assert value.endswith("+00:00") is True
    assert datetime.fromisoformat(value).utcoffset() == timedelta(0)
    conn.close()


def test_create_task_stores_and_returns_created_at():
    r = client.post("/api/tasks", json={"title": "Stamp me"})
    assert r.status_code == 201
    body = r.json()
    assert set(body.keys()) == {"id", "title", "completed", "created_at"}
    assert body["created_at"].endswith("+00:00")
    conn = sqlite3.connect(os.environ["TODO_DB_PATH"])
    stored = conn.execute("SELECT created_at FROM tasks WHERE id = ?", (body["id"],)).fetchone()[0]
    conn.close()
    assert stored == body["created_at"]
    assert client.delete(f"/api/tasks/{body['id']}").status_code == 204


def test_list_tasks_includes_created_at():
    ids = []
    for title in ("List A", "List B"):
        r = client.post("/api/tasks", json={"title": title})
        assert r.status_code == 201
        ids.append(r.json()["id"])
    tasks = client.get("/api/tasks").json()
    assert len(tasks) >= 2
    for t in tasks:
        assert isinstance(t["created_at"], str) and t["created_at"] != ""
        assert t["created_at"].endswith("+00:00")
    for task_id in ids:
        assert client.delete(f"/api/tasks/{task_id}").status_code == 204


def test_init_db_can_run_again_without_losing_data():
    r = client.post("/api/tasks", json={"title": "Survives restart"})
    assert r.status_code == 201
    stamp = r.json()["created_at"]
    task_id = r.json()["id"]
    init_db()
    init_db()
    found = [t for t in client.get("/api/tasks").json() if t["id"] == task_id]
    assert len(found) == 1
    assert found[0]["title"] == "Survives restart"
    assert found[0]["created_at"] == stamp
    assert client.delete(f"/api/tasks/{task_id}").status_code == 204
