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
1. **Define a stable timestamp format** in `backend/main.py` for `created_at`:
   - Use UTC ISO-8601 string: `datetime.now(timezone.utc).isoformat()`, stored as `TEXT` in SQLite.
2. **Add an idempotent migration step inside `init_db()`** in `backend/main.py`:
   - Keep the existing `CREATE TABLE IF NOT EXISTS tasks (...)` for first-run DB creation.
   - After table creation, check for `created_at` presence using:
     - `PRAGMA table_info(tasks)` and scan returned column names.
   - If missing, run `ALTER TABLE tasks ADD COLUMN created_at TEXT`.
   - Backfill existing rows where `created_at IS NULL` with a non-empty value (set to the migration-time timestamp).
   - Ensure running this logic repeatedly does not error and does not drop data.
3. **Update insert logic** in `create_task()` (`backend/main.py`):
   - Insert `created_at` on task creation (include it in the `INSERT` statement).
4. **Update API response mapping** in `row_to_dict()` (`backend/main.py`):
   - Include `created_at` key in returned dict.
   - Keep backwards compatibility in behavior (existing keys unchanged); adding a new field is additive.
5. **Update tests** in `tests/test_api.py`:
   - Add/extend tests to cover old-schema migration, backfill, API response, and idempotency:
     - **Old-schema DB migration + backfill:** create an on-disk SQLite DB with a `tasks` table that intentionally lacks `created_at`, insert at least one row with minimal columns, then start the app/init code against that DB and assert:
       - `PRAGMA table_info(tasks)` includes `created_at`
       - existing rows now have non-empty `created_at` (backfilled)
     - **API response includes created_at:** POST then GET/list returns `created_at` as a non-empty string.
     - **Second-run idempotency:** call `backend.main.init_db()` explicitly a second time and assert it does not raise and the API continues to operate (e.g., list still returns tasks and each has `created_at`).

**Mapping to acceptance criteria**
- AC1 (existing DB gets new column without data loss): covered by migration logic in `init_db()` using PRAGMA + ALTER + backfill + old-schema test.
- AC2 (idempotent): covered by PRAGMA guard + explicit second `init_db()` call in test.
- AC3 (POST then GET returns created_at): covered by updated insert + `row_to_dict()` + API tests.

**Effort:** M (schema + migration logic + tests)

---

### Story KAN-3 — Enforce maximum title length validation on create (and later reuse for edit) with negative tests

**Objective**
Enforce a maximum title length (per story AC: 100 chars) in the API, returning HTTP 422 and an explicit Jira-defined message for too-long titles, plus add negative/boundary tests.

**Files to change / create (real paths)**
- Change: `backend/main.py`
- Change: `tests/test_api.py`

**Implementation steps (ordered)**
1. **Choose a single validation function** in `backend/main.py` to keep create/edit consistent:
   - Implement helper (local function) like `validate_title(raw: str) -> str`:
     - `title = raw.strip()`
     - if empty: raise `HTTPException(422, "<JIRA_TITLE_REQUIRED_MESSAGE>")`
     - if `len(title) > 100`: raise `HTTPException(422, "<JIRA_TITLE_TOO_LONG_MESSAGE>")`
     - return `title`
   - Note: message strings must match Jira/AC exactly; do not invent them. Use placeholders until the exact strings are available.
2. **Use the helper in `create_task()`** in `backend/main.py` instead of inline `.strip()` logic.
3. **Update tests** in `tests/test_api.py`:
   - Add `test_title_too_long_rejected()` that posts a 200-character string and asserts:
     - status code 422
     - JSON `detail` equals `<JIRA_TITLE_TOO_LONG_MESSAGE>` (exact match)
   - Add `test_title_max_length_allowed()` that posts exactly 100 characters and asserts:
     - status code 201
     - returned title equals the submitted (trim rules still apply).
   - Keep/strengthen `test_blank_title_rejected()` verifying 422 for whitespace-only title and assert `detail == <JIRA_TITLE_REQUIRED_MESSAGE>` (exact match).

**Mapping to acceptance criteria**
- AC1 (200 chars rejected with explicit message): negative test asserts status/detail using Jira exact string.
- AC2 (100 chars accepted): boundary test asserts 201 and exact title.
- AC3 (blank title still rejected with same message): preserved and asserted via exact Jira string.

