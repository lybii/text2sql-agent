import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";
import { Badge, Card, ErrorText, Spinner, type Tone } from "../../components/ui";
import { formatDateTime } from "../../lib/format";

function tone(action: string): Tone {
  if (/(failed|rejected|revoked|blocked)/.test(action)) return "red";
  if (/(approved|executed)/.test(action)) return "green";
  if (/(edited|auto_executed)/.test(action)) return "violet";
  if (/(cancelled|expired|superseded)/.test(action)) return "slate";
  return "blue";
}

export function AuditPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ["audit"], queryFn: api.audit });
  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-6 py-8">
        <h1 className="text-xl font-semibold">Nhật ký audit</h1>
        <p className="mt-1 text-sm text-slate-500">Append-only: cơ sở dữ liệu từ chối mọi lệnh sửa hoặc xóa bảng này.</p>
        <Card className="mt-6 overflow-hidden">
          {isLoading && <div className="p-4"><Spinner label="Đang tải…" /></div>}
          <ErrorText error={error} />
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2">Thời điểm</th>
                <th className="px-4 py-2">Người thực hiện</th>
                <th className="px-4 py-2">Hành động</th>
                <th className="px-4 py-2">Đối tượng</th>
                <th className="px-4 py-2">Chi tiết</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data?.map((e) => (
                <tr key={e.id} className="align-top">
                  <td className="whitespace-nowrap px-4 py-2 text-slate-500">{formatDateTime(e.created_at)}</td>
                  <td className="px-4 py-2">{e.actor ?? "—"}</td>
                  <td className="px-4 py-2">
                    <Badge tone={tone(e.action)}>{e.action}</Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2 font-mono text-xs">
                    {e.entity}#{e.entity_id}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-slate-500">
                    {Object.entries(e.detail)
                      .filter(([, v]) => v !== null && v !== undefined)
                      .map(([k, v]) => `${k}=${typeof v === "string" && v.length > 16 ? v.slice(0, 12) + "…" : String(v)}`)
                      .join("  ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}
