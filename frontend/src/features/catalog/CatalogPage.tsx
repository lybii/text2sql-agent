import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Database, Lock, MessageSquareText } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";

import { api } from "../../api/client";
import type { Dataset } from "../../api/types";
import { Badge, Button, Card, ErrorText, Spinner, type Tone } from "../../components/ui";
import { RequestAccessDialog } from "../access/RequestAccessDialog";

const ACCESS: Record<Dataset["access_status"], { label: string; tone: Tone }> = {
  open: { label: "Mở cho mọi người", tone: "green" },
  granted: { label: "Đã được cấp quyền", tone: "green" },
  pending: { label: "Đang chờ duyệt", tone: "amber" },
  none: { label: "Cần cấp quyền", tone: "red" },
};

function DatasetCard({ dataset }: { dataset: Dataset }) {
  const navigate = useNavigate();
  const [showColumns, setShowColumns] = useState(false);
  const [requestOpen, setRequestOpen] = useState(false);
  const access = ACCESS[dataset.access_status];
  const canQuery = dataset.access_status === "open" || dataset.access_status === "granted";

  return (
    <Card className="flex flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 font-semibold">
            {canQuery ? <Database className="size-4 text-brand-600" /> : <Lock className="size-4 text-rose-500" />}
            {dataset.name}
          </h3>
          <p className="mt-0.5 text-xs text-slate-400">
            {dataset.code} · {dataset.owner} · {dataset.sensitivity === "confidential" ? "Mật" : "Nội bộ"}
          </p>
        </div>
        <Badge tone={access.tone}>{access.label}</Badge>
      </div>
      <p className="mt-3 text-sm text-slate-600">{dataset.description}</p>

      <div className="mt-4">
        <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">Chỉ số</p>
        <div className="flex flex-wrap gap-1.5">
          {dataset.metrics.map((m) => (
            <span key={m.code} title={m.description} className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
              {m.name}
            </span>
          ))}
        </div>
      </div>
      {dataset.dimensions.length > 0 && (
        <p className="mt-3 text-xs text-slate-500">
          <span className="font-semibold uppercase tracking-wide text-slate-400">Phân tích theo: </span>
          {dataset.dimensions.join(" · ")}
        </p>
      )}

      {canQuery && dataset.sample_questions.length > 0 && (
        <div className="mt-4 space-y-1">
          {dataset.sample_questions.slice(0, 3).map((q) => (
            <button
              key={q}
              onClick={() => navigate(`/chat?q=${encodeURIComponent(q)}`)}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-sm text-brand-700 hover:bg-brand-50"
            >
              <MessageSquareText className="size-3.5 shrink-0" /> {q}
            </button>
          ))}
        </div>
      )}

      <div className="mt-auto pt-4">
        {canQuery ? (
          <button onClick={() => setShowColumns(!showColumns)} className="flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-700">
            Cấu trúc dữ liệu <ChevronDown className={`size-3.5 transition-transform ${showColumns ? "rotate-180" : ""}`} />
          </button>
        ) : (
          dataset.access_status === "none" && (
            <Button size="sm" variant="secondary" onClick={() => setRequestOpen(true)}>
              Yêu cầu truy cập
            </Button>
          )
        )}
        {showColumns &&
          dataset.tables.map((t) => (
            <div key={t.name} className="mt-2 rounded-lg border border-slate-200">
              <p className="border-b border-slate-200 bg-slate-50 px-3 py-1.5 font-mono text-xs">{t.name}</p>
              <ul className="divide-y divide-slate-100 text-xs">
                {t.columns.map((c) => (
                  <li key={c.name} className="flex gap-3 px-3 py-1">
                    <span className="w-36 shrink-0 font-mono text-slate-700">{c.name}</span>
                    <span className="w-14 shrink-0 text-slate-400">{c.type}</span>
                    <span className="text-slate-500">{c.description}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
      </div>
      <RequestAccessDialog open={requestOpen} onClose={() => setRequestOpen(false)} datasetCode={dataset.code} datasetName={dataset.name} />
    </Card>
  );
}

export function CatalogPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-6 py-8">
        <h1 className="text-xl font-semibold">Danh mục dữ liệu</h1>
        <p className="mt-1 text-sm text-slate-500">
          Các dataset trợ lý được phép truy vấn. Dataset “cần cấp quyền” phải được quản trị viên phê duyệt.
        </p>
        <div className="mt-6">
          {isLoading && <Spinner label="Đang tải…" />}
          <ErrorText error={error} />
          <div className="grid gap-4 md:grid-cols-2">
            {data?.map((d) => (
              <DatasetCard key={d.code} dataset={d} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
