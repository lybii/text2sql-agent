export type Role = "user" | "admin";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
}

export interface TokenResponse {
  access_token: string;
  user: User;
}

export type QueryStatus =
  | "blocked"
  | "answered"
  | "clarification"
  | "access_required"
  | "rejected"
  | "awaiting_approval"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "superseded"
  | "expired";

export interface Column {
  name: string;
  type: "number" | "text" | "date" | "bool";
}

export interface ChartSpec {
  type: "kpi" | "line" | "bar";
  x: string | null;
  y: string[];
}

export interface RunMetrics {
  prompt_version: string | null;
  llm_model: string | null;
  llm_route: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  sql_attempts: number;
  planning_ms: number | null;
  execution_ms: number | null;
  explain_ms: number | null;
}

export interface QueryRun {
  id: number;
  conversation_id: number;
  status: QueryStatus;
  question: string;
  standalone_question: string | null;
  dataset_code: string | null;
  dataset_name: string | null;
  sql: string | null;
  sql_hash: string | null;
  interpretation: string | null;
  assumptions: string[];
  validation_errors: string[];
  risk_level: "low" | "high" | null;
  edited: boolean;
  auto_executed: boolean;
  expires_at: string | null;
  columns: Column[] | null;
  rows: unknown[][] | null;
  row_count: number | null;
  truncated: boolean;
  chart: ChartSpec | null;
  explanation: { summary: string; highlights: string[] } | null;
  explanation_grounded: boolean | null;
  error_message: string | null;
  metrics: RunMetrics;
  feedback: number | null;
  trace_url: string | null;
  created_at: string;
  approved_at: string | null;
  finished_at: string | null;
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  query: QueryRun | null;
}

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export type AccessStatus = "open" | "granted" | "pending" | "none";

export interface Dataset {
  code: string;
  name: string;
  description: string;
  owner: string;
  access: "open" | "restricted";
  sensitivity: string;
  access_status: AccessStatus;
  metrics: { code: string; name: string; description: string; unit: string }[];
  dimensions: string[];
  sample_questions: string[];
  tables: { name: string; description: string; columns: { name: string; type: string; description: string }[] }[];
}

export interface AccessRequest {
  id: number;
  dataset_code: string;
  dataset_name: string;
  reason: string;
  status: "pending" | "approved" | "rejected" | "cancelled";
  requester_email: string | null;
  requester_name: string | null;
  reviewer_name: string | null;
  review_comment: string | null;
  expires_at: string | null;
  created_at: string;
  reviewed_at: string | null;
}

export interface Entitlement {
  id: number;
  user_email: string;
  user_name: string;
  dataset_code: string;
  dataset_name: string;
  granted_at: string;
  expires_at: string | null;
}

export interface Stats {
  days: number;
  totals: Record<string, number>;
  rates: Record<string, number | null>;
  latency_ms: Record<string, number | null>;
  llm: Record<string, number | null>;
  hitl: Record<string, number | null>;
  feedback: { up: number; down: number };
  by_prompt_version: { prompt_version: string | null; runs: number; success_share: number; avg_planning_ms: number; avg_cost_usd: number }[];
}

export interface AuditEvent {
  id: number;
  created_at: string;
  actor: string | null;
  action: string;
  entity: string;
  entity_id: number | null;
  detail: Record<string, unknown>;
}
