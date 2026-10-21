import { useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "../auth";
import { ErrorText } from "../components/Status";
import { homeFor, isRole } from "../roles";

export function LoginPage() {
  const { state, login } = useAuth();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (state.status === "authenticated") {
    const from =
      (location.state as { from?: string } | null)?.from ?? homeFor(isRole(state.role) ? state.role : null);
    return <Navigate to={from} replace />;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrapper">
      <div className="login-card">
        <div className="login-brand">
          <span className="login-logo" aria-hidden="true">🎓</span>
          <h1>ExamGen</h1>
          <p>Sign in to your account</p>
        </div>
        <form onSubmit={submit} className="stack">
          <label>
            Username
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              placeholder="your-username"
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              placeholder="••••••••"
              required
            />
          </label>
          <ErrorText error={error} />
          <button type="submit" disabled={busy} style={{ marginTop: "0.5rem" }}>
            {busy ? "Signing in…" : "Sign in →"}
          </button>
        </form>
      </div>
    </div>
  );
}
