import os
import tempfile

os.environ["TODO_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

from fastapi.testclient import TestClient  # noqa: E402
from backend.main import app  # noqa: E402

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
