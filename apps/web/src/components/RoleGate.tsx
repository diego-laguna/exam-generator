import { Link, Outlet } from "react-router-dom";

import { useAuth } from "../auth";
import { homeFor, isRole, type Role } from "../roles";

/** Renders its child routes only for the given roles; others get a short explanation. */
export function RoleGate({ roles }: { roles: Role[] }) {
  const { state } = useAuth();
  const role = state.status === "authenticated" && isRole(state.role) ? state.role : null;
  if (role && roles.includes(role)) return <Outlet />;
  return (
    <section className="card">
      <h1>Not available</h1>
      <p>This page is not available for your account type{role ? ` (${role})` : ""}.</p>
      <Link to={homeFor(role)}>Go to your start page</Link>
    </section>
  );
}
