import { api, ApiError } from "../lib/api.js";

const NEXT_STATUS = { todo: "in_progress", in_progress: "done", done: "todo" };

export function TaskList({ tasks, onChange }) {
  if (tasks.length === 0) {
    return <div className="card" style={{ textAlign: "center", color: "var(--text-dim)" }}>
      No tasks yet — add one above.
    </div>;
  }

  async function cycleStatus(t) {
    try {
      const updated = await api.updateTask(t.id, { status: NEXT_STATUS[t.status] });
      onChange((cur) => cur.map((x) => x.id === updated.id ? updated : x));
    } catch (err) {
      console.error("cycleStatus", err);
    }
  }

  async function remove(t) {
    if (!confirm(`Delete "${t.title}"?`)) return;
    try {
      await api.deleteTask(t.id);
      onChange((cur) => cur.filter((x) => x.id !== t.id));
    } catch (err) {
      if (err instanceof ApiError && err.status !== 404) console.error("delete", err);
    }
  }

  return (
    <div>
      {tasks.map((t) => (
        <div key={t.id} className="task" data-testid="task-row">
          <div style={{ flex: 1 }}>
            <div className="row">
              <strong>{t.title}</strong>
              <span className={`status-${t.status}`}>· {t.status}</span>
            </div>
            {t.description && <div style={{ marginTop: 6 }}>{t.description}</div>}
            <div className="meta">
              {t.due_date ? `due ${t.due_date}` : "no due date"}
              {" · created "}{new Date(t.created_at).toLocaleDateString()}
            </div>
          </div>
          <div className="row" style={{ alignSelf: "center", gap: 6 }}>
            <button className="secondary" onClick={() => cycleStatus(t)}>→ {NEXT_STATUS[t.status]}</button>
            <button className="danger"    onClick={() => remove(t)}>delete</button>
          </div>
        </div>
      ))}
    </div>
  );
}
