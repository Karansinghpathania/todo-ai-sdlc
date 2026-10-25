const listEl = document.getElementById("task-list");
const inputEl = document.getElementById("title-input");
const addBtn = document.getElementById("add-btn");
const errorEl = document.getElementById("error");

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

    const span = document.createElement("span");
    span.className = "title";
    span.textContent = t.title;

    const del = document.createElement("button");
    del.textContent = "Delete";
    del.className = "delete-btn";
    del.addEventListener("click", () => act(() => api(`/api/tasks/${t.id}`, { method: "DELETE" })));

    li.append(cb, span, del);
    listEl.appendChild(li);
  });
}

async function load() {
  render(await api("/api/tasks"));
}

async function act(fn) {
  errorEl.textContent = "";
  try { await fn(); await load(); } catch (e) { errorEl.textContent = e.message; }
}

addBtn.addEventListener("click", () => {
  const title = inputEl.value.trim();
  if (!title) { errorEl.textContent = "Please enter a task title"; return; }
  act(async () => {
    await api("/api/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) });
    inputEl.value = "";
  });
});
inputEl.addEventListener("keydown", (e) => { if (e.key === "Enter") addBtn.click(); });

load().catch((e) => { errorEl.textContent = e.message; });