**Effort:** S (simple validation + tests)

---

### Story KAN-4 — Edit task title (API + UI) using existing list view and shared validation rules

**Objective**
Allow updating a task’s title via API and provide an edit interaction in the UI; reuse title validation from KAN-3. Add API and E2E tests for update success/404/422.

**Files to change / create (real paths)**
- Change: `backend/main.py`
- Change: `frontend/app.js`
- Change: `tests/test_api.py`
- Change/Add (if present in repo): Playwright tests under a conventional path (e.g., `e2e/` or `tests/e2e/`), following existing repo conventions.

**Implementation steps (ordered)**
1. **Backend: add update endpoint** in `backend/main.py`:
   - Add route: `@app.patch("/api/tasks/{task_id}")`
   - Request body: reuse `TaskIn` for `{ "title": ... }` (consistent schema).
   - Validate title via shared `validate_title()` from KAN-3 (ensures the same exact Jira error messages).
   - Execute SQL:
     - `UPDATE tasks SET title = ? WHERE id = ?`
     - if `rowcount == 0`: raise 404 with Jira/AC exact message: `<JIRA_TASK_NOT_FOUND_MESSAGE>`
     - select updated row and return via `row_to_dict()`.
2. **Frontend: implement edit control** in `frontend/app.js` without modifying `frontend/index.html`:
   - In `render(tasks)`, for each task:
     - Add an “Edit” button next to “Delete” (created dynamically, so no HTML change needed).
     - On click, replace the title display with an `<input>` prefilled with current title plus Save/Cancel controls (all created dynamically).
     - On Save:
       - call `PATCH /api/tasks/{id}` with `{ "title": newTitle }`
       - then reload via existing `act()`/`load()` pattern.
     - On Cancel: revert by calling `load()` (or revert DOM locally).
   - Ensure validation/errors surface via existing error handling (e.g., `errorEl` in `act()`).
3. **Tests**
   - **API tests** in `tests/test_api.py`:
     - `test_edit_title_success()`:
       - create a task
       - PATCH `/api/tasks/{id}` with updated title
       - assert 200 and title updated
     - `test_edit_title_404()`:
       - PATCH `/api/tasks/9999` returns 404 with `detail == <JIRA_TASK_NOT_FOUND_MESSAGE>` (exact match)
     - `test_edit_title_too_long_rejected()`:
       - create a task
       - PATCH with 200 chars returns 422 with `detail == <JIRA_TITLE_TOO_LONG_MESSAGE>` (exact match)
   - **Playwright E2E test(s)**:
     - Verify user can enter edit mode, change title, save, and observe updated title rendered.
     - Verify invalid edit (too-long title) shows error surfaced in the UI consistent with API response.

**Mapping to acceptance criteria**
- AC1 (PATCH updates title): covered by API endpoint + API test + E2E edit flow.
- AC2 (PATCH missing id returns 404): covered by API test asserting exact Jira message.
- AC3 (UI sends PATCH and shows updated title): covered by E2E test.
- AC4 (PATCH enforces max length with exact message): covered by shared validation + API test + E2E error assertion.

**Effort:** M (backend + UI behavior + API tests + E2E)

---

### Story KAN-5 — Add filtering (all/active/completed) and clear completed tasks (API + UI)

**Objective**
Support filtering tasks by completion state and clearing all completed tasks, both in API and UI, including an explicit 422 for invalid filter values.

**Files to change / create (real paths)**
- Change: `backend/main.py`
- Change: `frontend/app.js`
- Change: `tests/test_api.py`
- Change/Add (if present in repo): Playwright tests under a conventional path (e.g., `e2e/` or `tests/e2e/`), following existing repo conventions.

**Implementation steps (ordered)**
1. **Backend: extend list endpoint with query param** in `backend/main.py`:
   - Update `list_tasks()` signature to accept query param, e.g. `filter: str = "all"`.
   - Validate allowed values: `all`, `active`, `completed`.
     - If invalid, return HTTP 422 (explicitly required). Error message should be stable and (if defined by Jira/AC) must match exactly; otherwise use a placeholder: `<JIRA_INVALID_FILTER_MESSAGE>`.
   - SQL selection:
     - `all`: `SELECT * FROM tasks ORDER BY id`
     - `active`: `SELECT * FROM tasks WHERE completed = 0 ORDER BY id`
     - `completed`: `SELECT * FROM tasks WHERE completed = 1 ORDER BY id`
