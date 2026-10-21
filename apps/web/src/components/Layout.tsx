import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth";
import { isRole, navFor } from "../roles";
import { api } from "../session";

function ApiHealth() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const { response } = await api.GET("/api/v1/health");
      return response.ok;
    },
    refetchInterval: 30_000,
  });
  const online = health.data === true;
  return (
    <span className={online ? "health ok" : "health down"} role="status">
      API {health.isPending ? "checking…" : online ? "online" : "unreachable"}
    </span>
  );
}

/** Nav icon map – simple emoji so no icon library is needed. */
const NAV_ICONS: Record<string, string> = {
  "/documents": "📄",
  "/generate":  "✨",
  "/questions": "📋",
  "/sets":      "📦",
  "/exams":     "📝",
  "/users":     "👥",
  "/samples":   "🧪",
  "/sources":   "🔗",
  "/stats":     "📊",
};

export function Layout() {
  const { state, logout } = useAuth();
  const role = state.status === "authenticated" && isRole(state.role) ? state.role : null;
  return (
    <>
      <header className="topbar">
        <span className="brand">🎓 ExamGen</span>
        <nav aria-label="Main">
          {navFor(role).map((item) => (
            <NavLink key={item.to} to={item.to}>
              {NAV_ICONS[item.to] ?? ""} {item.label}
            </NavLink>
          ))}
        </nav>
        {role ? (
          <span className={`role-badge ${role}`}>{role}</span>
        ) : null}
        <button type="button" className="link" onClick={() => void logout()}>
          Sign out
        </button>
      </header>
      <main>
        <Outlet />
      </main>
      <footer className="footer">
        <ApiHealth />
      </footer>
    </>
  );
}
