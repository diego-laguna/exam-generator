export type Role = "teacher" | "student" | "admin";

export const isRole = (value: string | null | undefined): value is Role =>
  value === "teacher" || value === "student" || value === "admin";

interface NavItem {
  to: string;
  label: string;
  roles: Role[];
}

const ALL: Role[] = ["teacher", "student", "admin"];

/** What each role can reach. This only decides what to show; the API enforces access on every call. */
export const NAV: NavItem[] = [
  { to: "/documents", label: "Documents", roles: ["teacher"] },
  { to: "/generate", label: "Generate", roles: ["teacher"] },
  { to: "/questions", label: "Questions", roles: ["teacher"] },
  { to: "/sets", label: "Sets", roles: ["teacher"] },
  { to: "/exam", label: "Exam", roles: ["teacher"] },
  { to: "/exams", label: "Exams", roles: ["student"] },
  { to: "/users", label: "Users", roles: ["admin"] },
  { to: "/samples", label: "Samples", roles: ["admin"] },
  { to: "/sources", label: "Sources", roles: ALL },
  { to: "/stats", label: "My stats", roles: ALL },
];

export const navFor = (role: Role | null): NavItem[] => NAV.filter((item) => role !== null && item.roles.includes(role));

export function homeFor(role: Role | null): string {
  if (role === "teacher") return "/documents";
  if (role === "student") return "/exams";
  return "/users";
}
