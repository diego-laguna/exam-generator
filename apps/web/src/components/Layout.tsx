import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth";

export function Layout() {
  const { logout } = useAuth();
  return (
    <>
      <header className="topbar">
        <strong className="brand">learn-assistant</strong>
        <nav aria-label="Main">
          <NavLink to="/documents">Documents</NavLink>
          <NavLink to="/generate">Generate</NavLink>
          <NavLink to="/questions">Questions</NavLink>
          <NavLink to="/sets">Sets</NavLink>
        </nav>
        <button type="button" className="link" onClick={() => void logout()}>
          Sign out
        </button>
      </header>
      <main>
        <Outlet />
      </main>
    </>
  );
}
