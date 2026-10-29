# Implementation Plan

## 1. Overview (epic key, goal, scope, out of scope)

**Epic:** KAN-1 — Improve task lifecycle UX (edit, validate, filter/clear) and add created_at with idempotent migration

**Goal**
Enhance the existing Todo app so users can:
- edit task titles,
- have title max-length validation enforced by the API (with negative tests),
- filter tasks (all/active/completed) and clear completed tasks,
- and store a `created_at` timestamp for tasks via an idempotent SQLite migration.

**Scope (repo-grounded)**
- Backend changes in `backend/main.py` (FastAPI routes + SQLite access + startup DB initialization/migration).
- Frontend changes in `frontend/app.js` (edit UI, filter UI, clear-completed UI; without modifying `frontend/index.html`).
- Test changes in `tests/test_api.py` (pytest + FastAPI TestClient).

**Out of scope**
- Any fixes to `frontend/index.html` (explicitly excluded).
- Introducing external migration tools/frameworks (e.g., Alembic).
- Changing database engine away from SQLite.
- AuthN/AuthZ.

---

## 2. Story-by-story plan

### Story KAN-2 — Add created_at column to tasks with an idempotent SQLite migration

**Objective**
Add a `created_at` column to the `tasks` table without breaking existing databases, and ensure startup migration is idempotent. New tasks must return `created_at` in API responses.

**Files to change / create (real paths)**
- Change: `backend/main.py`
- Change: `tests/test_api.py`

**Implementation steps (ordered)**
1. **Define a stable timestamp format** in `backend/main.py` for created_at:
   - Use UTC ISO-8601 string (e.g., `datetime.now(timezone.utc).isoformat()`), stored as `TEXT` in SQLite.
2. **Add an idempotent migration step inside `init_db()`** in `backend/main.py`:
   - Keep the existing `CREATE TABLE IF NOT EXISTS tasks (...)` for first-run DB creation.
   - After table creation, check for `created_at` presence using:
     - `PRAGMA table_info(tasks)` and scan returned column names.
   - If missing, run `ALTER TABLE tasks ADD COLUMN created_at TEXT`.
   - Backfill existing rows where `created_at IS NULL` with a non-empty value (e.g., set to current timestamp at migration time).
   - Ensure running this logic repeatedly does not error and does not drop data.
3. **Update insert logic** in `create_task()` (`backend/main.py`):
   - Insert `created_at` on task creation (include it in the `INSERT` statement).
4. **Update API response mapping** in `row_to_dict()` (`backend/main.py`):
   - Include `created_at` key in returned dict.
   - Keep backwards compatibility in behavior (existing keys unchanged); adding a new field is additive.
5. **Update tests** in `tests/test_api.py`:
   - Extend `test_add_toggle_delete` to assert the response includes `"created_at"` and it is a non-empty string.
   - Add a focused migration idempotency test:
     - Create tasks, re-importing the app is hard because `init_db()` executes at import time; instead, validate idempotency by calling `backend.main.init_db()` explicitly a second time in-test and asserting API still works afterward (no exception) and created tasks still have `created_at`.

**Mapping to acceptance criteria**
- AC1 (existing DB gets new column without data loss): covered by migration logic in `init_db()` using PRAGMA + ALTER + backfill.
- AC2 (idempotent): covered by PRAGMA guard + explicit `init_db()` re-run test.
- AC3 (POST then GET returns created_at): covered by updated insert + `row_to_dict()` + tests.

**Effort:** M (schema + migration logic + tests)

---

### Story KAN-3 — Enforce maximum title length validation on create (and later reuse for edit) with negative tests

**Objective**
Enforce a maximum title length (per story AC: 100 chars) in the API, returning HTTP 422 and an explicit message for too-long titles, plus add negative/boundary tests.

**Files to change / create (real paths)**
- Change: `backend/main.py`
- Change: `tests/test_api.py`

**Implementation steps (ordered)**
1. **Choose a single validation function** in `backend/main.py` to keep create/edit consistent:
   - Implement helper (local function) like `validate_title(raw: str) -> str`:
     - `title = raw.strip()`
     - if empty: raise `HTTPException(422, "Title is required")` (preserve current behavior/message)
     - if `len(title) > 100`: raise `HTTPException(422, "Title must be 100 characters or less")`
     - return `title`
2. **Use the helper in `create_task()`** in `backend/main.py` instead of inline `.strip()` logic.
3. **Update tests** in `tests/test_api.py`:
   - Add `test_title_too_long_rejected()` that posts a 200-character string and asserts:
     - status code 422
     - JSON `detail` equals `"Title must be 100 characters or less"` (use exact message to match AC).
   - Add `test_title_max_length_allowed()` that posts exactly 100 characters and asserts:
     - status code 201
     - returned title equals the submitted (trim rules still apply).
   - Keep existing `test_blank_title_rejected()` verifying 422 for whitespace-only title (and optionally assert `detail == "Title is required"` to lock message).

