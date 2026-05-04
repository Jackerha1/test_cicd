import { useState } from "react";
import { api, ApiError } from "../lib/api.js";

export function Login({ onLoggedIn }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const { token, username: name } = mode === "login"
        ? await api.login(username, password)
        : await api.register(username, password);
      onLoggedIn({ token, username: name });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.body?.message || `error ${err.status}`);
      } else {
        setError("network error");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h1>{mode === "login" ? "Sign in" : "Create account"}</h1>
      <form onSubmit={submit}>
        <label htmlFor="u">Username</label>
        <input
          id="u"
          autoFocus
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          required
          minLength={3}
          maxLength={32}
        />
        <label htmlFor="p">Password</label>
        <input
          id="p"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          required
          minLength={mode === "register" ? 8 : 1}
        />
        {error && <div className="error" role="alert">{error}</div>}
        <div className="row" style={{ marginTop: 16 }}>
          <button type="submit" disabled={busy}>
            {busy ? "..." : mode === "login" ? "Sign in" : "Create account"}
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}
          >
            {mode === "login" ? "Need an account?" : "Already have one?"}
          </button>
        </div>
      </form>
    </div>
  );
}
