# Implementation Plan — KAN-1

## 1. Overview (epic key, goal, scope, out of scope)

- **Epic:** KAN-1 — Improve task lifecycle UX (edit, validate, filter/clear) and add created_at with idempotent migration
- **Goal:** Enhance the Todo app so users can:
  1) edit task titles,
  2) have a single shared title validation rule (**max 100 characters after trimming**) for create + edit (with negative tests),
  3) filter tasks (all/active/completed) and clear completed, and
  4) persist a `created_at` timestamp in SQLite using an **idempotent migration** executed on startup.

- **In scope (repo-grounded):**
  - Backend FastAPI + SQLite: `backend/main.py`
  - New migration module: `backend/migrations.py` (called from `init_db()`)
  - Frontend behavior: `frontend/app.js`
  - Allowed markup change: `frontend/index.html` (e.g., `maxlength=100`, filter/clear controls)
  - Tests: `tests/test_api.py`

- **Out of scope (per Epic description + user constraints):**
  - Introducing external migration tools/frameworks (Alembic, etc.)
  - Changing DB engine away from SQLite
  - AuthN/AuthZ
  - Any “fixes” to `frontend/index.html` display/content beyond the allowed changes (note: index may appear as plain text in code index; do not treat that as a gap)

- **Existing artifacts (from run inputs):**
  - Jira: KAN-1 through KAN-15 exist.
  - GitHub: user reports PR #1 + branch `docs/KAN-1-implementation-plan` + file `docs/implementation-plan.md` exist.
    **Repo tree on `main` shows no `docs/` folder**, so this plan proposes an **update** (not a duplicate) and targets `docs/implementation-plan.md` once we move to STEP 2 (after approval).

## 2. Story-by-story plan

> Shared constraints applied everywhere:
> - Title limit is **100 characters after trimming** for **create and edit**.
> - Blank title returns **422** with `{"detail":"Title is required"}` (already implemented for create).
> - Missing task returns **404** with `{"detail":"Task not found"}` (already implemented for toggle/delete; must match for edit).
> - Filtering invalid value returns **422** with `{"detail":"Filter must be all, active or completed"}`.
> - **Route ordering:** declare `DELETE /api/tasks/completed` **before** `DELETE /api/tasks/{task_id}` to avoid FastAPI path matching causing 422.
> - **Migration rules:** SQLite cannot `ADD COLUMN` with non-constant default; migration must:
>   - check `PRAGMA table_info(tasks)` before altering,
>   - add `created_at` with **no default**,
>   - backfill existing rows in the same migration run,
>   - set `created_at` explicitly on insert,
>   - use `datetime.now(timezone.utc).isoformat()`,
>   - be kept in `backend/migrations.py` and called from `init_db()`.

### Story KAN-2 — Add created_at column to tasks with an idempotent SQLite migration

- **Objective:** Add `created_at` to the tasks table without breaking existing DBs and ensure new tasks get a UTC ISO timestamp.
- **Files to change/create (real paths):**
  - **Create:** `backend/migrations.py`
  - **Update:** `backend/main.py`
  - **Update:** `tests/test_api.py`

- **Ordered implementation steps:**
  1. **Create `backend/migrations.py`** with a function (e.g., `run_migrations(conn: sqlite3.Connection) -> None`) that:
     - runs `PRAGMA table_info(tasks)` and detects if `created_at` exists.
     - if missing:
       - executes `ALTER TABLE tasks ADD COLUMN created_at TEXT`
       - backfills existing rows: `UPDATE tasks SET created_at = ? WHERE created_at IS NULL OR created_at = ''`
         - value: `datetime.now(timezone.utc).isoformat()`
     - does nothing if column already exists (idempotent).
  2. **Update `init_db()` in `backend/main.py`:**
     - keep `CREATE TABLE IF NOT EXISTS ...` as-is (but it will need `created_at` for fresh DBs). Because existing DBs might already exist, do:
       - Create table with the **new schema** if it doesn’t exist (include `created_at TEXT` but no default).
       - Call `run_migrations(conn)` after ensuring table exists.
  3. **Update `create_task()` in `backend/main.py`:**
     - compute `created_at = datetime.now(timezone.utc).isoformat()`
     - insert both `title` and `created_at` explicitly:
       - `INSERT INTO tasks (title, created_at) VALUES (?, ?)`
  4. **Update `row_to_dict()` in `backend/main.py`:**
     - include `"created_at": row["created_at"]` (ensure existing select includes the column post-migration).
  5. **Tests (`tests/test_api.py`):**
     - Extend `test_add_toggle_delete()` (or add new tests) to assert created task JSON includes a non-empty `"created_at"`.
     - Add an idempotency test by calling `backend.main.init_db()` a second time (or importing app in a way that triggers it) and verifying no exception occurs and subsequent calls still work.

