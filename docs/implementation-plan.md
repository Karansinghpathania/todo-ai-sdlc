# Implementation Plan: Epic KAN-1

## 1. Overview

- **Epic:** KAN-1 - Improve task lifecycle UX (edit, validate, filter/clear) and add created_at with idempotent migration
- **Goal:** Let users edit task titles, enforce one title limit of 100 characters in backend and frontend, filter tasks (all/active/completed) and clear completed tasks, and store a `created_at` timestamp through an idempotent SQLite migration.
- **Stories:** KAN-2 (created_at + migration), KAN-3 (title length validation), KAN-4 (edit title), KAN-5 (filter + clear completed)
- **In scope:**
  - Backend: `backend/main.py`, new `backend/migrations.py`
  - Frontend: `frontend/app.js`; minimal edits to `frontend/index.html` (change the title input `maxlength` from 200 to 100, add controls or test hooks if needed)
  - Tests: `tests/test_api.py` (pytest), Gherkin features and Playwright end-to-end tests (written in the QA phase)
- **Out of scope:** new application frameworks, external migration tools, changing the database engine, authentication, repairing `frontend/index.html` (it is not broken; the code index only shows its text).

## 2. Story-by-story plan

### Shared rules (apply to every story)

- Title limit is **100 characters, measured after trimming**, for create and edit, in backend and frontend.
- Exact messages (copy from the Jira acceptance criteria; verify against KAN-3 and KAN-4 before coding):
  - blank title: 422, `"Title is required"`
  - too long: 422, `"Title must be 100 characters or less"`
  - missing task: 404, `"Task not found"`
- `created_at` uses `datetime.now(timezone.utc).isoformat()` for both backfill and new inserts.
- Every new interactive UI element gets a stable `data-testid` attribute (names are fixed in the LLD).
- Existing endpoints and JSON fields stay backward compatible; new fields and query parameters are additive and optional.

### KAN-2: created_at column with an idempotent migration

- **Objective:** add `created_at` to `tasks`, upgrade existing databases without data loss, safe to run repeatedly.
- **Files:** CREATE `backend/migrations.py`; UPDATE `backend/main.py`; UPDATE `tests/test_api.py`.
- **Steps:**
  1. Create `backend/migrations.py` with `migrate_sqlite_schema(conn)`.
  2. In it, read `PRAGMA table_info(tasks)`. If `created_at` is missing: `ALTER TABLE tasks ADD COLUMN created_at TEXT` (no default, because SQLite rejects non-constant defaults on ADD COLUMN), then `UPDATE tasks SET created_at = ? WHERE created_at IS NULL` with one timestamp generated in Python.
  3. In `backend/main.py`, keep `CREATE TABLE IF NOT EXISTS`, then call `migrate_sqlite_schema(conn)` from `init_db()`.
  4. Set `created_at` explicitly in the `INSERT` inside `create_task()`; include `created_at` in `row_to_dict()`.
- **Tests:**
  - POST and GET responses include a non-empty `created_at`.
  - **Upgrade test:** create a temporary SQLite file with the old schema (`id`, `title`, `completed`) and at least one row; call `migrate_sqlite_schema` on it; assert the column exists and the existing row has a non-null `created_at`; call it a second time and assert no error and unchanged values.
  - Calling `init_db()` again on the test database raises no error.
- **Acceptance criteria:** existing database upgraded without data loss; migration idempotent; `created_at` returned on create and list.
- **Effort:** M

### KAN-3: title length validation

- **Objective:** one validation rule, used for create now and edit later.
- **Files:** UPDATE `backend/main.py`, `frontend/app.js`, `frontend/index.html`, `tests/test_api.py`.
- **Steps:**
  1. Backend: add `validate_title(raw)` that trims, raises 422 `"Title is required"` when empty, raises 422 `"Title must be 100 characters or less"` when longer than 100, and returns the trimmed title. Use it in `create_task()`.
  2. Frontend: change the title input `maxlength` from 200 to 100 in `frontend/index.html`. In `frontend/app.js`, check trimmed length before the POST, show the same message in the error element, and send no request when it fails. The same check is reused by the edit handler in KAN-4.
- **Tests (pytest):** 200-character title returns 422 with the exact message; exactly 100 characters returns 201; blank title still returns 422 and the test asserts the detail `"Title is required"`.
- **UI criteria** (maxlength, client-side error) are covered by Playwright in the QA phase.
- **Effort:** S

### KAN-4: edit task title

- **Objective:** edit an existing task's title through the API and an inline UI, reusing `validate_title`.
- **Files:** UPDATE `backend/main.py`, `frontend/app.js`, `tests/test_api.py`.
- **Steps:**
  1. Backend: `PATCH /api/tasks/{task_id}` with body `{"title": ...}`; call `validate_title`; `UPDATE tasks SET title = ? WHERE id = ?`; if no row changed return 404 `"Task not found"`; return the updated row. The existing `PATCH /api/tasks/{task_id}/toggle` must keep working.
  2. Frontend: in `render(tasks)`, add an Edit button per task, created dynamically with a `data-testid`. Clicking it swaps the title text for an input with Save and Cancel buttons. Save validates with the shared client-side check, calls the PATCH, and reloads. Cancel restores the list without any request.
