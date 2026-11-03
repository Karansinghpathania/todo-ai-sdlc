import os
import tempfile
import sqlite3
from datetime import datetime, timedelta
import pytest

os.environ["TODO_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

from fastapi.testclient import TestClient  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from backend.main import app  # noqa: E402
from backend.main import init_db  # noqa: E402
from backend.main import normalize_and_validate_title  # noqa: E402
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


def test_migration_repairs_missing_timestamps_without_changing_valid_rows():
    original_stamp = "2024-01-01T12:00:00+00:00"
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            "CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL, "
            "completed INTEGER NOT NULL DEFAULT 0, created_at TEXT)"
        )
        conn.executemany(
            "INSERT INTO tasks (id, title, completed, created_at) VALUES (?, ?, ?, ?)",
            [
                (1, "Null timestamp", 0, None),
                (2, "Empty timestamp", 1, ""),
                (3, "Valid timestamp", 1, original_stamp),
            ],
        )
        conn.commit()

        migrate_sqlite_schema(conn)
        conn.commit()
        rows = conn.execute(
            "SELECT id, title, completed, created_at FROM tasks ORDER BY id"
        ).fetchall()
        stamp = rows[0][3]
        assert isinstance(stamp, str) and stamp != ""
        assert datetime.fromisoformat(stamp).utcoffset() == timedelta(0)
        assert rows == [
            (1, "Null timestamp", 0, stamp),
            (2, "Empty timestamp", 1, stamp),
            (3, "Valid timestamp", 1, original_stamp),
        ]

        migrate_sqlite_schema(conn)
        conn.commit()
        assert conn.execute(
            "SELECT id, title, completed, created_at FROM tasks ORDER BY id"
        ).fetchall() == rows
    finally:
        conn.close()


def test_init_db_repairs_empty_timestamp_and_returns_it_in_api(tmp_path, monkeypatch):
    from backend import main

    db_path = tmp_path / "repair.db"
    monkeypatch.setattr(main, "DB_PATH", str(db_path))
    init_db()
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO tasks (title, completed, created_at) VALUES (?, ?, ?)",
                ("Needs timestamp", 1, ""),
            )
    finally:
        conn.close()

    init_db()
    response = client.get("/api/tasks")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 1
    task = tasks[0]
    assert task["title"] == "Needs timestamp"
    assert task["completed"] is True
    assert datetime.fromisoformat(task["created_at"]).utcoffset() == timedelta(0)

    init_db()
    assert client.get("/api/tasks").json() == tasks
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT created_at FROM tasks").fetchone()[0] == task["created_at"]
    finally:
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


def test_create_title_101_chars_rejected():
    r = client.post("/api/tasks", json={"title": "a" * 101})
    assert r.status_code == 422
    assert r.json() == {"detail": "Title must be 100 characters or less"}
    assert all(t["title"] != "a" * 101 for t in client.get("/api/tasks").json())


def test_create_title_100_chars_accepted():
    r = client.post("/api/tasks", json={"title": "a" * 100})
    assert r.status_code == 201
    task = r.json()
    assert task["title"] == "a" * 100 and task["completed"] is False
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204


def test_create_title_length_is_checked_after_trimming():
    r = client.post("/api/tasks", json={"title": "  " + "a" * 100 + "  "})
    assert r.status_code == 201 and r.json()["title"] == "a" * 100
    assert client.delete(f"/api/tasks/{r.json()['id']}").status_code == 204

    r = client.post("/api/tasks", json={"title": "  " + "a" * 101 + "  "})
    assert r.status_code == 422
    assert r.json() == {"detail": "Title must be 100 characters or less"}


def test_blank_title_rejected_with_message():
    r = client.post("/api/tasks", json={"title": "   "})
    assert r.status_code == 422 and r.json() == {"detail": "Title is required"}


def test_normalize_and_validate_title_helper():
    assert normalize_and_validate_title("  hello  ") == "hello"
    assert normalize_and_validate_title("a" * 100) == "a" * 100
    with pytest.raises(HTTPException) as blank:
        normalize_and_validate_title("   ")
    assert blank.value.status_code == 422
    assert blank.value.detail == "Title is required"
    with pytest.raises(HTTPException) as too_long:
        normalize_and_validate_title("a" * 101)
    assert too_long.value.status_code == 422
    assert too_long.value.detail == "Title must be 100 characters or less"


