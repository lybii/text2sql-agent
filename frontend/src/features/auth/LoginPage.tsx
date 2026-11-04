import { useState, type FormEvent } from "react";
import { Navigate } from "react-router";

import { Button, ErrorText, inputClass } from "../../components/ui";
import { useAuth } from "./AuthContext";

const DEMO = [
  { label: "Chuyên viên", email: "analyst@demo.local", password: "Analyst@123" },
  { label: "Trưởng phòng", email: "manager@demo.local", password: "Manager@123" },
  { label: "Quản trị", email: "admin@demo.local", password: "Admin@123" },
];

export function LoginPage() {
  const { user, login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/chat" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, fullName, password);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center bg-gradient-to-br from-brand-50 via-white to-slate-100 p-6">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-3 flex size-12 items-center justify-center rounded-xl bg-brand-600 font-bold text-white">T2S</div>
          <h1 className="text-2xl font-semibold">Text2SQL Agent</h1>
          <p className="mt-1 text-sm text-slate-500">Hỏi dữ liệu bán hàng bằng tiếng Việt — duyệt SQL trước khi chạy</p>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          {mode === "register" && (
            <label className="block text-sm">
              <span className="mb-1 block font-medium">Họ tên</span>
              <input className={inputClass} value={fullName} onChange={(e) => setFullName(e.target.value)} required minLength={2} />
            </label>
          )}
          <label className="block text-sm">
            <span className="mb-1 block font-medium">Email</span>
            <input className={inputClass} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="username" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium">Mật khẩu</span>
            <input
              className={inputClass}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={mode === "register" ? 8 : 1}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
            />
          </label>
          <ErrorText error={error} />
          <Button type="submit" loading={busy} className="w-full">
            {mode === "login" ? "Đăng nhập" : "Tạo tài khoản"}
          </Button>
          <p className="text-center text-sm text-slate-500">
            {mode === "login" ? "Chưa có tài khoản?" : "Đã có tài khoản?"}{" "}
            <button type="button" className="font-medium text-brand-600 hover:underline" onClick={() => setMode(mode === "login" ? "register" : "login")}>
              {mode === "login" ? "Đăng ký" : "Đăng nhập"}
            </button>
          </p>
        </form>
        {mode === "login" && (
          <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-white/60 p-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Tài khoản demo</p>
            <div className="flex flex-wrap gap-2">
              {DEMO.map((d) => (
                <Button key={d.email} variant="secondary" size="sm" onClick={() => (setEmail(d.email), setPassword(d.password))}>
                  {d.label}
                </Button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