2. **Backend: add clear-completed endpoint** in `backend/main.py`:
   - `@app.delete("/api/tasks/completed", status_code=204)`
   - Execute `DELETE FROM tasks WHERE completed = 1`
   - Always return 204 (even if 0 rows deleted) to keep it idempotent.
3. **Frontend: add filter controls + clear completed** in `frontend/app.js` without editing HTML:
   - Create a control bar dynamically at runtime and insert it relative to existing elements (e.g., above the task list).
     - Controls: All / Active / Completed selector or buttons
     - “Clear completed” button
   - Maintain UI state variable: `let currentFilter = "all";`
   - Update `load()` to call `GET /api/tasks?filter=${currentFilter}` (or omit param for `all` if preferred).
   - Wire filter controls to set `currentFilter` and call `load()`.
   - Wire clear-completed button to call `DELETE /api/tasks/completed` via existing `act()` helper and then reload.
4. **Tests**
   - **API tests** in `tests/test_api.py`:
     - Filter tests:
       - Create tasks and toggle some completed.
       - `GET /api/tasks?filter=active` returns only `completed == False`
       - `GET /api/tasks?filter=completed` returns only `completed == True`
     - Invalid filter test:
       - `GET /api/tasks?filter=bogus` returns 422 and (if specified) exact `detail` message, else `<JIRA_INVALID_FILTER_MESSAGE>`.
     - Clear completed test:
       - `DELETE /api/tasks/completed` returns 204
       - subsequent `GET /api/tasks?filter=completed` returns `[]`
   - **Playwright E2E test(s)**:
     - Verify filter UI switches list between all/active/completed and reflects correct items.
     - Verify “Clear completed” removes completed tasks from list and completed filter becomes empty.

**Mapping to acceptance criteria**
- AC1/AC2 (filter active/completed): covered by API tests + E2E filter behavior.
- AC3 (clear completed 204 and completed becomes empty): covered by API tests + E2E clear-completed behavior.
- AC4 (UI filter + clear completed): covered by E2E tests.
- Explicit requirement: invalid filter returns 422: covered by API validation + API test.

**Effort:** M (backend + UI controls + API tests + E2E)

---

## 3. Sequence and dependencies (recommended order; one commit per story)

**Recommended implementation order (minimize rework / shared logic)**
1. **KAN-2** (created_at + idempotent migration)  
   Reason: establishes schema evolution pattern early; affects row mapping and task creation response shape.
2. **KAN-3** (title max-length validation + tests)  
   Reason: creates shared validation used by edit.
3. **KAN-4** (edit title API + UI + tests)  
   Depends on KAN-3 validation helper and exact Jira messages.
4. **KAN-5** (filter + clear completed API + UI + tests)  
   Independent of title validation; adds query param validation and UI controls.

---

## 4. Data changes (what changes, and how existing data stays valid)

**Schema change**
- Add column: `tasks.created_at` (`TEXT`, ISO-8601 timestamp string created by `datetime.now(timezone.utc).isoformat()`).

**Migration approach (idempotent)**
- On startup in `init_db()` (`backend/main.py`):
  - Ensure `tasks` table exists.
  - Check existing columns via `PRAGMA table_info(tasks)`.
  - If `created_at` missing: `ALTER TABLE tasks ADD COLUMN created_at TEXT`.
  - Backfill existing rows with a non-empty timestamp where `created_at IS NULL`.

**Backward compatibility**
- Existing DB files remain usable; no drops/recreates.
- API responses include an additional field `created_at` (additive).
- Existing endpoints preserved; changes are additive (new field, new query param, new PATCH and DELETE endpoints).

---

## 5. Test strategy (API + Playwright E2E)

**API tests (pytest + FastAPI TestClient)**
- Location: `tests/test_api.py`

