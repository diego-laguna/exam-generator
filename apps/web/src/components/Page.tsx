import type { ReactNode } from "react";
import { Link } from "react-router-dom";

interface PageHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  /** A link back to the parent screen, shown above the title. */
  back?: { to: string; label: string };
  /** Page-level buttons, aligned to the right of the title. */
  actions?: ReactNode;
}

export function PageHeader({ title, subtitle, back, actions }: PageHeaderProps) {
  return (
    <header className="page-head">
      <div className="grow">
        {back ? (
          <Link to={back.to} className="back-link">
            <span aria-hidden="true">&larr;</span> {back.label}
          </Link>
        ) : null}
        <h1>{title}</h1>
        {subtitle ? <p className="subtitle">{subtitle}</p> : null}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}

export function EmptyState({ icon, title, children }: { icon: string; title: string; children?: ReactNode }) {
  return (
    <div className="empty-state">
      <span className="empty-icon" aria-hidden="true">
        {icon}
      </span>
      <strong>{title}</strong>
      {children ? <p>{children}</p> : null}
    </div>
  );
}

/** One number in a `.stat-grid`. */
export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="stat">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}