- **Mapping to acceptance criteria (KAN-2):**
  - AC1 (update schema without dropping data): covered by `PRAGMA table_info` check + `ALTER TABLE` + no destructive actions.
  - AC2 (idempotent on subsequent starts): covered by “column exists => no-op” branch + test that reruns migration/init.
  - AC3 (created_at included in returned tasks): covered by explicit insert + `row_to_dict()` + tests.

- **Effort:** **M** (SQLite migration + careful startup behavior)

---

### Story KAN-3 — Enforce maximum title length validation on create (and later reuse for edit) with negative tests

- **Objective:** Enforce **one** title validation rule for create (and later edit): trimmed title must be non-empty and length <= 100; add negative tests.
- **Files to change/create (real paths):**
  - **Update:** `backend/main.py`
  - **Update:** `frontend/app.js`
  - **Update:** `frontend/index.html` (allowed: change maxlength 200→100; repo content currently minimal, but file exists)
  - **Update:** `tests/test_api.py`

- **Ordered implementation steps:**
  1. **Backend: centralize validation** in `backend/main.py`:
     - Add a helper (e.g., `def normalize_and_validate_title(raw: str) -> str:`) that:
       - `title = raw.strip()`
       - if blank: raise `HTTPException(422, "Title is required")`
       - if `len(title) > 100`: raise `HTTPException(422, "Title must be 100 characters or less")`
       - return `title`
     - Update `create_task()` to call helper instead of inline `.strip()` and blank-only check.
  2. **Frontend: enforce 100 in UI**:
     - Update `frontend/index.html` to set the title input `maxlength="100"` (binding note requirement).
     - In `frontend/app.js`, keep trimming before submit (`inputEl.value.trim()`) and add a pre-check:
       - if `title.length > 100`: show error (either same backend message or a UI-friendly message) and do not call API.
       - Note: backend remains source of truth; UI check is for UX.
  3. **Tests (`tests/test_api.py`):**
     - Add test: POST with `"a"*101` (or 200 per Jira text, but must exceed 100) returns 422 and **exact** `detail == "Title must be 100 characters or less"`.
     - Add boundary test: POST with `"a"*100` returns 201 and title is unchanged (post-trim).
     - Preserve and assert existing blank-title test still returns 422 and (optionally) exact detail.

- **Mapping to acceptance criteria (KAN-3):**
  - AC1 (too long rejected with explicit message): backend helper + tests.
  - AC2 (exactly max length accepted): boundary test.
  - AC3 (blank title still rejected with existing message): helper preserves existing behavior + test.

- **Effort:** **S** (simple validation + tests + maxlength)

---

### Story KAN-4 — Edit task title (API + UI) using existing list view and shared validation rules

- **Objective:** Allow updating a task title with PATCH, reusing the exact same validation as create; provide UI editing in the list.
- **Files to change/create (real paths):**
  - **Update:** `backend/main.py`
  - **Update:** `frontend/app.js`
  - **Update (if needed/allowed for controls):** `frontend/index.html`
  - **Update:** `tests/test_api.py`

- **Ordered implementation steps:**
  1. **Backend: add PATCH endpoint** in `backend/main.py`:
     - Define `@app.patch("/api/tasks/{task_id}")` that accepts `TaskIn` (already defined) or a new model if needed.
     - Validate title using the shared helper from KAN-3 (trim + required + <=100).
     - Execute update:
       - `UPDATE tasks SET title = ? WHERE id = ?`
       - if `rowcount == 0`: raise 404 `"Task not found"`
     - Return the updated row via `SELECT * FROM tasks WHERE id = ?` and `row_to_dict()`.
  2. **Frontend: inline edit UX** in `frontend/app.js`:
     - In `render(tasks)`, replace the title span or augment it:
       - Add an “Edit” button per task (simplest, lowest risk).
       - On edit click: swap span with an input prefilled with title, plus “Save” and “Cancel”.
       - Enforce trim + 100 limit on save before calling API.
       - Call `PATCH /api/tasks/{id}` with JSON `{title: <new>}` and reload list on success.
  3. **Tests (`tests/test_api.py`):**
     - Add test for successful edit (create then patch and assert title updated).
     - Add test for missing id edit returns 404 with `detail == "Task not found"`.
     - Add test for blank title edit returns 422 with `detail == "Title is required"`.
     - Add test for too-long edit returns 422 with `detail == "Title must be 100 characters or less"`.