def test_frontend_enforces_title_limit():
    page = client.get("/")
    assert page.status_code == 200
    assert 'maxlength="100"' in page.text and 'maxlength="200"' not in page.text
    js = client.get("/static/app.js").text
    assert js.count("Title must be 100 characters or less") == 1
    assert "if (title.length > 100)" in js
    assert js.index("if (title.length > 100)") < js.index('method: "POST"')
    assert 'inputEl.setAttribute("data-testid", "title-input");' in js
    assert 'addBtn.setAttribute("data-testid", "add-btn");' in js
    assert 'errorEl.setAttribute("data-testid", "error-banner");' in js


def create_task_via_api(title: str) -> dict:
    r = client.post("/api/tasks", json={"title": title})
    assert r.status_code == 201
    return r.json()


def test_edit_task_title_success():
    task = create_task_via_api("Buy mikl")
    r = client.patch(f"/api/tasks/{task['id']}", json={"title": "Buy milk"})
    assert r.status_code == 200
    assert r.json()["id"] == task["id"] and r.json()["title"] == "Buy milk"
    found = next(t for t in client.get("/api/tasks").json() if t["id"] == task["id"])
    assert found["title"] == "Buy milk"
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204


def test_edit_task_title_is_trimmed():
    task = create_task_via_api("Before trim")
    r = client.patch(f"/api/tasks/{task['id']}", json={"title": "  After trim  "})
    assert r.status_code == 200 and r.json()["title"] == "After trim"
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204


def test_edit_missing_task_returns_404():
    r = client.patch("/api/tasks/9999", json={"title": "Anything"})
    assert r.status_code == 404 and r.json() == {"detail": "Task not found"}


def test_edit_title_101_chars_rejected():
    task = create_task_via_api("Original title")
    r = client.patch(f"/api/tasks/{task['id']}", json={"title": "  " + "a" * 101 + "  "})
    assert r.status_code == 422
    assert r.json() == {"detail": "Title must be 100 characters or less"}
    found = next(t for t in client.get("/api/tasks").json() if t["id"] == task["id"])
    assert found["title"] == "Original title"
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204


def test_edit_title_100_chars_accepted():
    task = create_task_via_api("Short title")
    r = client.patch(f"/api/tasks/{task['id']}", json={"title": "a" * 100})
    assert r.status_code == 200 and r.json()["title"] == "a" * 100
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204


def test_edit_blank_title_rejected():
    task = create_task_via_api("Keep me")
    r = client.patch(f"/api/tasks/{task['id']}", json={"title": "   "})
    assert r.status_code == 422 and r.json() == {"detail": "Title is required"}
    found = next(t for t in client.get("/api/tasks").json() if t["id"] == task["id"])
    assert found["title"] == "Keep me"
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204


def test_edit_keeps_completed_and_created_at():
    task = create_task_via_api("Keep fields")
    toggled = client.patch(f"/api/tasks/{task['id']}/toggle")
    assert toggled.status_code == 200 and toggled.json()["completed"] is True
    r = client.patch(f"/api/tasks/{task['id']}", json={"title": "Kept fields"})
    assert r.status_code == 200 and r.json()["title"] == "Kept fields"
    assert r.json()["completed"] is True
    assert r.json()["created_at"] == task["created_at"]
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204


def test_frontend_inline_edit():
    js = client.get("/static/app.js").text
    assert 'const TITLE_TOO_LONG = "Title must be 100 characters or less";' in js
    assert js.count("Title must be 100 characters or less") == 1
    assert js.count("errorEl.textContent = TITLE_TOO_LONG;") == 2
    assert js.count("if (title.length > 100)") == 2
    assert js.count("Please enter a task title") == 2
    assert "editInput.maxLength = 100;" in js
    assert 'cb.setAttribute("data-testid", `toggle-task-${t.id}`);' in js
    assert 'span.setAttribute("data-testid", `task-title-${t.id}`);' in js
    assert 'del.setAttribute("data-testid", `delete-task-${t.id}`);' in js
    assert 'span.addEventListener("click", () => startEdit(t, span));' in js
    save_src = js[js.index("function saveEdit"):js.index("async function load()")]
    assert save_src.index("if (title.length > 100)") < save_src.index('method: "PATCH"')
    assert save_src.index("if (!title)") < save_src.index('method: "PATCH"')