- **Tests (pytest):** success (200, new title); missing id (404); blank title (422 `"Title is required"`); 200-character title (422, same message as create); toggle endpoint still passes.
- **UI criterion** (inline edit shows the updated title) is covered by Playwright in the QA phase.
- **Effort:** M

### KAN-5: filter and clear completed

- **Objective:** filter by completion state and remove completed tasks.
- **Files:** UPDATE `backend/main.py`, `frontend/app.js`, `tests/test_api.py`; `frontend/index.html` only if static markup is preferred over dynamic controls.
- **Steps:**
  1. Backend, route order is critical: declare `DELETE /api/tasks/completed` **before** `DELETE /api/tasks/{task_id}`. Otherwise FastAPI treats `completed` as a task id and returns 422.
  2. `GET /api/tasks` accepts an optional `filter` query parameter (`all`, `active`, `completed`; default `all`). An invalid value returns 422 with detail `"Filter must be all, active or completed"` (decided here because the Jira criteria do not define it). A request without the parameter returns every task, as today.
  3. `DELETE /api/tasks/completed` runs `DELETE FROM tasks WHERE completed = 1` and always returns 204.
  4. Frontend: All / Active / Completed controls and a Clear completed button, each with a `data-testid`. Keep a `currentFilter` variable; `load()` requests `/api/tasks?filter=<value>` for active and completed, and plain `/api/tasks` for all.
- **Tests (pytest):** create several tasks and complete some; `filter=active` returns only incomplete tasks; `filter=completed` returns only completed tasks; an invalid filter returns 422; `DELETE /api/tasks/completed` returns 204 and the completed filter is then empty; deleting a single task by id still works.
- **UI criteria** (filter controls, Clear completed) are covered by Playwright in the QA phase.
- **Effort:** M

## 3. Sequence and dependencies

Work on **one feature branch** with **one commit per story**, in this order:

1. KAN-2: created_at migration. It changes every task response, so it goes first.
2. KAN-3: title validation. It creates the shared helper that edit reuses.
3. KAN-4: edit title. It depends on KAN-3.
4. KAN-5: filter and clear. It is independent and additive.

## 4. Data changes

- New column `tasks.created_at TEXT` (ISO-8601 UTC string).
- The migration checks `PRAGMA table_info(tasks)` before altering, adds the column without a default, and backfills existing rows in the same run. Running it again changes nothing.
- No table is dropped or recreated, so existing data stays valid. The new response field is additive.

## 5. Test strategy

- **pytest (`tests/test_api.py`):** API behaviour and the migration upgrade test, as listed per story.
- **Playwright end-to-end (QA phase, after the code is merged):** one spec file per story under `tests/e2e/`, with Gherkin `.feature` files under `tests/features/`. They cover every UI acceptance criterion: the 100-character maxlength and client-side error (KAN-3), inline edit (KAN-4), filter controls and Clear completed (KAN-5). Tests use the `data-testid` hooks from the LLD, start the app on a separate port with a temporary database through `TODO_DB_PATH`, and produce an HTML report.
- UI behaviour is not verified manually only.

## 6. Risks and mitigations

- **Route shadowing:** `/api/tasks/completed` can be captured by `/api/tasks/{task_id}`. Declare it first and test it.
- **Existing rows without created_at:** adding the column leaves NULLs. Backfill in the same migration and test the upgrade path.
- **Import-time `init_db()`:** it runs when the module is imported, which makes startup tests awkward. Test `migrate_sqlite_schema` directly on a temporary database, and keep `init_db()` callable.
- **Limit mismatch:** the input currently allows 200 characters while the API limit is 100. Change `maxlength` to 100 in KAN-3 and use one constant or helper.
- **Message coupling between code and tests:** keep each message in one place and assert it exactly.
- **Missing test hooks:** the LLD must name a `data-testid` for every new control, or Playwright tests will depend on styling.

## 7. Branching and commits

- Branch: `feature/KAN-1-task-lifecycle-ux` (one branch for the epic).
- Commits, in order:
  - `KAN-2: add created_at and idempotent migration`
  - `KAN-3: enforce 100-char title limit in backend and frontend`
  - `KAN-4: add edit task title API and UI`
  - `KAN-5: add filtering and clear completed`

## 8. Definition of done

- All acceptance criteria of KAN-2 to KAN-5 are met as written in Jira.
- pytest passes, including the migration upgrade test; Playwright tests pass and an HTML report is produced.
- Existing endpoints and rows keep working; new parameters are optional.
- The 100-character limit and its messages are identical in backend, frontend and tests.
- `DELETE /api/tasks/completed` works (route order verified).
- Build script produces a deployable artefact; README and documentation are updated; Jira stories are moved to Done.
