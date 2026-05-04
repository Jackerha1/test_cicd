import { useEffect, useState } from "react";
import { api, ApiError, tokenStore } from "./lib/api.js";
import { Login } from "./components/Login.jsx";
import { TaskForm } from "./components/TaskForm.jsx";
import { TaskList } from "./components/TaskList.jsx";

export function App() {
  const [session, setSession] = useState(() => {
    const t = tokenStore.get();
    return t ? { token: t, username: localStorage.getItem("aicicd:username") || "" } : null;
  });
  const [tasks, setTasks] = useState([]);
  const [loadError, setLoadError] = useState(null);

  // Persist token on session change.
  useEffect(() => {
    if (session) {
      tokenStore.set(session.token);
      localStorage.setItem("aicicd:username", session.username);
    }
  }, [session]);

  // Load tasks whenever signed in.
  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    (async () => {
      try {
        const list = await api.listTasks();
        if (!cancelled) setTasks(list);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          // Token expired or invalid — sign out.
          signOut();
        } else {
          setLoadError(err instanceof ApiError ? err.body?.message : "network error");
        }
      }
    })();
    return () => { cancelled = true; };
  }, [session]);

  function signOut() {
    tokenStore.clear();
    localStorage.removeItem("aicicd:username");
    setSession(null);
    setTasks([]);
    setLoadError(null);
  }

  if (!session) {
    return <div className="app"><Login onLoggedIn={setSession} /></div>;
  }

  return (
    <div className="app">
      <div className="topbar">
        <h1 style={{ marginBottom: 0 }}>Tasks</h1>
        <div className="spacer" />
        <span className="who">@{session.username}</span>
        <button className="secondary" onClick={signOut}>Sign out</button>
      </div>

      <TaskForm onCreated={(t) => setTasks((cur) => [t, ...cur])} />
      {loadError && <div className="card error" role="alert">Could not load tasks: {loadError}</div>}
      <TaskList tasks={tasks} onChange={setTasks} />
    </div>
  );
}