- **Mapping to acceptance criteria (KAN-4):**
  - AC1: covered by edit success test and backend PATCH.
  - AC2: covered by 404 test.
  - AC3: UI sends PATCH and reloads list (manual verification + code change; API tests cover correctness).
  - AC4: too-long message identical to create (shared helper + test).

- **Effort:** **M** (UI state handling + new endpoint + tests)

---

### Story KAN-5 — Add filtering (all/active/completed) and clear completed tasks (API + UI)

- **Objective:** Add server-side filter query param (optional) and clear-completed endpoint; update UI with filter selection and clear button.
- **Files to change/create (real paths):**
  - **Update:** `backend/main.py`
  - **Update:** `frontend/app.js`
  - **Update (allowed):** `frontend/index.html`
  - **Update:** `tests/test_api.py`

- **Ordered implementation steps:**
  1. **Backend: filtering in `GET /api/tasks`** (`backend/main.py`):
     - Update `list_tasks()` signature to accept optional query param, e.g. `filter: str = "all"` or `filter: str | None = None`.
       - Per binding note: if any query parameter is added, it **must be optional**. Recommended behavior:
         - if `filter is None` => treat as `"all"`.
         - else validate: only `"all"`, `"active"`, `"completed"`.
     - Apply SQL:
       - all: `SELECT * FROM tasks ORDER BY id`
       - active: `SELECT * FROM tasks WHERE completed = 0 ORDER BY id`
       - completed: `SELECT * FROM tasks WHERE completed = 1 ORDER BY id`
     - Invalid => raise `HTTPException(422, detail="Filter must be all, active or completed")`.
  2. **Backend: clear completed** in `backend/main.py`:
     - Add endpoint: `@app.delete("/api/tasks/completed", status_code=204)` that executes `DELETE FROM tasks WHERE completed = 1`.
     - **Important:** Place this route **before** `@app.delete("/api/tasks/{task_id}")` to avoid FastAPI matching `/completed` as `{task_id}` and throwing 422.
  3. **Frontend UI** (`frontend/app.js` + possibly `frontend/index.html`):
     - Add filter controls (e.g., three buttons or a select) that set a current filter state.
     - Update `load()` to request `/api/tasks?filter=<state>` (or omit param for “all”).
     - Add “Clear completed” control that calls `DELETE /api/tasks/completed` and reloads.
  4. **Tests (`tests/test_api.py`):**
     - Create tasks, toggle some to completed.
     - Assert:
       - `GET /api/tasks?filter=active` returns only `completed == False`
       - `GET /api/tasks?filter=completed` returns only `completed == True`
       - `GET /api/tasks?filter=invalid` returns 422 and exact detail message.
       - `DELETE /api/tasks/completed` returns 204 and subsequent `GET /api/tasks?filter=completed` returns `[]`.
     - Add a regression test that `DELETE /api/tasks/completed` does not produce 422 (implicitly verifies route order correctness).

- **Mapping to acceptance criteria (KAN-5):**
  - AC1/AC2: filter query with correct subsets + tests.
  - AC3: clear completed endpoint + tests.
  - AC4: UI controls to filter and clear (manual verification; API behavior covered by tests).

- **Effort:** **M** (API + UI + route ordering + tests)

## 3. Sequence and dependencies (recommended order; one commit per story)

Per binding design notes, recommended implementation order is:

1. **KAN-2 (created_at migration)**
2. **KAN-3 (title validation 100 + negative tests + frontend maxlength)**
3. **KAN-4 (edit title API/UI/tests)** depends on shared validation from KAN-3
4. **KAN-5 (filter + clear completed)** independent but touches routing; do last to reduce endpoint churn

**Commit discipline:** one commit per story, in the order above.

## 4. Data changes (what changes, and how existing data stays valid)

