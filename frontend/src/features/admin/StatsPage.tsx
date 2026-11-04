import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../api/client";
import { Card, ErrorText, Spinner } from "../../components/ui";

const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
const ms = (v: number | null | undefined) => (v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`);
const num = (v: number | null | undefined) => (v == null ? "—" : new Intl.NumberFormat("vi-VN").format(v));

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
    </Card>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{children}</div>
    </section>
  );
}

export function StatsPage() {
  const [days, setDays] = useState(30);
  const { data: s, isLoading, error } = useQuery({ queryKey: ["stats", days], queryFn: () => api.stats(days) });

  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-6 py-8">
        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-xl font-semibold">Chất lượng & vận hành AI</h1>
            <p className="mt-1 text-sm text-slate-500">Số liệu tổng hợp từ query run — không chứa nội dung câu hỏi hay dữ liệu kết quả.</p>
          </div>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm">
            {[1, 7, 30, 90].map((d) => (
              <option key={d} value={d}>
                {d} ngày
              </option>
            ))}
          </select>
        </div>
        {isLoading && <div className="mt-6"><Spinner label="Đang tải…" /></div>}
        <ErrorText error={error} />
        {s && (
          <>
            <Section title="Kết quả">
              <Stat label="Tổng câu hỏi" value={num(s.totals.runs)} />
              <Stat label="Thực thi thành công" value={pct(s.rates.execution_success)} hint={`${num(s.totals.succeeded ?? 0)} thành công · ${num(s.totals.failed ?? 0)} lỗi`} />
              <Stat label="Hỏi lại để làm rõ" value={pct(s.rates.clarification)} />
              <Stat label="Thiếu quyền" value={pct(s.rates.access_required)} />
            </Section>
            <Section title="Guardrails">
              <Stat label="Input bị chặn" value={pct(s.rates.input_blocked)} hint="prompt injection, quá dài…" />
              <Stat label="SQL bị guard từ chối" value={pct(s.rates.guard_rejected)} />
              <Stat label="Diễn giải không kiểm chứng" value={pct(s.llm.ungrounded_explanation_rate)} hint="đã thay bằng bản tất định" />
              <Stat label="Route suy giảm" value={pct(s.llm.degraded_route_rate)} hint="fallback / demo" />
            </Section>
            <Section title="Human-in-the-loop">
              <Stat label="Tỷ lệ duyệt" value={pct(s.hitl.approval_rate)} hint={`${num(s.hitl.approved)} duyệt · ${num(s.hitl.auto_executed)} tự chạy`} />
              <Stat label="Tỷ lệ sửa SQL" value={pct(s.hitl.edit_rate)} hint="override rate" />
              <Stat label="Thời gian chờ duyệt (median)" value={s.hitl.median_seconds_to_approve == null ? "—" : `${s.hitl.median_seconds_to_approve} s`} />
              <Stat label="Hủy / hết hạn / thay thế" value={`${num(s.hitl.cancelled)} / ${num(s.hitl.expired)} / ${num(s.hitl.superseded)}`} />
            </Section>
            <Section title="Độ trễ & chi phí">
              <Stat label="Lập kế hoạch p50 / p95" value={`${ms(s.latency_ms.planning_p50)} / ${ms(s.latency_ms.planning_p95)}`} hint={`p99 ${ms(s.latency_ms.planning_p99)}`} />
              <Stat label="Thực thi SQL p95" value={ms(s.latency_ms.execution_p95)} />
              <Stat label="Chi phí LLM" value={`$${(s.llm.cost_usd ?? 0).toFixed(4)}`} hint={`${num((s.llm.prompt_tokens ?? 0) + (s.llm.completion_tokens ?? 0))} tokens`} />
              <Stat label="Plan cache hit" value={pct(s.llm.plan_cache_hit_rate)} />
            </Section>
            <Section title="Phản hồi người dùng">
              <Stat label="👍 Hữu ích" value={num(s.feedback.up)} />
              <Stat label="👎 Chưa đúng" value={num(s.feedback.down)} />
            </Section>

            <h2 className="mb-3 mt-8 text-sm font-semibold uppercase tracking-wide text-slate-500">Theo phiên bản prompt</h2>
            <Card className="overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-2">Prompt</th>
                    <th className="px-4 py-2 text-right">Câu hỏi</th>
                    <th className="px-4 py-2 text-right">Tỷ lệ chạy thành công</th>
                    <th className="px-4 py-2 text-right">Lập kế hoạch TB</th>
                    <th className="px-4 py-2 text-right">Chi phí TB</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {s.by_prompt_version.map((p) => (
                    <tr key={p.prompt_version ?? "none"}>
                      <td className="px-4 py-2 font-mono">{p.prompt_version ?? "—"}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{num(p.runs)}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{pct(p.success_share)}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{ms(p.avg_planning_ms)}</td>
                      <td className="px-4 py-2 text-right tabular-nums">${p.avg_cost_usd.toFixed(5)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
