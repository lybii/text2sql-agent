import clsx from "clsx";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  ChevronDown,
  Clock,
  Code2,
  ExternalLink,
  KeyRound,
  Pencil,
  Play,
  ShieldAlert,
  ThumbsDown,
  ThumbsUp,
  X,
} from "lucide-react";
import { useState } from "react";

import type { QueryRun } from "../../api/types";
import { Badge, Button, ErrorText, Spinner, inputClass, type Tone } from "../../components/ui";
import { timeLeft } from "../../lib/format";
import { RequestAccessDialog } from "../access/RequestAccessDialog";
import { ResultChart, ResultTable } from "./ResultView";

export interface QueryActions {
  approve: (run: QueryRun) => Promise<void>;
  edit: (run: QueryRun, sql: string) => Promise<void>;
  cancel: (run: QueryRun) => Promise<void>;
  feedback: (run: QueryRun, rating: 1 | -1) => Promise<void>;
}

const STATUS: Partial<Record<QueryRun["status"], { label: string; tone: Tone }>> = {
  awaiting_approval: { label: "Chờ bạn duyệt", tone: "amber" },
  running: { label: "Đang chạy", tone: "blue" },
  succeeded: { label: "Hoàn tất", tone: "green" },
  failed: { label: "Thất bại", tone: "red" },
  cancelled: { label: "Đã hủy", tone: "slate" },
  superseded: { label: "Đã thay bằng câu hỏi mới", tone: "slate" },
  expired: { label: "Hết hạn duyệt", tone: "slate" },
  rejected: { label: "Không tạo được SQL an toàn", tone: "red" },
};

function SqlBlock({ sql, defaultOpen = false }: { sql: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button onClick={() => setOpen(!open)} className="flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-700">
        <Code2 className="size-3.5" /> SQL <ChevronDown className={clsx("size-3.5 transition-transform", open && "rotate-180")} />
      </button>
      {open && <pre className="scroll-thin mt-2 overflow-x-auto rounded-lg bg-slate-900 p-3 font-mono text-xs leading-relaxed text-slate-100">{sql}</pre>}
    </div>
  );
}

function MetricsFooter({ run }: { run: QueryRun }) {
  const m = run.metrics;
  const parts = [
    m.llm_route && `route: ${m.llm_route}`,
    m.llm_model,
    m.prompt_tokens + m.completion_tokens > 0 && `${m.prompt_tokens + m.completion_tokens} tokens`,
    m.cost_usd > 0 && `$${m.cost_usd.toFixed(4)}`,
    m.planning_ms != null && `lập kế hoạch ${m.planning_ms} ms`,
    m.execution_ms != null && `chạy ${m.execution_ms} ms`,
    m.sql_attempts > 1 && `${m.sql_attempts} lần sinh SQL`,
  ].filter(Boolean);
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400">
      {parts.map((p) => (
        <span key={String(p)}>{p}</span>
      ))}
      {run.trace_url && (
        <a href={run.trace_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 hover:text-brand-600">
          trace <ExternalLink className="size-3" />
        </a>
      )}
    </div>
  );
}

