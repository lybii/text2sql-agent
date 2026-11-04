import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router";

import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import { MyRequestsPage } from "./features/access/MyRequestsPage";
import { AdminAccessPage } from "./features/admin/AdminAccessPage";
import { AuditPage } from "./features/admin/AuditPage";
import { StatsPage } from "./features/admin/StatsPage";
import { AuthProvider, useAuth } from "./features/auth/AuthContext";
import { LoginPage } from "./features/auth/LoginPage";
import { CatalogPage } from "./features/catalog/CatalogPage";
import { ChatPage } from "./features/chat/ChatPage";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 15_000 } },
});

function RequireAuth({ admin, children }: { admin?: boolean; children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading)
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner label="Đang tải…" />
      </div>
    );
  if (!user) return <Navigate to="/login" replace />;
  if (admin && user.role !== "admin") return <Navigate to="/chat" replace />;
  return <>{children}</>;
}

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: (
      <RequireAuth>
        <Layout />
      </RequireAuth>
    ),
    children: [
      { path: "/", element: <Navigate to="/chat" replace /> },
      { path: "/chat", element: <ChatPage /> },
      { path: "/chat/:conversationId", element: <ChatPage /> },
      { path: "/datasets", element: <CatalogPage /> },
      { path: "/access", element: <MyRequestsPage /> },
      { path: "/admin/access", element: <RequireAuth admin><AdminAccessPage /></RequireAuth> },
      { path: "/admin/stats", element: <RequireAuth admin><StatsPage /></RequireAuth> },
      { path: "/admin/audit", element: <RequireAuth admin><AuditPage /></RequireAuth> },
      { path: "*", element: <Navigate to="/chat" replace /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
);
