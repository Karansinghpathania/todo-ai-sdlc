"""Baseline Todo app: add, list, complete (toggle), delete."""
import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("TODO_DB_PATH", str(BASE_DIR / "todo.db"))
FRONTEND_DIR = BASE_DIR.parent / "frontend"

app = FastAPI(title="Todo App")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0
            )"""
        )


init_db()


class TaskIn(BaseModel):
    title: str


def row_to_dict(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "title": row["title"], "completed": bool(row["completed"])}


@app.get("/api/tasks")
def list_tasks():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
    return [row_to_dict(r) for r in rows]


@app.post("/api/tasks", status_code=201)
def create_task(task: TaskIn):
    title = task.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title is required")
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO tasks (title) VALUES (?)", (title,))
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_dict(row)


@app.patch("/api/tasks/{task_id}/toggle")
def toggle_task(task_id: int):
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE tasks SET completed = 1 - completed WHERE id = ?", (task_id,)
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Task not found")
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return row_to_dict(row)


@app.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: int):
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Task not found")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