function ApprovalPanel({ run, actions }: { run: QueryRun; actions: QueryActions }) {
  const [editing, setEditing] = useState(false);
  const [sql, setSql] = useState(run.sql ?? "");
  const [busy, setBusy] = useState<"approve" | "edit" | "cancel" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const left = run.expires_at ? timeLeft(run.expires_at) : null;

  const act = async (kind: "approve" | "edit" | "cancel", fn: () => Promise<void>) => {
    setBusy(kind);
    setError(null);
    try {
      await fn();
      if (kind === "edit") setEditing(false);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3">
      {run.assumptions.length > 0 && (
        <ul className="list-inside list-disc text-xs text-slate-500">
          {run.assumptions.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      )}
      {editing ? (
        <textarea
          className={clsx(inputClass, "font-mono text-xs")}
          rows={Math.min(14, sql.split("\n").length + 1)}
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          spellCheck={false}
        />
      ) : (
        <pre className="scroll-thin overflow-x-auto rounded-lg bg-slate-900 p-3 font-mono text-xs leading-relaxed text-slate-100">{run.sql}</pre>
      )}
      <ErrorText error={error} />
      <div className="flex flex-wrap items-center gap-2">
        {editing ? (
          <>
            <Button size="sm" loading={busy === "edit"} onClick={() => act("edit", () => actions.edit(run, sql))}>
              Lưu & kiểm tra SQL
            </Button>
            <Button size="sm" variant="ghost" onClick={() => (setEditing(false), setSql(run.sql ?? ""))}>
              Bỏ sửa
            </Button>
          </>
        ) : (
          <>
            <Button size="sm" loading={busy === "approve"} onClick={() => act("approve", () => actions.approve(run))}>
              <Play className="size-3.5" /> Duyệt & chạy
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
              <Pencil className="size-3.5" /> Sửa SQL
            </Button>
            <Button size="sm" variant="ghost" loading={busy === "cancel"} onClick={() => act("cancel", () => actions.cancel(run))}>
              <X className="size-3.5" /> Hủy
            </Button>
          </>
        )}
        {left && (
          <span className="ml-auto inline-flex items-center gap-1 text-xs text-slate-400">
            <Clock className="size-3.5" /> hết hạn sau {left}
          </span>
        )}
      </div>
    </div>
  );
}

function ResultPanel({ run, actions }: { run: QueryRun; actions: QueryActions }) {
  const [rating, setRating] = useState(run.feedback);
  const columns = run.columns ?? [];
  const rows = run.rows ?? [];
  const rate = async (r: 1 | -1) => {
    setRating(r);
    await actions.feedback(run, r).catch(() => setRating(run.feedback));
  };
  return (
    <div className="space-y-4">
      {run.explanation && (
        <div className="space-y-1.5">
          <p className="text-sm text-slate-800">{run.explanation.summary}</p>
          {run.explanation.highlights.length > 0 && (
            <ul className="space-y-0.5 text-sm text-slate-600">
              {run.explanation.highlights.map((h) => (
                <li key={h} className="flex gap-2">
                  <span className="text-brand-500">•</span>
                  {h}
                </li>
              ))}
            </ul>
          )}
          {run.explanation_grounded === false && (
            <p className="text-xs text-amber-600">Diễn giải tự động chứa số liệu không kiểm chứng được nên đã được thay bằng bản tóm tắt tất định.</p>
          )}
        </div>
      )}
      {run.chart && rows.length > 0 && <ResultChart spec={run.chart} columns={columns} rows={rows} />}
      {rows.length > 0 && (run.chart?.type !== "kpi" || columns.length > 1) && <ResultTable columns={columns} rows={rows} />}
      {rows.length === 0 && <p className="text-sm text-slate-500">Không có dòng dữ liệu nào.</p>}
      {run.truncated && <p className="text-xs text-amber-600">Kết quả đã bị giới hạn số dòng.</p>}
      <div className="flex items-center gap-3">
        {run.sql && <SqlBlock sql={run.sql} />}
        <div className="ml-auto flex items-center gap-1">
          <span className="mr-1 text-xs text-slate-400">Kết quả hữu ích?</span>
          <button aria-label="Hữu ích" onClick={() => rate(1)} className={clsx("rounded p-1 hover:bg-slate-100", rating === 1 ? "text-emerald-600" : "text-slate-400")}>
            <ThumbsUp className="size-4" />
          </button>
          <button aria-label="Chưa đúng" onClick={() => rate(-1)} className={clsx("rounded p-1 hover:bg-slate-100", rating === -1 ? "text-rose-600" : "text-slate-400")}>
            <ThumbsDown className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

export function QueryCard({ run, reply, actions }: { run: QueryRun; reply: string; actions: QueryActions }) {
  const [requestOpen, setRequestOpen] = useState(false);

  if (run.status === "clarification" || run.status === "answered") {
    return <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">{reply}</p>;
  }
  if (run.status === "blocked") {
    return (
      <p className="flex items-start gap-2 text-sm text-slate-700">
        <ShieldAlert className="mt-0.5 size-4 shrink-0 text-rose-500" /> {reply}
      </p>
    );
  }
  if (run.status === "access_required") {
    return (
      <div className="space-y-3">
        <p className="flex items-start gap-2 text-sm text-slate-700">
          <KeyRound className="mt-0.5 size-4 shrink-0 text-amber-500" /> {reply}
        </p>
        {run.dataset_code && (
          <>
            <Button size="sm" variant="secondary" onClick={() => setRequestOpen(true)}>
              Gửi yêu cầu truy cập
            </Button>
            <RequestAccessDialog
              open={requestOpen}
              onClose={() => setRequestOpen(false)}
              datasetCode={run.dataset_code}
              datasetName={run.dataset_name ?? run.dataset_code}
            />
          </>
        )}
      </div>
    );
  }

  const status = STATUS[run.status];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {status && <Badge tone={status.tone}>{status.label}</Badge>}
        {run.dataset_name && <Badge tone="blue">{run.dataset_name}</Badge>}
        {run.risk_level && (
          <Badge tone={run.risk_level === "high" ? "red" : "green"}>
            {run.risk_level === "high" ? <AlertTriangle className="size-3" /> : <CheckCircle2 className="size-3" />}
            Rủi ro {run.risk_level === "high" ? "cao" : "thấp"}
          </Badge>
        )}
        {run.edited && <Badge tone="violet">Đã sửa SQL</Badge>}
        {run.auto_executed && <Badge tone="violet">Tự chạy (rủi ro thấp)</Badge>}
      </div>
      {run.interpretation && <p className="text-sm leading-relaxed text-slate-800">{run.interpretation}</p>}

      {run.status === "awaiting_approval" && <ApprovalPanel run={run} actions={actions} />}
      {run.status === "running" && <Spinner label="Đang thực thi truy vấn…" />}
      {run.status === "succeeded" && <ResultPanel run={run} actions={actions} />}
      {run.status === "failed" && (
        <p className="flex items-start gap-2 text-sm text-rose-600">
          <Ban className="mt-0.5 size-4 shrink-0" /> {run.error_message}
        </p>
      )}
      {run.status === "rejected" && (
        <>
          <p className="text-sm text-slate-700">{reply}</p>
          {run.validation_errors.length > 0 && (
            <ul className="list-inside list-disc text-xs text-rose-600">
              {run.validation_errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
        </>
      )}
      {["cancelled", "superseded", "expired", "failed"].includes(run.status) && run.sql && <SqlBlock sql={run.sql} />}
      <MetricsFooter run={run} />
    </div>
  );
}