Planned API tests by story:
- **KAN-2**
  - Old-schema DB migration + backfill:
    - Start from a DB that has a `tasks` table without `created_at`, with at least one pre-existing row.
    - Run `init_db()` and assert `created_at` column exists and pre-existing rows have non-empty backfilled values.
  - API response includes `created_at`:
    - Create a new task via POST and assert response includes non-empty `created_at`.
    - List/get tasks and assert each has non-empty `created_at`.
  - Second-run idempotency:
    - Call `init_db()` a second time and assert no exception and API remains functional.
- **KAN-3**
  - Blank/whitespace title rejected with 422 and exact Jira message: `<JIRA_TITLE_REQUIRED_MESSAGE>`.
  - Title > 100 chars rejected with 422 and exact Jira message: `<JIRA_TITLE_TOO_LONG_MESSAGE>`.
  - Title of exactly 100 chars accepted (201) and echoed correctly.
- **KAN-4**
  - PATCH updates title successfully (200, updated title returned).
  - PATCH unknown id returns 404 with exact Jira message: `<JIRA_TASK_NOT_FOUND_MESSAGE>`.
  - PATCH too-long title returns 422 with exact Jira message: `<JIRA_TITLE_TOO_LONG_MESSAGE>`.
- **KAN-5**
  - Filter `active` returns only incomplete tasks.
  - Filter `completed` returns only completed tasks.
  - Invalid filter returns 422 (and exact Jira message if provided): `<JIRA_INVALID_FILTER_MESSAGE>`.
  - Clear completed returns 204 and subsequent completed-filter list is empty.

**Playwright E2E tests (UI acceptance criteria)**
- Purpose: validate UI flows for acceptance criteria that depend on `frontend/app.js` behavior.
- Planned E2E coverage:
  - **KAN-3 (UI creation validation)**
    - Attempt to add a task with a title longer than 100 characters and assert the UI displays the API error message (exact Jira message placeholder: `<JIRA_TITLE_TOO_LONG_MESSAGE>`).
  - **KAN-4 (Edit UI)**
    - Edit an existing task title, save, and assert the list updates to the new title.
    - Attempt to save an invalid (too-long) title and assert error is displayed.
  - **KAN-5 (Filter + clear completed UI)**
    - Toggle completion and verify filter controls correctly show All/Active/Completed subsets.
    - Clear completed and verify completed tasks are removed and completed-filter view is empty.

---

## 6. Risks and mitigations

1. **Risk: SQLite ALTER TABLE + backfill could behave unexpectedly across existing DB states**
   - Mitigation: use `PRAGMA table_info(tasks)` to detect column presence; only ALTER when absent; backfill only when `created_at IS NULL`.

2. **Risk: `row_to_dict()` assumes created_at exists and could KeyError if migration didn’t run**
   - Mitigation: ensure `init_db()` runs before serving requests and that migration logic runs after table creation and before any selects/inserts rely on `created_at`.

3. **Risk: UI changes require DOM elements that may not exist in `frontend/index.html`**
   - Mitigation: create edit/filter/clear-completed controls dynamically in `frontend/app.js` and insert relative to existing, already-referenced elements. Do not add required static HTML.

4. **Risk: Tight coupling between validation messages and tests**
   - Mitigation: centralize validation in `validate_title()` and define message strings in a single place. Use placeholders until exact Jira strings are confirmed; once confirmed, update both backend and tests to match exactly.

---

## 7. Branching and commits

**Branch name**
- `feature/KAN-1-todo-enhancements`

**Commit order (one per story)**
1. `KAN-2: add created_at and idempotent migration`
2. `KAN-3: enforce max title length validation`
3. `KAN-4: add edit title API and UI`
4. `KAN-5: add filtering and clear completed`

---

## 8. Definition of done

- All acceptance criteria for KAN-2, KAN-3, KAN-4, KAN-5 are implemented and verifiable via automated tests.
- API tests are green (pytest).
- Playwright E2E tests are green for UI acceptance criteria (KAN-3, KAN-4, KAN-5).
- No changes made to `frontend/index.html` (explicitly respected).
- API remains backward compatible (existing endpoints preserved; additive fields/params only).
- Code changes limited to repo paths:
  - `backend/main.py`, `frontend/app.js`, `tests/test_api.py` (plus Playwright tests in the repo’s existing E2E test location, if present).

DRAFT READY - AWAITING APPROVAL
