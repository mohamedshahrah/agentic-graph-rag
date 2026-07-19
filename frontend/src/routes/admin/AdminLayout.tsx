import clsx from "clsx";
import { Activity, Server, SlidersHorizontal, Users } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

const TABS = [
  { to: "/admin", end: true, label: "Overview", icon: Activity },
  { to: "/admin/users", end: false, label: "Users", icon: Users },
  { to: "/admin/limits", end: false, label: "Limits", icon: SlidersHorizontal },
  { to: "/admin/system", end: false, label: "System", icon: Server },
];

export default function AdminLayout() {
  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-border bg-surface px-4">
        <nav className="mx-auto flex max-w-6xl gap-1">
          {TABS.map(({ to, end, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                clsx(
                  "-mb-px inline-flex items-center gap-2 border-b-2 px-3 py-3 text-[13px] font-medium transition-colors",
                  isActive
                    ? "border-accent text-strong"
                    : "border-transparent text-muted hover:text-body",
                )
              }
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </NavLink>
          ))}
        </nav>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl px-4 py-6">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
