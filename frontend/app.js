const listEl = document.getElementById("task-list");
const inputEl = document.getElementById("title-input");
const addBtn = document.getElementById("add-btn");
const errorEl = document.getElementById("error");
inputEl.setAttribute("data-testid", "title-input");
addBtn.setAttribute("data-testid", "add-btn");
errorEl.setAttribute("data-testid", "error-banner");
const TITLE_TOO_LONG = "Title must be 100 characters or less";

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = "Request failed";
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

function render(tasks) {
  listEl.innerHTML = "";
  tasks.forEach((t) => {
    const li = document.createElement("li");
    li.dataset.id = t.id;
    if (t.completed) li.classList.add("done");

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = t.completed;
    cb.addEventListener("change", () => act(() => api(`/api/tasks/${t.id}/toggle`, { method: "PATCH" })));
    cb.setAttribute("data-testid", `toggle-task-${t.id}`);

    const span = document.createElement("span");
    span.className = "title";
    span.textContent = t.title;
    span.setAttribute("data-testid", `task-title-${t.id}`);
    span.addEventListener("click", () => startEdit(t, span));

    const del = document.createElement("button");
    del.textContent = "Delete";
    del.className = "delete-btn";
    del.setAttribute("data-testid", `delete-task-${t.id}`);
    del.addEventListener("click", () => act(() => api(`/api/tasks/${t.id}`, { method: "DELETE" })));

    li.append(cb, span, del);
    listEl.appendChild(li);
  });
}

function startEdit(t, span) {
  const editInput = document.createElement("input");
  editInput.type = "text";
  editInput.className = "edit-input";
  editInput.maxLength = 100;
  editInput.value = t.title;
  const save = document.createElement("button");
  save.textContent = "Save";
  save.className = "save-btn";
  save.addEventListener("click", () => saveEdit(t.id, editInput));
  const cancel = document.createElement("button");
  cancel.textContent = "Cancel";
  cancel.className = "cancel-btn";
  cancel.addEventListener("click", () => { errorEl.textContent = ""; load().catch((e) => { errorEl.textContent = e.message; }); });
  editInput.addEventListener("keydown", (e) => { if (e.key === "Enter") save.click(); });
  span.replaceWith(editInput, save, cancel);
  editInput.focus();
}

function saveEdit(id, editInput) {
  const title = editInput.value.trim();
  if (!title) { errorEl.textContent = "Please enter a task title"; return; }
  if (title.length > 100) { errorEl.textContent = TITLE_TOO_LONG; return; }
  act(() => api(`/api/tasks/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) }));
}

async function load() {
  const path = currentFilter === "all" ? "/api/tasks" : `/api/tasks?filter=${currentFilter}`;
  render(await api(path));
}

async function act(fn) {
  errorEl.textContent = "";
  try { await fn(); await load(); } catch (e) { errorEl.textContent = e.message; }
}

addBtn.addEventListener("click", () => {
  const title = inputEl.value.trim();
  if (!title) { errorEl.textContent = "Please enter a task title"; return; }
  if (title.length > 100) { errorEl.textContent = TITLE_TOO_LONG; return; }
  act(async () => {
    await api("/api/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) });
    inputEl.value = "";
  });
});
inputEl.addEventListener("keydown", (e) => { if (e.key === "Enter") addBtn.click(); });

let currentFilter = "all";
const filterButtons = {};
const filterBar = document.createElement("div");
filterBar.className = "filter-bar";
["all", "active", "completed"].forEach((name) => {
  const btn = document.createElement("button");
  btn.textContent = name.charAt(0).toUpperCase() + name.slice(1);
  btn.className = "filter-btn";
  btn.addEventListener("click", () => act(() => { currentFilter = name; updateFilterButtons(); }));
  filterButtons[name] = btn;
  filterBar.appendChild(btn);
});
const clearBtn = document.createElement("button");
clearBtn.textContent = "Clear completed";
clearBtn.className = "clear-completed-btn";
clearBtn.addEventListener("click", () => act(() => api("/api/tasks/completed", { method: "DELETE" })));
filterBar.appendChild(clearBtn);
listEl.before(filterBar);

function updateFilterButtons() {
  Object.keys(filterButtons).forEach((name) => {
    const selected = name === currentFilter;
    filterButtons[name].setAttribute("aria-pressed", String(selected));
    filterButtons[name].style.fontWeight = selected ? "bold" : "normal";
  });
}
updateFilterButtons();

load().catch((e) => { errorEl.textContent = e.message; });