- **Schema change:** add `created_at TEXT` column to `tasks`.
- **Idempotent migration approach (SQLite-safe):**
  - On startup, query `PRAGMA table_info(tasks)` to determine whether `created_at` exists.
  - If missing:
    - `ALTER TABLE tasks ADD COLUMN created_at TEXT` (no default; SQLite constraint)
    - Backfill existing rows within the same migration run to a UTC ISO string using `datetime.now(timezone.utc).isoformat()`.
- **Existing data validity:**
  - No rows are dropped or rewritten beyond adding/backfilling `created_at`.
  - Existing tasks keep `id`, `title`, `completed` unchanged.
- **Forward data validity:**
  - New inserts must set `created_at` explicitly in `INSERT` to avoid NULLs.

## 5. Test strategy (existing test framework for unit/API tests, Playwright for end-to-end, which stories need which)

- **Existing framework:** `pytest` with `fastapi.testclient.TestClient` (`tests/test_api.py`).
- **API-focused tests (primary):**
  - **KAN-2:** assert `created_at` present; ensure migration/init idempotency doesn’t crash across repeated init/start usage.
  - **KAN-3:** POST validation tests for blank and >100 (after trim) and boundary at 100.
  - **KAN-4:** PATCH edit tests for 200/404/422(blank)/422(too-long).
  - **KAN-5:** filter query tests, invalid filter 422 exact message, clear-completed 204 + verification.
- **End-to-end tests:** Playwright is **not** present in repo (no Playwright config or tests found). Do not add Playwright unless separately requested; keep scope to existing pytest suite.

## 6. Risks and mitigations

- **Risk: FastAPI route conflict causing 422** (`/api/tasks/{task_id}` vs `/api/tasks/completed`)
  - Mitigation: define `DELETE /api/tasks/completed` **before** `DELETE /api/tasks/{task_id}` in `backend/main.py`; add regression test hitting `/api/tasks/completed`.
- **Risk: SQLite migration pitfalls (non-constant defaults)**
  - Mitigation: add `created_at` with **no default**, backfill explicitly, and set explicitly on insert; check `PRAGMA table_info` before altering; keep logic in `backend/migrations.py`.
- **Risk: Shared validation drift between create and edit**
  - Mitigation: single helper function in `backend/main.py` used by both endpoints; tests cover both create and edit over-limit cases with the same expected message.
- **Risk: Frontend markup mismatch (index.html content minimal / may render differently in environment)**
  - Mitigation: keep frontend changes primarily in `frontend/app.js`; any `frontend/index.html` edits limited to allowed attributes/controls (e.g., `maxlength=100`, filter/clear controls).
- **Risk: Test ordering / DB state leakage**
  - Mitigation: continue using temp DB via `TODO_DB_PATH` as in existing tests; keep tests self-contained (create needed tasks inside each test).

## 7. Branching and commits

- **Feature branch (binding note):** `feature/KAN-1-task-lifecycle-ux`
- **One commit per story (binding note), ordered:** KAN-2, KAN-3, KAN-4, KAN-5
- **Commit message format (role requirement):** `"<STORY-KEY>: summary"`
  - Examples:
    - `KAN-2: Add created_at migration and persist timestamp`
    - `KAN-3: Enforce 100-char title limit with negative tests`
    - `KAN-4: Add edit-title endpoint and inline UI editing`
    - `KAN-5: Add filtering and clear completed`

## 8. Definition of done

- All KAN-1 stories (KAN-2 to KAN-5) implemented per Jira acceptance criteria and binding design notes.
- Backend endpoints updated/added in `backend/main.py` with:
  - shared title validation (trim + required + <=100),
  - `created_at` persisted and returned,
  - optional filter param with invalid filter 422 message,
  - clear-completed route ordered before delete-by-id.
- Frontend updated in `frontend/app.js` (and allowed minimal updates to `frontend/index.html`) to support:
  - editing titles,
  - enforcing 100-char input limit (maxlength=100),
  - filtering and clear completed.
- Tests updated in `tests/test_api.py`:
  - cover new endpoints and negative cases, including exact error messages required.
- `pytest` passes locally (Windows PowerShell environment supported by repo’s current pure-python setup).
- No duplicate docs artifacts created; if plan already exists in a PR/branch, it will be updated (STEP 2 only after explicit approval).

DRAFT READY - AWAITING APPROVAL