**Mapping to acceptance criteria**
- AC1 (200 chars rejected with explicit message): negative test asserts status/detail.
- AC2 (100 chars accepted): boundary test asserts 201 and exact title.
- AC3 (blank title still rejected with same message): existing behavior maintained; optionally strengthen assertion on `detail`.

**Effort:** S (simple validation + tests)

---

### Story KAN-4 — Edit task title (API + UI) using existing list view and shared validation rules

**Objective**
Allow updating a task’s title via API and provide an edit interaction in the UI; reuse title validation from KAN-3. Add API tests for update success/404/422.

**Files to change / create (real paths)**
- Change: `backend/main.py`
- Change: `frontend/app.js`
- Change: `tests/test_api.py`

**Implementation steps (ordered)**
1. **Backend: add update endpoint** in `backend/main.py`:
   - Create a new route: `@app.patch("/api/tasks/{task_id}")`
   - Request body: reuse `TaskIn` for `{ "title": ... }` (consistent schema).
   - Validate title via the shared `validate_title()` introduced in KAN-3.
   - Execute SQL:
     - `UPDATE tasks SET title = ? WHERE id = ?`
     - if `rowcount == 0`: raise 404 `"Task not found"` (match AC)
     - select updated row and return via `row_to_dict()`.
2. **Frontend: implement edit control** in `frontend/app.js` without modifying `frontend/index.html`:
   - In `render(tasks)`, for each task:
     - Add an “Edit” button next to “Delete” (created dynamically, so no HTML change needed).
     - On click, replace the title `<span>` with an `<input>` prefilled with current title plus Save/Cancel buttons (all created dynamically).
     - On Save:
       - call `api(`/api/tasks/${t.id}`, { method: "PATCH", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ title: newTitle }) })`
       - then `load()` via existing `act()` pattern.
     - On Cancel: re-render by calling `load()` (or revert DOM locally).
   - Ensure errors surface via existing `errorEl` (already handled in `act()`).
3. **Tests: extend API test coverage** in `tests/test_api.py`:
   - `test_edit_title_success()`:
     - create a task
     - PATCH `/api/tasks/{id}` with corrected title
     - assert 200 and title updated
   - `test_edit_title_404()`:
     - PATCH `/api/tasks/9999` returns 404
   - `test_edit_title_too_long_rejected()`:
     - create a task
     - PATCH with 200 chars returns 422 with same detail message as create (per AC).

**Mapping to acceptance criteria**
- AC1 (PATCH updates title): covered by endpoint + `test_edit_title_success`.
- AC2 (PATCH missing id returns 404): covered by `test_edit_title_404`.
- AC3 (UI sends PATCH and shows updated title): covered by implementing dynamic edit controls and using `act()` reload behavior.
- AC4 (PATCH enforces max length): covered by shared validation + negative test.

**Effort:** M (backend + UI behavior + tests)

---

### Story KAN-5 — Add filtering (all/active/completed) and clear completed tasks (API + UI)

**Objective**
Support filtering tasks by completion state and clearing all completed tasks, both in API and UI.

**Files to change / create (real paths)**
- Change: `backend/main.py`
- Change: `frontend/app.js`
- Change: `tests/test_api.py`

**Implementation steps (ordered)**
1. **Backend: extend list endpoint with query param** in `backend/main.py`:
   - Update `list_tasks()` signature to accept a query param, e.g. `filter: str = "all"`.
   - Validate allowed values: `all`, `active`, `completed`.
     - If invalid, return HTTP 422 with a clear message (not specified in AC, but safer than silently defaulting).
   - SQL selection:
     - `all`: `SELECT * FROM tasks ORDER BY id`
     - `active`: `SELECT * FROM tasks WHERE completed = 0 ORDER BY id`
     - `completed`: `SELECT * FROM tasks WHERE completed = 1 ORDER BY id`
2. **Backend: add clear-completed endpoint** in `backend/main.py`:
   - `@app.delete("/api/tasks/completed", status_code=204)`
   - Execute `DELETE FROM tasks WHERE completed = 1`
   - Always return 204 (even if 0 rows deleted) to keep it simple and idempotent.
3. **Frontend: add filter controls + clear completed** in `frontend/app.js` without editing HTML:
   - Create a small control bar dynamically at runtime and insert it before/above the list (using DOM insertion around `listEl`):
     - Three buttons or a `<select>`: All / Active / Completed
     - A “Clear completed” button
   - Maintain a JS state variable, e.g. `let currentFilter = "all";`
   - Update `load()` to call `api("/api/tasks?filter=" + currentFilter)` (when filter isn’t all).
   - Wire filter controls to set `currentFilter` and call `load()`.
   - Wire clear-completed button to call `act(() => api("/api/tasks/completed", { method: "DELETE" }))` then reload (already in `act`).
