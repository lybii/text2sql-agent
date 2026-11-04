import type {
  AccessRequest,
  AuditEvent,
  Conversation,
  ConversationDetail,
  Dataset,
  Entitlement,
  Message,
  QueryRun,
  Stats,
  TokenResponse,
  User,
} from "./types";

const BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8000") + "/api/v1";
const TOKEN_KEY = "t2s.token";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = tokenStore.get();
  const response = await fetch(BASE + path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && token) onUnauthorized();
    const detail = body?.error ?? {};
    const message =
      detail.message ??
      (Array.isArray(body?.detail) ? body.detail.map((d: { msg: string }) => d.msg).join("; ") : null) ??
      `Lỗi ${response.status}`;
    throw new ApiError(response.status, detail.code ?? "error", message);
  }
  return body as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  login: (email: string, password: string) => post<TokenResponse>("/auth/login", { email, password }),
  register: (email: string, full_name: string, password: string) =>
    post<TokenResponse>("/auth/register", { email, full_name, password }),
  me: () => request<User>("/auth/me"),

  datasets: () => request<Dataset[]>("/datasets"),

  conversations: () => request<Conversation[]>("/conversations"),
  conversation: (id: number) => request<ConversationDetail>(`/conversations/${id}`),
  createConversation: () => post<Conversation>("/conversations", {}),
  deleteConversation: (id: number) => request<void>(`/conversations/${id}`, { method: "DELETE" }),
  sendMessage: (id: number, content: string) =>
    post<{ messages: Message[] }>(`/conversations/${id}/messages`, { content }),

  approve: (id: number, sql_hash: string) => post<QueryRun>(`/queries/${id}/approve`, { sql_hash }),
  edit: (id: number, sql: string) => post<QueryRun>(`/queries/${id}/edit`, { sql }),
  cancel: (id: number) => post<QueryRun>(`/queries/${id}/cancel`),
  feedback: (id: number, rating: 1 | -1) =>
    request<void>(`/queries/${id}/feedback`, { method: "PUT", body: JSON.stringify({ rating }) }),

  myRequests: () => request<AccessRequest[]>("/access-requests"),
  requestAccess: (dataset_code: string, reason: string) =>
    post<AccessRequest>("/access-requests", { dataset_code, reason }),
  cancelRequest: (id: number) => post<AccessRequest>(`/access-requests/${id}/cancel`),

  adminRequests: (status: string) => request<AccessRequest[]>(`/admin/access-requests?status=${status}`),
  decide: (id: number, decision: "approve" | "reject", comment?: string, expires_at?: string) =>
    post<AccessRequest>(`/admin/access-requests/${id}/decision`, {
      decision,
      comment: comment || null,
      expires_at: expires_at ?? null,
    }),
  entitlements: () => request<Entitlement[]>("/admin/entitlements"),
  revoke: (id: number) => request<void>(`/admin/entitlements/${id}`, { method: "DELETE" }),
  stats: (days: number) => request<Stats>(`/admin/stats?days=${days}`),
  audit: () => request<AuditEvent[]>("/admin/audit?limit=200"),
};
