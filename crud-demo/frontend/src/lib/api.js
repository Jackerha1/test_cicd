// Single fetch chokepoint. Routes never call fetch directly.
// JWT lives in localStorage under "aicicd:token" — see CONVENTIONS.md.

const BASE = import.meta.env.VITE_API_URL || "http://localhost:5000";
const TOKEN_KEY = "aicicd:token";

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

class ApiError extends Error {
  constructor(status, body) {
    super(body?.message || `HTTP ${status}`);
    this.status = status;
    this.body = body;
    this.name = "ApiError";
  }
}

async function request(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const token = tokenStore.get();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 204) return null;
  let payload = null;
  try { payload = await res.json(); } catch { /* non-JSON tolerated for DELETE etc. */ }

  if (!res.ok) throw new ApiError(res.status, payload);
  return payload;
}

// ---- public API ----

export const api = {
  register: (username, password) =>
    request("/api/auth/register", { method: "POST", body: { username, password }, auth: false }),

  login: (username, password) =>
    request("/api/auth/login", { method: "POST", body: { username, password }, auth: false }),

  listTasks: () =>
    request("/api/tasks"),

  createTask: (data) =>
    request("/api/tasks", { method: "POST", body: data }),

  updateTask: (id, data) =>
    request(`/api/tasks/${id}`, { method: "PUT", body: data }),

  deleteTask: (id) =>
    request(`/api/tasks/${id}`, { method: "DELETE" }),
};

export { ApiError };