4. **Tests: add API coverage** in `tests/test_api.py`:
   - Create three tasks, toggle some to completed.
   - Assert:
     - `GET /api/tasks?filter=active` returns only `completed == False`
     - `GET /api/tasks?filter=completed` returns only `completed == True`
   - Call `DELETE /api/tasks/completed` and assert:
     - status 204
     - subsequent `GET /api/tasks?filter=completed` is empty list.

**Mapping to acceptance criteria**
- AC1/AC2 (filter active/completed): covered by list endpoint changes + tests.
- AC3 (clear completed 204 and completed becomes empty): covered by delete endpoint + tests.
- AC4 (UI filter + clear completed behavior): covered by dynamic controls in JS and wiring through existing `act/load` pattern.

**Effort:** M (backend + UI controls + tests)

---

## 3. Sequence and dependencies (recommended order; one commit per story)

**Recommended implementation order (minimize rework / shared logic)**
1. **KAN-2** (created_at + idempotent migration)  
   Reason: establishes schema evolution pattern early; affects row mapping.
2. **KAN-3** (title max-length validation + tests)  
   Reason: creates shared validation used by edit.
3. **KAN-4** (edit title API + UI + tests)  
   Depends on KAN-3 validation helper.
4. **KAN-5** (filter + clear completed API + UI + tests)  
   Mostly independent; UI work is cleanly additive.

**One commit per story** (plus optional small refactor within story commit only).

---

## 4. Data changes (what changes, and how existing data stays valid)

**Schema change**
- Add column: `tasks.created_at` (`TEXT`, ISO-8601 timestamp string).

**Migration approach (idempotent)**
- On startup in `init_db()` (`backend/main.py`):
  - Ensure `tasks` table exists.
  - Check existing columns via `PRAGMA table_info(tasks)`.
  - If `created_at` missing: `ALTER TABLE ... ADD COLUMN created_at TEXT`.
  - Backfill existing rows with a non-empty timestamp value where `created_at` is NULL.

**Backward compatibility**
- Existing DB files remain usable; no drops/recreates.
- API responses will include an additional field `created_at`; this is additive.
- Existing behavior for blank title remains the same message: `"Title is required"`.

---

## 5. Test strategy (existing test framework for unit/API tests, Playwright for end-to-end, which stories need which)

**Existing framework**
- API tests: `pytest` + `fastapi.testclient.TestClient` in `tests/test_api.py`.

**Planned tests**
- KAN-2:
  - Assert `created_at` exists and is non-empty on created task.
  - Call `init_db()` again during tests to validate idempotency (no crash; still functional).
- KAN-3:
  - Negative test for >100 chars returns 422 with explicit message.
  - Boundary test for exactly 100 chars returns 201.
  - Keep/strengthen blank-title test.
- KAN-4:
  - API tests for PATCH update success, 404, and 422 (too long).
- KAN-5:
  - API tests for filter=active/completed.
  - API test for clear-completed endpoint.

**E2E (Playwright)**
- NOT FOUND in repo (no Playwright config/deps). Per constraint, do not introduce new frameworks in this plan; UI behavior will be validated indirectly via API tests and manual verification.

---

## 6. Risks and mitigations

1. **Risk: SQLite ALTER TABLE + backfill could behave unexpectedly across existing DB states**
   - Mitigation: use `PRAGMA table_info(tasks)` to detect column presence; only ALTER when absent; backfill only when `created_at IS NULL`.

2. **Risk: `row_to_dict()` assumes created_at exists and could KeyError if migration didn’t run**
   - Mitigation: ensure `init_db()` migration runs before any request handlers (it already runs at import); keep ordering inside `init_db()` correct.

3. **Risk: UI changes require DOM elements that may not exist in `frontend/index.html`**
   - Mitigation: create filter/edit controls dynamically in `frontend/app.js` and insert relative to existing elements already referenced (`task-list`, `title-input`, `add-btn`, `error`). Avoid adding new required static HTML.

4. **Risk: Tight coupling between validation messages and tests**
   - Mitigation: standardize error messages in one place (validation helper) so create/edit share exact same strings.

---

## 7. Branching and commits: branch `feature/<EPIC-KEY>-<slug>`; commit message format `"<STORY-KEY>: summary"`

**Branch name (for future implementation work)**
- `feature/KAN-1-task-lifecycle-ux`

**Commit conventions**
- One commit per story:
  - `KAN-2: add created_at and idempotent migration`
  - `KAN-3: enforce max title length validation`
  - `KAN-4: add edit title API and UI`
  - `KAN-5: add filtering and clear completed`

---

## 8. Definition of done

- All acceptance criteria for KAN-2, KAN-3, KAN-4, KAN-5 are implemented and verifiable.
- `pytest` passes locally (`tests/test_api.py` green).
- No changes made to `frontend/index.html` (explicitly respected).
- API remains backward compatible (existing endpoints preserved; additive fields/params only).
- Code changes limited to discovered repo paths:
  - `backend/main.py`, `frontend/app.js`, `tests/test_api.py` (and no new tooling introduced).
