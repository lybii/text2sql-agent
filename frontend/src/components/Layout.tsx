import clsx from "clsx";
import { BarChart3, Database, FileClock, KeyRound, LogOut, MessagesSquare, ShieldCheck } from "lucide-react";
import { NavLink, Outlet } from "react-router";

import { useAuth } from "../features/auth/AuthContext";

const userLinks = [
  { to: "/chat", label: "Hỏi dữ liệu", icon: MessagesSquare },
  { to: "/datasets", label: "Danh mục dữ liệu", icon: Database },
  { to: "/access", label: "Yêu cầu truy cập", icon: KeyRound },
];
const adminLinks = [
  { to: "/admin/access", label: "Duyệt quyền", icon: ShieldCheck },
  { to: "/admin/stats", label: "Chất lượng AI", icon: BarChart3 },
  { to: "/admin/audit", label: "Nhật ký audit", icon: FileClock },
];

function NavItem({ to, label, icon: Icon }: { to: string; label: string; icon: typeof Database }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        clsx(
          "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
          isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100",
        )
      }
    >
      <Icon className="size-4" />
      {label}
    </NavLink>
  );
}

export function Layout() {
  const { user, logout } = useAuth();
  return (
    <div className="flex h-full">
      <aside className="flex w-60 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="flex items-center gap-2 px-5 py-4">
          <div className="flex size-8 items-center justify-center rounded-lg bg-brand-600 text-sm font-bold text-white">T2S</div>
          <div>
            <p className="text-sm font-semibold leading-tight">Text2SQL Agent</p>
            <p className="text-xs text-slate-500">Phân tích dữ liệu bán hàng</p>
          </div>
        </div>
        <nav className="flex flex-1 flex-col gap-1 px-3">
          {userLinks.map((l) => (
            <NavItem key={l.to} {...l} />
          ))}
          {user?.role === "admin" && (
            <>
              <p className="mt-4 px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Quản trị</p>
              {adminLinks.map((l) => (
                <NavItem key={l.to} {...l} />
              ))}
            </>
          )}
        </nav>
        <div className="border-t border-slate-200 p-3">
          <p className="truncate px-2 text-sm font-medium">{user?.full_name}</p>
          <p className="truncate px-2 text-xs text-slate-500">{user?.email}</p>
          <button onClick={logout} className="mt-2 flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-slate-600 hover:bg-slate-100">
            <LogOut className="size-4" /> Đăng xuất
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
