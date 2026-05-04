import { useState } from "react";
import { api, ApiError } from "../lib/api.js";

const STATUSES = ["todo", "in_progress", "done"];

export function TaskForm({ onCreated }) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [status, setStatus] = useState("todo");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const created = await api.createTask({
        title: title.trim(),
        description: description.trim() || undefined,
        due_date: dueDate || undefined,
        status,
      });
      onCreated(created);
      setTitle(""); setDescription(""); setDueDate(""); setStatus("todo");
    } catch (err) {
      setError(err instanceof ApiError ? (err.body?.message || `error ${err.status}`) : "network error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h2>New task</h2>
      <label htmlFor="t-title">Title</label>
      <input id="t-title" value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={120} />

      <label htmlFor="t-desc">Description</label>
      <textarea id="t-desc" rows={2} value={description}
                onChange={(e) => setDescription(e.target.value)} maxLength={2000} />

      <div className="row" style={{ alignItems: "flex-end", gap: 12 }}>
        <div style={{ flex: 1 }}>
          <label htmlFor="t-due">Due date</label>
          <input id="t-due" type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
        </div>
        <div style={{ flex: 1 }}>
          <label htmlFor="t-status">Status</label>
          <select id="t-status" value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <button type="submit" disabled={busy || !title.trim()}>
          {busy ? "..." : "Add"}
        </button>
      </div>

      {error && <div className="error" role="alert">{error}</div>}
    </form>
  );
}
