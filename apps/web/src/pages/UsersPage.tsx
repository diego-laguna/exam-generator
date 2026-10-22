import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";

import type { Schema } from "@exam-generator/api-client";

import { ErrorText } from "../components/Status";
import { unwrap } from "../errors";
import { api } from "../session";

type Role = Schema["Role"];
type CreatedUser = Schema["UserOut"];

export function UsersPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("teacher");
  const [created, setCreated] = useState<CreatedUser[]>([]);

  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/users", { body: { username: username.trim(), password, role } })),
    onSuccess: (user) => {
      setCreated((list) => [user, ...list]);
      setUsername("");
      setPassword("");
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <>
      <h1>Users</h1>
      <p className="hint">There is no self-registration: administrators create accounts here.</p>
      <form onSubmit={submit} className="card stack">
        <label>
          Username
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            minLength={3}
            maxLength={64}
            pattern="[A-Za-z0-9_.\-]+"
            title="Letters, digits, dot, dash and underscore"
            autoComplete="off"
            required
          />
        </label>
        <label>
          Password (8 to 128 characters)
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            maxLength={128}
            autoComplete="new-password"
            required
          />
        </label>
        <label>
          Role
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="teacher">Teacher</option>
            <option value="student">Student</option>
            <option value="admin">Admin</option>
          </select>
        </label>
        <ErrorText error={create.error} />
        <button type="submit" disabled={create.isPending}>
          Create user
        </button>
      </form>

      {created.length > 0 ? (
        <section aria-live="polite">
          <h2>Created in this session</h2>
          <ul className="list">
            {created.map((u) => (
              <li key={u.id} className="card row">
                <strong className="grow">{u.username}</strong>
                <span className={`role-badge ${u.role}`}>{u.role}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}