def complete_task_via_api(task_id: int) -> None:
    r = client.patch(f"/api/tasks/{task_id}/toggle")
    assert r.status_code == 200 and r.json()["completed"] is True


def test_filter_active_returns_only_incomplete_tasks():
    open_task = create_task_via_api("Filter open")
    done_task = create_task_via_api("Filter done")
    complete_task_via_api(done_task["id"])
    r = client.get("/api/tasks?filter=active")
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()]
    assert open_task["id"] in ids and done_task["id"] not in ids
    assert all(t["completed"] is False for t in r.json())
    assert client.delete(f"/api/tasks/{open_task['id']}").status_code == 204
    assert client.delete(f"/api/tasks/{done_task['id']}").status_code == 204


def test_filter_completed_returns_only_completed_tasks():
    open_task = create_task_via_api("Filter open")
    done_task = create_task_via_api("Filter done")
    complete_task_via_api(done_task["id"])
    r = client.get("/api/tasks?filter=completed")
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()]
    assert done_task["id"] in ids and open_task["id"] not in ids
    assert all(t["completed"] is True for t in r.json())
    assert client.delete(f"/api/tasks/{open_task['id']}").status_code == 204
    assert client.delete(f"/api/tasks/{done_task['id']}").status_code == 204


def test_filter_all_and_omitted_return_every_task():
    open_task = create_task_via_api("All open")
    done_task = create_task_via_api("All done")
    complete_task_via_api(done_task["id"])
    omitted = client.get("/api/tasks")
    explicit = client.get("/api/tasks?filter=all")
    assert omitted.status_code == 200 and explicit.status_code == 200
    assert omitted.json() == explicit.json()
    ids = [t["id"] for t in omitted.json()]
    assert open_task["id"] in ids and done_task["id"] in ids
    assert ids == sorted(ids)
    assert client.delete(f"/api/tasks/{open_task['id']}").status_code == 204
    assert client.delete(f"/api/tasks/{done_task['id']}").status_code == 204


def test_filter_invalid_value_rejected():
    for value in ("invalidvalue", "", "Active"):
        r = client.get(f"/api/tasks?filter={value}")
        assert r.status_code == 422
        assert r.json() == {"detail": "Filter must be all, active or completed"}


def test_clear_completed_removes_only_completed_tasks():
    open_task = create_task_via_api("Clear open")
    first_done = create_task_via_api("Clear done 1")
    second_done = create_task_via_api("Clear done 2")
    complete_task_via_api(first_done["id"])
    complete_task_via_api(second_done["id"])
    r = client.delete("/api/tasks/completed")
    assert r.status_code == 204 and r.content == b""
    assert client.get("/api/tasks?filter=completed").json() == []
    ids = [t["id"] for t in client.get("/api/tasks").json()]
    assert open_task["id"] in ids
    assert first_done["id"] not in ids and second_done["id"] not in ids
    assert client.delete(f"/api/tasks/{open_task['id']}").status_code == 204


def test_clear_completed_route_is_not_parsed_as_task_id():
    r = client.delete("/api/tasks/completed")
    assert r.status_code == 204
    task = create_task_via_api("Delete by id still works")
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    r = client.delete("/api/tasks/9999")
    assert r.status_code == 404 and r.json() == {"detail": "Task not found"}
    delete_paths = [
        route.path for route in app.routes
        if getattr(route, "methods", None) and "DELETE" in route.methods
    ]
    assert delete_paths.index("/api/tasks/completed") < delete_paths.index("/api/tasks/{task_id}")


def test_frontend_filter_and_clear_controls():
    js = client.get("/static/app.js").text
    assert 'let currentFilter = "all";' in js
    assert '["all", "active", "completed"].forEach((name) => {' in js
    assert 'const path = currentFilter === "all" ? "/api/tasks" : `/api/tasks?filter=${currentFilter}`;' in js
    assert "render(await api(path));" in js
    assert "?filter=all" not in js
    assert 'clearBtn.textContent = "Clear completed";' in js
    assert 'clearBtn.addEventListener("click", () => act(() => api("/api/tasks/completed", { method: "DELETE" })));' in js
    assert js.count("listEl.before(filterBar);") == 1
    assert js.count("async function load()") == 1
    render_src = js[js.index("function render(tasks)"):js.index("function startEdit")]
    assert "filterBar" not in render_src and "clearBtn" not in render_src
